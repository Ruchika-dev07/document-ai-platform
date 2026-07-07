"""
Document upload endpoint.

Accepts a file via a web request, saves it, and runs it through the
full pipeline we've already built: OCR (Azure) -> extraction -> validation
-> duplicate check.

This is the "Document Upload" stage from architecture doc section 3,
wired directly into the OCR/extraction/validation stages that already work.
"""

import os
import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.ocr.azure_ocr_service import analyze_invoice
from app.services.extraction.invoice_extractor import extract_invoice_fields
from app.services.validation.invoice_validator import validate_invoice
from app.services.validation.duplicate_checker import check_duplicate

router = APIRouter()

UPLOAD_DIR = "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload an invoice image/PDF. Runs it through OCR, extraction, and
    validation, and returns the combined result.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        analyze_result = analyze_invoice(saved_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Azure OCR call failed: {str(e)}")

    fields = extract_invoice_fields(analyze_result)
    validation_result = validate_invoice(fields)
    duplicate_result = check_duplicate(fields)

    return {
        "filename": file.filename,
        "extracted_fields": fields,
        "validation": validation_result,
        "duplicate_check": duplicate_result,
    }
