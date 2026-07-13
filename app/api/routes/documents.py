"""
Multi-page document upload, split, classification, and metadata extraction.
"""

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
from app.services.ocr.azure_ocr_service import analyze_invoice

router = APIRouter()

UPLOAD_DIR = "uploads"
THUMBNAIL_DIR = "uploads/page_thumbnails"
OCR_RESOLUTION = 200  # higher res + preprocessing fixed real misreads like
                      # "Tax Purchase - Invoice" -> "Fax Purchase - Iriwesioe"


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
                    "thumbnail_path": thumb_path,
                    "category": classification["category"],
                    "confidence": classification["confidence"],
                    "matched_keyword": classification["matched_keyword"],
                    "needs_review": classification["confidence"] < 0.6,
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

    blocks = group_pages_into_blocks(page_classifications)

    for p in page_classifications:
        p.pop("thumbnail_path", None)

    return {
        "batch_id": batch_id,
        "filename": file.filename,
        "total_pages": total_pages,
        "pages": page_classifications,
        "blocks": blocks,
        "summary": {
            "jv_count": sum(1 for b in blocks if b["category"] == "JV"),
            "invoice_count": sum(1 for b in blocks if b["category"] == "Invoice"),
            "supporting_document_count": sum(1 for b in blocks if b["category"] == "Supporting Document"),
        },
    }


class ExtractRequest(BaseModel):
    batch_id: str
    page_number: int


@router.post("/documents/extract-block")
async def extract_block(req: ExtractRequest):
    """
    Runs real Azure Document Intelligence extraction on a single page
    (the first page of an Invoice block) and returns structured fields.
    Uses the exact same extraction pipeline already validated earlier
    (azure_ocr_service.py + invoice_extractor.py).
    """
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{req.batch_id}_page_{req.page_number}.png")
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Page image not found. Re-upload the document.")

    try:
        analyze_result = analyze_invoice(thumb_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure OCR call failed: {str(e)}")

    fields = extract_invoice_fields(analyze_result)
    return {"page_number": req.page_number, "fields": fields}