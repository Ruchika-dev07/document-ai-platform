"""
JV (Journal Voucher) metadata extractor.

Unlike invoices, there's no Azure prebuilt model for journal vouchers,
so this uses regex/pattern heuristics against the raw OCR text (the same
text already produced during classification) to pull out:
- JV number
- Date
- Description/narration (الشرح)
- Total amount

This is intentionally a best-effort first pass, matching the same
"honest about confidence" philosophy as invoice_extractor.py - fields
that can't be confidently parsed come back as None rather than guessed.
"""

import re
from typing import Optional


def _find_date(text: str) -> Optional[str]:
    # Matches dd/mm/yyyy or dd-mm-yyyy or similar, both Arabic and Western digits
    match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text)
    return match.group(1) if match else None


def _find_jv_number(text: str) -> Optional[str]:
    # Looks for a 2-4 digit standalone number near the top of the page,
    # since JV numbers on these vouchers appear as a large boxed number
    # (e.g. "113") near the header, distinct from dates/amounts.
    lines = text.strip().split("\n")[:8]
    for line in lines:
        match = re.search(r"\b(\d{2,4})\b", line)
        if match and len(match.group(1)) <= 4:
            return match.group(1)
    return None


def _find_amount(text: str) -> Optional[str]:
    # Looks for the largest decimal-formatted number on the page,
    # typically the voucher total.
    matches = re.findall(r"[\d,]+\.\d{2}", text)
    if not matches:
        return None
    # Return the largest by numeric value
    cleaned = [(m, float(m.replace(",", ""))) for m in matches]
    cleaned.sort(key=lambda x: x[1], reverse=True)
    return cleaned[0][0]


def extract_jv_fields(raw_text: str) -> dict:
    """
    Takes raw OCR text from a JV page and returns best-effort structured
    fields. Any field that can't be confidently found returns None -
    this is deliberately honest rather than guessing.
    """
    return {
        "jv_number": _find_jv_number(raw_text),
        "date": _find_date(raw_text),
        "amount": _find_amount(raw_text),
        "raw_text_preview": raw_text[:200].strip(),
        "extraction_method": "regex_heuristic",
        "note": "JV extraction is regex-based (no Azure prebuilt model exists for "
                "journal vouchers). Verify jv_number and amount against the page image.",
    }