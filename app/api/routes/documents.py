"""
Multi-page document upload, split, and classification endpoint.
"""

import os
import shutil
import uuid

import pdfplumber
import pytesseract
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.classification.document_classifier import (
    classify_page,
    group_pages_into_blocks,
)

router = APIRouter()

UPLOAD_DIR = "uploads"
THUMBNAIL_DIR = "uploads/page_thumbnails"


def _get_page_text(page, thumb_path: str, page_number: int) -> str:
    """
    Gets text for classification: tries the PDF's embedded text layer
    first (instant, free). Falls back to Tesseract OCR on the page
    image if that's empty.

    Errors are printed to the server console (not silently swallowed)
    so a broken Tesseract install shows up immediately instead of
    quietly misclassifying every page.
    """
    text = page.extract_text() or ""
    if text.strip():
        return text

    try:
        from PIL import Image
        ocr_text = pytesseract.image_to_string(Image.open(thumb_path))
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
                # Higher resolution than before (150 vs 100) - small
                # thumbnails at low res were likely too blurry for
                # Tesseract to reliably read header text like
                # "JOURNAL VOUCHER" or "TAX INVOICE".
                im = page.to_image(resolution=150)
                im.save(thumb_path)

                page_text = _get_page_text(page, thumb_path, page_number)
                classification = classify_page(page_text)

                if page_number <= 3:
                    print(f"[DEBUG] Page {page_number} OCR preview: {page_text[:80]!r} -> {classification['category']}")

                page_classifications.append({
                    "page_number": page_number,
                    "thumbnail_url": f"/thumbnails/{thumb_filename}",
                    "category": classification["category"],
                    "confidence": classification["confidence"],
                    "matched_keyword": classification["matched_keyword"],
                    "needs_review": classification["confidence"] < 0.6,
                })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

    blocks = group_pages_into_blocks(page_classifications)

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