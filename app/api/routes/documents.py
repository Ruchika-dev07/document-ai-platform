"""
Multi-page document upload, split, and classification endpoint.

This is the "Document Upload -> split into pages -> classify each page ->
group into blocks (JV / Invoice / Supporting Document)" flow.

Flow:
1. Upload a multi-page PDF (e.g. a 128-page batch containing JVs,
   invoices, and supporting documents mixed together)
2. Split into individual page images (thumbnails), saved to disk
3. Extract text per page for classification purposes:
   - Try the PDF's embedded text layer first (free, instant)
   - If empty (fully scanned pages, confirmed to be the case on real
     test documents), fall back to Tesseract OCR (free, local, no API
     cost) - this is a classification-only pass, not the final
     high-accuracy extraction
4. Classify each page (JV / Invoice / Supporting Document) based on
   that text
5. Group consecutive Supporting Document pages into blocks
6. Return a JSON structure describing every page + block, ready for the
   frontend to render as thumbnails with category tags

Azure Document Intelligence (higher accuracy, but costs per page) is
intentionally NOT called here - it's reserved for the deeper field
extraction step that runs AFTER a block is confirmed as JV or Invoice,
not for every page during this fast classification pass.
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


def _get_page_text(page, thumb_path: str) -> str:
    """
    Gets text for classification: tries the PDF's embedded text layer
    first (instant, free). Falls back to Tesseract OCR on the page
    image if that's empty (confirmed necessary for fully-scanned PDFs).
    """
    text = page.extract_text() or ""
    if text.strip():
        return text

    # No embedded text layer - fall back to local OCR on the thumbnail
    # we already saved for this page.
    try:
        from PIL import Image
        return pytesseract.image_to_string(Image.open(thumb_path))
    except Exception:
        return ""


@router.post("/documents/split")
async def split_document(file: UploadFile = File(...)):
    """
    Uploads a multi-page PDF, splits it into page thumbnails, classifies
    each page, and groups pages into JV / Invoice / Supporting Document
    blocks.
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

    try:
        with pdfplumber.open(saved_path) as pdf:
            total_pages = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                page_number = i + 1

                # Save a thumbnail image for the UI to display (and for
                # OCR fallback if there's no text layer).
                thumb_filename = f"{batch_id}_page_{page_number}.png"
                thumb_path = os.path.join(THUMBNAIL_DIR, thumb_filename)
                im = page.to_image(resolution=100)
                im.save(thumb_path)

                page_text = _get_page_text(page, thumb_path)
                classification = classify_page(page_text)

                page_classifications.append({
                    "page_number": page_number,
                    "thumbnail_path": thumb_path,
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