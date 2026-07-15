"""
Page-level document classifier.

Classifies based on the page's HEADER/TITLE area (first ~200 characters),
not the whole page body. This matters because:
- "Invoice" legitimately appears as a column value inside Supporting
  Document trial-balance tables (e.g. "Document Type: Invoice"), which
  would cause false positives if we scanned the whole page.
- pdfplumber sometimes scrambles word order on multi-column layouts, so
  exact phrases like "Invoice No" can get split apart in the body text -
  but titles near the top of the page are short and stay intact.

If nothing matches in the header, we fall back to scanning the full
page text at lower confidence, so genuinely ambiguous pages still get
flagged "needs review" rather than silently misfiled.
"""

from typing import Optional

CATEGORY_JV = "JV"
CATEGORY_INVOICE = "Invoice"
CATEGORY_SUPPORTING = "Supporting Document"

HEADER_CHARS = 200

JV_KEYWORDS = ["JOURNAL VOUCHER", "سند قيد", "JV NO", "JOURNAL ENTRY"]
INVOICE_STRICT_KEYWORDS = ["TAX INVOICE", "ORIGINAL INVOICE", "TAX PURCHASE", "INVOICE NO", "فاتورة ضريبية"]
INVOICE_HEADER_ONLY_KEYWORDS = ["TAX INVOICE", "فاتورة ضريبية", "Tax Purchase - Invoice"]  # too broad to trust outside the header/title area


def classify_page(page_text: str) -> dict:
    """
    Classifies a single page's OCR/text content.
    Returns {"category": str, "confidence": float, "matched_keyword": str|None}
    """
    full_text_upper = (page_text or "").upper()
    header_upper = full_text_upper[:HEADER_CHARS]

    # Pass 1: header/title area - checks both strict phrases AND the
    # broad "INVOICE" keyword, since a page's title is a reliable signal.
    for kw in JV_KEYWORDS:
        if kw.upper() in header_upper:
            return {"category": CATEGORY_JV, "confidence": 0.9, "matched_keyword": kw}

    for kw in INVOICE_STRICT_KEYWORDS + INVOICE_HEADER_ONLY_KEYWORDS:
        if kw.upper() in header_upper:
            return {"category": CATEGORY_INVOICE, "confidence": 0.9, "matched_keyword": kw}

    # Pass 2: full page text fallback, strict phrases only - the broad
    # "INVOICE" keyword is deliberately excluded here, since Supporting
    # Document trial-balance tables list "Invoice" as a row/document-type
    # value dozens of times per page, which would cause false positives.
    for kw in JV_KEYWORDS:
        if kw.upper() in full_text_upper:
            return {"category": CATEGORY_JV, "confidence": 0.55, "matched_keyword": kw}

    for kw in INVOICE_STRICT_KEYWORDS:
        if kw.upper() in full_text_upper:
            return {"category": CATEGORY_INVOICE, "confidence": 0.55, "matched_keyword": kw}

    return {"category": CATEGORY_SUPPORTING, "confidence": 0.4, "matched_keyword": None}


def group_pages_into_blocks(page_classifications: list) -> list:
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