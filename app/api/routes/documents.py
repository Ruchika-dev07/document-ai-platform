"""
Multi-page document upload, split, classification, extraction, and
persistence of manual corrections.

Persistence design: each upload gets a batch_id. The full page/block
state is saved to uploads/{batch_id}_state.json after splitting, and
updated every time a page is manually recategorized. The frontend
stores batch_id in the URL hash, so refreshing the page re-fetches the
saved state via GET /documents/batch/{batch_id} instead of losing all
progress and needing a re-upload.
"""

import json
import os
import shutil
import uuid

import pdfplumber
import pytesseract
from PIL import Image, ImageOps
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.classification.document_classifier import (
    classify_page,
    group_pages_into_blocks,
)
from app.services.extraction.invoice_extractor import extract_invoice_fields
from app.services.extraction.jv_extractor import extract_jv_fields
from app.services.ocr.azure_ocr_service import analyze_invoice

router = APIRouter()

UPLOAD_DIR = "uploads"
THUMBNAIL_DIR = "uploads/page_thumbnails"
STATE_DIR = "uploads/batch_state"
OCR_RESOLUTION = 200


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
    """Rebuilds blocks + summary from the current per-page categories."""
    blocks = group_pages_into_blocks(data["pages"])
    data["blocks"] = blocks
    data["summary"] = {
        "jv_count": sum(1 for b in blocks if b["category"] == "JV"),
        "invoice_count": sum(1 for b in blocks if b["category"] == "Invoice"),
        "supporting_document_count": sum(1 for b in blocks if b["category"] == "Supporting Document"),
    }
    return data


def _get_page_text(page, thumb_path: str, page_number: int) -> str:
    text = page.extract_text() or ""
    if text.strip():
        return text
    try:
        img = Image.open(thumb_path).convert("L")
        img = ImageOps.autocontrast(img)
        ocr_text = pytesseract.image_to_string(img)
        if not ocr_text.strip():
            print(f"[WARN] Page {page_number}: Tesseract returned empty text.")
        return ocr_text
    except Exception as e:
        print(f"[ERROR] Page {page_number}: Tesseract OCR failed - {type(e).__name__}: {e}")
        return ""


@router.post("/documents/split")
async def split_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for splitting.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)

    batch_id = str(uuid.uuid4())[:8]
    saved_path = os.path.join(UPLOAD_DIR, f"{batch_id}_{file.filename}")

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    page_classifications = []

    try:
        with pdfplumber.open(saved_path) as pdf:
            total_pages = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                page_number = i + 1
                thumb_filename = f"{batch_id}_page_{page_number}.png"
                thumb_path = os.path.join(THUMBNAIL_DIR, thumb_filename)
                im = page.to_image(resolution=OCR_RESOLUTION)
                im.save(thumb_path)

                page_text = _get_page_text(page, thumb_path, page_number)
                classification = classify_page(page_text)

                page_classifications.append({
                    "page_number": page_number,
                    "thumbnail_url": f"/thumbnails/{thumb_filename}",
                    "category": classification["category"],
                    "confidence": classification["confidence"],
                    "matched_keyword": classification["matched_keyword"],
                    "needs_review": classification["confidence"] < 0.6,
                    "manually_corrected": False,
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

    data = {
        "batch_id": batch_id,
        "filename": file.filename,
        "total_pages": total_pages,
        "pages": page_classifications,
    }
    data = _recompute(data)
    _save_state(batch_id, data)

    return data


@router.get("/documents/batch/{batch_id}")
async def get_batch(batch_id: str):
    """Restores a previously split batch, including any manual corrections."""
    data = _load_state(batch_id)
    return _recompute(data)


class ReassignRequest(BaseModel):
    batch_id: str
    page_number: int
    category: str


@router.post("/documents/reassign")
async def reassign_page(req: ReassignRequest):
    """Manually recategorizes a page and persists the change."""
    if req.category not in ("JV", "Invoice", "Supporting Document"):
        raise HTTPException(status_code=400, detail="Invalid category.")

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
async def extract_invoice_block(req: ExtractRequest):
    """Runs real Azure Document Intelligence extraction on an Invoice page."""
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{req.batch_id}_page_{req.page_number}.png")
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Page image not found. Re-upload the document.")

    try:
        analyze_result = analyze_invoice(thumb_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure OCR call failed: {str(e)}")

    fields = extract_invoice_fields(analyze_result)
    return {"page_number": req.page_number, "category": "Invoice", "fields": fields}


@router.post("/documents/extract-jv")
async def extract_jv_block(req: ExtractRequest):
    """
    Runs regex-based JV extraction. No Azure prebuilt model exists for
    journal vouchers, so this re-OCRs the page and applies pattern
    matching (see jv_extractor.py) instead of calling Azure.
    """
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
    return {"page_number": req.page_number, "category": "JV", "fields": fields}