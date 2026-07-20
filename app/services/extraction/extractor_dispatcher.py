"""
Extraction dispatcher.

This is the single decision point that routes a classified page to the
correct extractor based on its category. Classification (what type of
document is this?) and extraction (what data is on it?) are
deliberately kept in separate modules:

- Classification lives in app/services/classification/document_classifier.py
- Extraction logic lives in this folder, one file per document type

This file is the glue between them: given a category, it calls the
matching extractor and returns a consistent response shape regardless
of which underlying extractor ran.

To add a new document type's extraction logic:
1. Write a new extractor file in this folder (e.g. emiratesid_extractor.py)
2. Add one line to CATEGORY_DISPATCH below
No other code needs to change.
"""

from typing import Callable, Optional

from app.services.extraction.invoice_extractor import extract_invoice_fields
from app.services.extraction.jv_extractor import extract_jv_fields
from app.services.extraction.passport_extractor import extract_passport_fields


def _supporting_document_handler(**kwargs) -> dict:
    """
    Supporting Documents are deliberately NOT deeply extracted - per
    the original requirement, they're the "not main document" category,
    grouped as one block and passed through as-is rather than having
    structured fields pulled from them.
    """
    return {
        "extraction_method": "none",
        "note": "Supporting Documents are not individually extracted - "
                "they're grouped and passed through as reference material "
                "alongside the main JV/Invoice records.",
    }


def _generic_fallback_handler(raw_text: str = "", **kwargs) -> dict:
    """Used for any category with no dedicated extractor yet."""
    return {
        "raw_text_preview": (raw_text or "")[:200].strip(),
        "extraction_method": "none",
        "note": "No dedicated extractor exists yet for this document type. "
                "Showing raw OCR text as a fallback.",
    }


# The actual "if category is X, extract like Y" logic.
# Each handler receives whatever kwargs the caller has available
# (raw_text, analyze_result, etc.) and returns a fields dict.
CATEGORY_DISPATCH = {
    "JV": lambda **kwargs: extract_jv_fields(kwargs.get("raw_text", "")),
    "Invoice": lambda **kwargs: extract_invoice_fields(kwargs.get("analyze_result", {})),
    "Passport": lambda **kwargs: extract_passport_fields(kwargs.get("raw_text", "")),
    "Supporting Document": _supporting_document_handler,
}


def dispatch_extraction(category: str, **kwargs) -> dict:
    """
    Routes to the correct extractor based on category. Falls back to a
    generic handler for any category without a dedicated extractor
    (e.g. "Emirates ID", "Resume", "Contract" - not built yet).
    """
    handler = CATEGORY_DISPATCH.get(category, _generic_fallback_handler)
    return handler(**kwargs)