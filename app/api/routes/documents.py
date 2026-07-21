"""
Multi-page document upload, split, classification, extraction,
persistence, and per-category PDF download.
"""

import json
import os
import shutil
import uuid
from io import BytesIO

import pdfplumber
import pytesseract
from PIL import Image, ImageOps
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

# Hardcode the Tesseract binary path instead of relying on shell PATH.
# Homebrew adds /opt/homebrew/bin to PATH only for zsh (via ~/.zprofile),
# but bash sessions never get it, causing intermittent "tesseract not
# found" failures depending on which terminal tab is running.
# Windows installs to Program Files by default instead.
for _candidate in [
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
]:
    if os.path.exists(_candidate):
        pytesseract.pytesseract.tesseract_cmd = _candidate
        break

from app.services.classification.document_classifier import (
    classify_page,
    group_pages_into_blocks,
)
from app.services.extraction.invoice_extractor import extract_invoice_fields
from app.services.extraction.jv_extractor import extract_jv_fields
from app.services.ocr.azure_ocr_service import analyze_invoice
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import Depends
from app.database.connection import get_db
from app.models.document_record import DocumentRecord

router = APIRouter()

UPLOAD_DIR = "uploads"
THUMBNAIL_DIR = "uploads/page_thumbnails"
STATE_DIR = "uploads/batch_state"
OCR_RESOLUTION = 200

# Document types that skip the JV/Invoice/Supporting classifier entirely
# and instead tag every page as the same single category - for batches
# that are known in advance to be all one type (e.g. 100 Emirates IDs).
SINGLE_TYPE_OPTIONS = {"Emirates ID", "Passport", "Resume", "Contract"}


def _state_path(batch_id: str) -> str:
    return os.path.join(STATE_DIR, f"{batch_id}.json")


