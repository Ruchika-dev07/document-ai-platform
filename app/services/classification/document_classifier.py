"""
Page-level document classifier.

Given the raw text of a single page (from OCR or a text-based PDF layer),
predicts which category it belongs to: JV (Journal Voucher), Invoice, or
Supporting Document.

This is a fast, keyword-based first pass - no AI/API call needed per page,
which matters because a 100+ page document would otherwise mean 100+ Azure
calls just to classify. Real field extraction (via Azure) only runs AFTER
a page/block is confirmed as JV or Invoice - Supporting Documents are
grouped and stored, but not deeply extracted, matching the "supporting
docs aren't the main document" rule from the architecture discussion.

Confidence is returned alongside the category so the UI can flag
low-confidence pages as "Needs Review" (matching the auto-detected /
needs-review pattern from the reference UI).
"""

from typing import Optional

CATEGORY_JV = "JV"
CATEGORY_INVOICE = "Invoice"
CATEGORY_SUPPORTING = "Supporting Document"

# Keyword rules, checked in order. First match wins.
# Real-world documents are inconsistent, so we check a few phrasings per type.
JV_KEYWORDS = ["JOURNAL VOUCHER", "سند قيد", "JV NO", "JOURNAL ENTRY"]
INVOICE_KEYWORDS = ["TAX INVOICE", "ORIGINAL INVOICE", "INVOICE NO", "فاتورة ضريبية"]


def classify_page(page_text: str) -> dict:
    """
    Classifies a single page's OCR/text content.
    Returns {"category": str, "confidence": float, "matched_keyword": str|None}
    """
    text_upper = (page_text or "").upper()

    for kw in JV_KEYWORDS:
        if kw.upper() in text_upper:
            return {"category": CATEGORY_JV, "confidence": 0.9, "matched_keyword": kw}

    for kw in INVOICE_KEYWORDS:
        if kw.upper() in text_upper:
            return {"category": CATEGORY_INVOICE, "confidence": 0.9, "matched_keyword": kw}

    # No strong signal found - default to Supporting Document, but with
    # lower confidence so the UI can flag it for manual review rather than
    # silently misfiling it.
    return {"category": CATEGORY_SUPPORTING, "confidence": 0.4, "matched_keyword": None}


def group_pages_into_blocks(page_classifications: list) -> list:
    """
    Takes a list of per-page classification results (in page order) and
    groups them into blocks:
    - JV and Invoice pages are numbered individually (Invoice 1, Invoice 2, ...)
    - Consecutive Supporting Document pages are merged into a single block

    Input: [{"page_number": 1, "category": "JV", ...}, {"page_number": 2, "category": "Supporting Document", ...}, ...]
    Output: [{"block_label": "JV 1", "category": "JV", "pages": [1]}, {"block_label": "Supporting Document 1", "category": "Supporting Document", "pages": [2,3,4]}, ...]
    """
    blocks = []
    invoice_counter = 0
    jv_counter = 0
    supporting_counter = 0

    current_block = None

    for page in page_classifications:
        category = page["category"]
        page_number = page["page_number"]

        if category == CATEGORY_SUPPORTING:
            if current_block and current_block["category"] == CATEGORY_SUPPORTING:
                # extend the existing supporting-doc block
                current_block["pages"].append(page_number)
                continue
            else:
                supporting_counter += 1
                current_block = {
                    "block_label": f"Supporting Document {supporting_counter}",
                    "category": CATEGORY_SUPPORTING,
                    "pages": [page_number],
                }
                blocks.append(current_block)
        else:
            # JV and Invoice pages are always their own block, even if
            # a document happens to be multi-page (kept simple for now:
            # one page = one block for these two categories).
            if category == CATEGORY_JV:
                jv_counter += 1
                label = f"JV {jv_counter}"
            else:
                invoice_counter += 1
                label = f"Invoice {invoice_counter}"

            current_block = {
                "block_label": label,
                "category": category,
                "pages": [page_number],
            }
            blocks.append(current_block)

    return blocks