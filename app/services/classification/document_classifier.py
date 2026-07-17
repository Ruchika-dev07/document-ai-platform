"""
Page-level document classifier.

Keywords are loaded from classification_config.json rather than
hardcoded, so they can be edited without touching code. Reloaded fresh
on every call to classify_page so config edits take effect without
restarting the server.

Classification logic (header/title area only, first `header_chars`
characters):
1. Check exclusion keywords first (e.g. "Credit Memo") - if any exclusion
   keyword is present, the page is NEVER classified as Invoice, even if
   an include keyword also matches. This prevents credit memos/notes
   from being misfiled as invoices just because they share the word
   "Invoice" in a compound heading like "Tax Purchase_Credit Memo".
2. Check JV include keywords.
3. Check Invoice include keywords (only if no exclusion matched).
4. Anything else defaults to Supporting Document.
"""

import json
import os
from typing import Optional

CATEGORY_JV = "JV"
CATEGORY_INVOICE = "Invoice"
CATEGORY_SUPPORTING = "Supporting Document"

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "classification_config.json")


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def classify_page(page_text: str) -> dict:
    """
    Classifies a single page's OCR/text content using the header/title
    area, checking exclusions before inclusions.
    """
    config = _load_config()
    header_chars = config.get("header_chars", 200)
    full_text_upper = (page_text or "").upper()
    header_upper = full_text_upper[:header_chars]

    jv_keywords = config.get("jv_include_keywords", [])
    invoice_include = config.get("invoice_include_keywords", [])
    invoice_exclude = config.get("invoice_exclude_keywords", [])

    # Exclusions checked first - if present, this page can never be
    # classified as Invoice regardless of other keyword matches.
    excluded = any(kw.upper() in header_upper for kw in invoice_exclude)

    for kw in jv_keywords:
        if kw.upper() in header_upper:
            return {"category": CATEGORY_JV, "confidence": 0.9, "matched_keyword": kw}

    if not excluded:
        for kw in invoice_include:
            if kw.upper() in header_upper:
                return {"category": CATEGORY_INVOICE, "confidence": 0.9, "matched_keyword": kw}

    # Fallback: full-text pass, strict phrases only (skips the single
    # broad "INVOICE" keyword to avoid false positives from trial
    # balance tables listing "Invoice" as a row/document-type value)
    strict_invoice = [kw for kw in invoice_include if kw.upper() not in ("INVOICE", "فاتورة")]

    for kw in jv_keywords:
        if kw.upper() in full_text_upper:
            return {"category": CATEGORY_JV, "confidence": 0.55, "matched_keyword": kw}

    if not excluded:
        for kw in strict_invoice:
            if kw.upper() in full_text_upper:
                return {"category": CATEGORY_INVOICE, "confidence": 0.55, "matched_keyword": kw}

    reason = "matched exclusion keyword" if excluded else None
    return {"category": CATEGORY_SUPPORTING, "confidence": 0.4, "matched_keyword": reason}


def group_pages_into_blocks(page_classifications: list) -> list:
    """
    Groups classified pages into blocks:
    - JV and Invoice pages are numbered individually (JV 1, Invoice 1,
      Invoice 2, ...) even if scattered across the document.
    - ALL Supporting Document pages across the entire document are
      merged into a single block ("Supporting Document 1"), regardless
      of whether they're consecutive or scattered - since supporting
      docs aren't the "main" document type and don't need per-section
      splitting.
    - Any other category (from a single-document-type upload, e.g.
      "Emirates ID") is also grouped as one block per category.
    """
    blocks_by_category = {}
    invoice_counter = 0
    jv_counter = 0
    ordered_blocks = []

    for page in page_classifications:
        category = page["category"]
        page_number = page["page_number"]

        if category == CATEGORY_SUPPORTING:
            if CATEGORY_SUPPORTING not in blocks_by_category:
                block = {"block_label": "Supporting Document 1", "category": CATEGORY_SUPPORTING, "pages": []}
                blocks_by_category[CATEGORY_SUPPORTING] = block
                ordered_blocks.append(block)
            blocks_by_category[CATEGORY_SUPPORTING]["pages"].append(page_number)

        elif category == CATEGORY_JV:
            jv_counter += 1
            block = {"block_label": f"JV {jv_counter}", "category": CATEGORY_JV, "pages": [page_number]}
            ordered_blocks.append(block)

        elif category == CATEGORY_INVOICE:
            invoice_counter += 1
            block = {"block_label": f"Invoice {invoice_counter}", "category": CATEGORY_INVOICE, "pages": [page_number]}
            ordered_blocks.append(block)

        else:
            # Single-document-type mode (e.g. every page tagged
            # "Emirates ID" directly) - one block per category, all
            # pages merged together.
            if category not in blocks_by_category:
                block = {"block_label": f"{category} 1", "category": category, "pages": []}
                blocks_by_category[category] = block
                ordered_blocks.append(block)
            blocks_by_category[category]["pages"].append(page_number)

    return ordered_blocks