def _save_state(batch_id: str, data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_path(batch_id), "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_state(batch_id: str) -> dict:
    path = _state_path(batch_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Batch not found. It may have expired or never existed.")
    with open(path) as f:
        return json.load(f)


def _recompute(data: dict) -> dict:
    blocks = group_pages_into_blocks(data["pages"])
    data["blocks"] = blocks
    counts = {}
    for b in blocks:
        counts[b["category"]] = counts.get(b["category"], 0) + 1
    data["summary"] = {
        "jv_count": counts.get("JV", 0),
        "invoice_count": counts.get("Invoice", 0),
        "supporting_document_count": counts.get("Supporting Document", 0),
        "other_counts": {k: v for k, v in counts.items() if k not in ("JV", "Invoice", "Supporting Document")},
    }
    return data


HEADER_FRACTION = 0.20  # top 20% of the page, by visual position


def _get_page_header_and_full_text(page, thumb_path: str, page_number: int):
    """
    Returns (header_text, full_text) where header_text is built from
    only the words positioned in the top 20% of the page, by actual
    pixel/point position - not a character-count slice of the text
    stream. This matters because OCR/PDF text order does not always
    match visual top-to-bottom layout on multi-column documents.
    """
    full_text = page.extract_text() or ""

    if full_text.strip():
        # Text-layer PDF: pdfplumber gives word-level bounding boxes
        # directly, no OCR needed.
        try:
            words = page.extract_words()
            cutoff = page.height * HEADER_FRACTION
            header_words = [w["text"] for w in words if w["top"] < cutoff]
            header_text = " ".join(header_words)
            return header_text, full_text
        except Exception as e:
            print(f"[WARN] Page {page_number}: word position extraction failed ({e}), using full text as header.")
            return full_text, full_text

    # No text layer - fall back to OCR, using Tesseract'''s own word
    # bounding boxes (image_to_data) to isolate the top 20% region.
    try:
        img = Image.open(thumb_path).convert("L")
        img = ImageOps.autocontrast(img)
        full_text = pytesseract.image_to_string(img)

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        img_height = img.height
        cutoff = img_height * HEADER_FRACTION
        header_words = [
            data["text"][i] for i in range(len(data["text"]))
            if data["top"][i] < cutoff and data["text"][i].strip()
        ]
        header_text = " ".join(header_words)

        if not full_text.strip():
            print(f"[WARN] Page {page_number}: Tesseract returned empty text.")
        return header_text, full_text
    except Exception as e:
        print(f"[ERROR] Page {page_number}: Tesseract OCR failed - {type(e).__name__}: {e}")
        return "", ""


@router.post("/documents/split")
async def split_document(file: UploadFile = File(...), doc_type: str = Form(default="Mixed")):
    """
    doc_type: "Mixed" runs the real JV/Invoice/Supporting classifier.
    Any other value (e.g. "Emirates ID") skips classification entirely
    and tags every page with that value directly, since the batch is
    already known to be a single document type.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for splitting.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)

    batch_id = str(uuid.uuid4())[:8]
    saved_path = os.path.join(UPLOAD_DIR, f"{batch_id}_{file.filename}")

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    page_classifications = []
    single_type_mode = doc_type != "Mixed"

    try:
        with pdfplumber.open(saved_path) as pdf:
            total_pages = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                page_number = i + 1
                thumb_filename = f"{batch_id}_page_{page_number}.png"
                thumb_path = os.path.join(THUMBNAIL_DIR, thumb_filename)
                im = page.to_image(resolution=OCR_RESOLUTION)
                im.save(thumb_path)

                if single_type_mode:
                    category, confidence, matched_keyword = doc_type, 1.0, None
                else:
                    header_text, full_text = _get_page_header_and_full_text(page, thumb_path, page_number)
                    result = classify_page(header_text, full_text)
                    category, confidence, matched_keyword = result["category"], result["confidence"], result["matched_keyword"]

                page_classifications.append({
                    "page_number": page_number,
                    "thumbnail_url": f"/thumbnails/{thumb_filename}",
                    "category": category,
                    "confidence": confidence,
                    "matched_keyword": matched_keyword,
                    "needs_review": confidence < 0.6,
                    "manually_corrected": False,
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

    data = {
        "batch_id": batch_id,
        "filename": file.filename,
        "original_pdf_path": saved_path,
        "doc_type": doc_type,
        "total_pages": total_pages,
        "pages": page_classifications,
    }
    data = _recompute(data)
    _save_state(batch_id, data)

    return data


@router.get("/documents/batch/{batch_id}")
async def get_batch(batch_id: str):
    data = _load_state(batch_id)
    return _recompute(data)


class ReassignRequest(BaseModel):
    batch_id: str
    page_number: int
    category: str


@router.post("/documents/reassign")
async def reassign_page(req: ReassignRequest):
    data = _load_state(req.batch_id)
    page = next((p for p in data["pages"] if p["page_number"] == req.page_number), None)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found in this batch.")

    page["category"] = req.category
    page["confidence"] = 1.0
    page["needs_review"] = False
    page["manually_corrected"] = True

    data = _recompute(data)
    _save_state(req.batch_id, data)
    return data


class ExtractRequest(BaseModel):
    batch_id: str
    page_number: int


@router.post("/documents/extract-invoice")
async def extract_invoice_block(req: ExtractRequest, db: Session = Depends(get_db)):
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{req.batch_id}_page_{req.page_number}.png")
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Page image not found. Re-upload the document.")

    try:
        analyze_result = analyze_invoice(thumb_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure OCR call failed: {str(e)}")

    fields = extract_invoice_fields(analyze_result)

    # Save to database. Date comes back as "YYYY-MM-DD" string from
    # Azure - parse it, but don't fail the whole request if it's
    # missing/unparseable, just store it as null.
    parsed_date = None
    if fields.get("invoice_date"):
        try:
            parsed_date = datetime.strptime(fields["invoice_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    amount = None
    if fields.get("invoice_total") and isinstance(fields["invoice_total"], dict):
        amount = fields["invoice_total"].get("amount")

    record = DocumentRecord(
        batch_id=req.batch_id,
        page_number=req.page_number,
        category="Invoice",
        invoice_no=fields.get("invoice_id"),
        vendor=fields.get("vendor_name"),
        amount=amount,
        invoice_date=parsed_date,
        status="extracted",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {"page_number": req.page_number, "category": "Invoice", "fields": fields, "saved_record_id": record.id}


@router.post("/documents/extract-jv")
async def extract_jv_block(req: ExtractRequest, db: Session = Depends(get_db)):
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{req.batch_id}_page_{req.page_number}.png")
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Page image not found. Re-upload the document.")

    try:
        img = Image.open(thumb_path).convert("L")
        img = ImageOps.autocontrast(img)
        text = pytesseract.image_to_string(img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")

    fields = extract_jv_fields(text)

    parsed_date = None
    if fields.get("date"):
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                parsed_date = datetime.strptime(fields["date"], fmt).date()
                break
            except (ValueError, TypeError):
                continue

    amount = None
    if fields.get("amount"):
        try:
            amount = float(fields["amount"].replace(",", ""))
        except (ValueError, AttributeError):
            pass

    record = DocumentRecord(
        batch_id=req.batch_id,
        page_number=req.page_number,
        category="JV",
        invoice_no=fields.get("jv_number"),
        vendor=None,
        amount=amount,
        invoice_date=parsed_date,
        status="extracted",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {"page_number": req.page_number, "category": "JV", "fields": fields, "saved_record_id": record.id}


@router.get("/documents/download")
async def download_category(batch_id: str, category: str):
    """
    Merges every page belonging to `category` (across all its blocks)
    into a single PDF, extracted losslessly from the original uploaded
    PDF (not re-rendered from thumbnails), and returns it as a download.
    """
    data = _load_state(batch_id)
    original_path = data.get("original_pdf_path")
    if not original_path or not os.path.exists(original_path):
        raise HTTPException(status_code=404, detail="Original PDF not found for this batch.")

    page_numbers = sorted(p["page_number"] for p in data["pages"] if p["category"] == category)
    if not page_numbers:
        raise HTTPException(status_code=404, detail=f"No pages found in category '{category}'.")

    reader = PdfReader(original_path)
    writer = PdfWriter()
    for page_num in page_numbers:
        writer.add_page(reader.pages[page_num - 1])

    buffer = BytesIO()
    writer.write(buffer)
    buffer.seek(0)

    safe_category = category.replace(" ", "_")
    filename = f"{safe_category}_{batch_id}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/documents/records")
async def list_records(batch_id: str = None, db: Session = Depends(get_db)):
    """Lists saved extraction records, optionally filtered by batch_id."""
    query = db.query(DocumentRecord)
    if batch_id:
        query = query.filter(DocumentRecord.batch_id == batch_id)
    records = query.order_by(DocumentRecord.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "batch_id": r.batch_id,
            "page_number": r.page_number,
            "category": r.category,
            "invoice_no": r.invoice_no,
            "vendor": r.vendor,
            "amount": float(r.amount) if r.amount is not None else None,
            "invoice_date": str(r.invoice_date) if r.invoice_date else None,
            "status": r.status,
            "created_at": str(r.created_at),
        }
        for r in records
    ]


class UnifiedExtractRequest(BaseModel):
    batch_id: str
    page_number: int
    category: str


@router.post("/documents/extract")
async def extract_by_category(req: UnifiedExtractRequest, db: Session = Depends(get_db)):
    """
    Single entry point for extraction. Looks at the page's category and
    routes to the correct extractor via dispatch_extraction() - this is
    the actual "if JV do X, if Invoice do Y, if Passport do Z" logic,
    kept separate from classification (which already happened earlier,
    during /documents/split).
    """
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{req.batch_id}_page_{req.page_number}.png")
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Page image not found. Re-upload the document.")

    kwargs = {}

    if req.category == "Invoice":
        try:
            kwargs["analyze_result"] = analyze_invoice(thumb_path)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Azure OCR call failed: {str(e)}")
    elif req.category in ("JV", "Passport"):
        try:
            img = Image.open(thumb_path).convert("L")
            img = ImageOps.autocontrast(img)
            kwargs["raw_text"] = pytesseract.image_to_string(img)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")

    fields = dispatch_extraction(req.category, **kwargs)

    # Persist to database where we have a schema that fits (Invoice/JV).
    # Passport and other types return fields for display but aren't
    # saved yet - the current table schema (invoice_no/vendor/amount/
    # invoice_date) doesn't have passport-appropriate columns
    # (surname/nationality/DOB) without a migration, which is a
    # reasonable next step rather than shoehorning data into the wrong
    # columns now.
    saved_record_id = None
    if req.category == "Invoice":
        parsed_date = None
        if fields.get("invoice_date"):
            try:
                parsed_date = datetime.strptime(fields["invoice_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass
        amount = fields["invoice_total"].get("amount") if isinstance(fields.get("invoice_total"), dict) else None
        record = DocumentRecord(
            batch_id=req.batch_id, page_number=req.page_number, category="Invoice",
            invoice_no=fields.get("invoice_id"), vendor=fields.get("vendor_name"),
            amount=amount, invoice_date=parsed_date, status="extracted",
        )
        db.add(record); db.commit(); db.refresh(record)
        saved_record_id = record.id

    elif req.category == "JV":
        parsed_date = None
        if fields.get("date"):
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
                try:
                    parsed_date = datetime.strptime(fields["date"], fmt).date()
                    break
                except (ValueError, TypeError):
                    continue
        amount = None
        if fields.get("amount"):
            try:
                amount = float(fields["amount"].replace(",", ""))
            except (ValueError, AttributeError):
                pass
        record = DocumentRecord(
            batch_id=req.batch_id, page_number=req.page_number, category="JV",
            invoice_no=fields.get("jv_number"), vendor=None,
            amount=amount, invoice_date=parsed_date, status="extracted",
        )
        db.add(record); db.commit(); db.refresh(record)
        saved_record_id = record.id

    return {
        "page_number": req.page_number,
        "category": req.category,
        "fields": fields,
        "saved_record_id": saved_record_id,
    }