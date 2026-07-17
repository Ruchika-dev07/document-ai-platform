"""
Page-level document classifier.

Classification is based on the page's VISUAL top region (top 20% of
the page height, by word position), not a character-count slice of the
OCR text stream. This distinction matters: OCR text order doesn't
always match visual top-to-bottom layout, especially on multi-column
invoices where a right-column field label (e.g. "Vendor Invoice No")
can appear earlier in the extracted text than the actual document
title, even though it sits lower on the physical page. A character-
count "header" would wrongly catch that field label; a position-based
header correctly only looks at what's actually printed near the top of
the page.

Keywords are loaded from classification_config.json (editable without
touching code), reloaded fresh on every call.

Exclusions (e.g. "Credit Memo") are checked before inclusions - if an
exclusion keyword appears in the header, the page can never be
classified as Invoice, even if "Invoice" also appears in the header.
"""

import json
import os

CATEGORY_JV = "JV"
CATEGORY_INVOICE = "Invoice"
CATEGORY_SUPPORTING = "Supporting Document"

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "classification_config.json")


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def classify_page(header_text: str, full_text: str = "") -> dict:
    """
    Classifies a page using its VISUAL header region text (top 20% of
    the page, by word position - see documents.py for how this is
    extracted). `full_text` is used only as a lower-confidence fallback
    for JV keywords if the header is empty/unreadable; the broad
    "Invoice"/"فاتورة" keywords are deliberately NEVER checked outside
    the header, per the classification rule.
    """
    config = _load_config()
    header_upper = (header_text or "").upper()
    full_text_upper = (full_text or header_text or "").upper()

    jv_keywords = config.get("jv_include_keywords", [])
    invoice_include = config.get("invoice_include_keywords", [])
    invoice_exclude = config.get("invoice_exclude_keywords", [])

    excluded = any(kw.upper() in header_upper for kw in invoice_exclude)

    for kw in jv_keywords:
        if kw.upper() in header_upper:
            return {"category": CATEGORY_JV, "confidence": 0.9, "matched_keyword": kw}

    if not excluded:
        for kw in invoice_include:
            if kw.upper() in header_upper:
                return {"category": CATEGORY_INVOICE, "confidence": 0.9, "matched_keyword": kw}

    # Fallback only for JV, using full text at lower confidence, in case
    # the header region extraction failed for some reason. Invoice
    # keywords are NEVER checked outside the header - that's the rule.
    for kw in jv_keywords:
        if kw.upper() in full_text_upper:
            return {"category": CATEGORY_JV, "confidence": 0.55, "matched_keyword": kw}

    reason = "matched exclusion keyword in header" if excluded else None
    return {"category": CATEGORY_SUPPORTING, "confidence": 0.4, "matched_keyword": reason}


def group_pages_into_blocks(page_classifications: list) -> list:
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
            if category not in blocks_by_category:
                block = {"block_label": f"{category} 1", "category": category, "pages": []}
                blocks_by_category[category] = block
                ordered_blocks.append(block)
            blocks_by_category[category]["pages"].append(page_number)

    return ordered_blocks