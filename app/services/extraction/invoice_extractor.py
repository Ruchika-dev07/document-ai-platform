"""
Extracts structured invoice fields from Azure Document Intelligence's
prebuilt-invoice output.

Key design decision (from real testing on a bilingual UAE tax invoice):
Azure's prebuilt model reliably maps VAT Registration Number to
VendorTaxId / CustomerTaxId — no custom field needed there.

However, VendorName extraction is unreliable on Arabic/RTL invoices.
On one test invoice, VendorName came back as "/" with 44.7% confidence,
even though the correct Arabic company name was clearly present in the
raw OCR "lines" array (line 2, right after the header graphic).

Fix: if the labeled VendorName field's confidence is below
settings.LOW_CONFIDENCE_THRESHOLD, fall back to a heuristic that scans
the first few lines of page 1 for the longest non-numeric text block
(this is typically the company name/header).
"""

from app.core.config import settings

from typing import Optional

def _fallback_vendor_name_from_lines(analyze_result: dict) -> Optional[str]:
    """
    Heuristic fallback: scan the first 5 lines of page 1 and return the
    longest line that isn't purely numeric/symbols. This is where vendor
    names/headers typically sit on invoices.
    """
    try:
        pages = analyze_result["analyzeResult"]["pages"]
        lines = pages[0].get("lines", [])[:5]
    except (KeyError, IndexError):
        return None

    candidates = [
        line["content"] for line in lines
        if line["content"].strip() and not line["content"].strip().isdigit()
    ]

    if not candidates:
        return None

    # Longest candidate line is usually the company name
    return max(candidates, key=len)


def extract_invoice_fields(analyze_result: dict) -> dict:
    """
    Takes the raw Azure analyzeResult dict and returns a clean, flat
    dictionary of the fields our system actually needs, applying the
    VendorName fallback where confidence is too low.
    """
    documents = analyze_result.get("analyzeResult", {}).get("documents", [])
    if not documents:
        return {}

    fields = documents[0].get("fields", {})

    def get_value(field_name: str, value_key: str):
        field = fields.get(field_name)
        if not field:
            return None, 0.0
        return field.get(value_key) or field.get("content"), field.get("confidence", 0.0)

    vendor_name, vendor_confidence = get_value("VendorName", "valueString")

    if vendor_confidence < settings.LOW_CONFIDENCE_THRESHOLD:
        fallback_name = _fallback_vendor_name_from_lines(analyze_result)
        if fallback_name:
            vendor_name = fallback_name
            vendor_confidence = None  # heuristic, not a model confidence score

    result = {
        "vendor_name": vendor_name,
        "vendor_name_source": "heuristic_fallback" if vendor_confidence is None else "model",
        "vendor_tax_id": get_value("VendorTaxId", "valueString")[0],
        "customer_name": get_value("CustomerName", "valueString")[0],
        "customer_tax_id": get_value("CustomerTaxId", "valueString")[0],
        "invoice_id": get_value("InvoiceId", "valueString")[0],
        "invoice_date": get_value("InvoiceDate", "valueDate")[0],
        "invoice_total": get_value("InvoiceTotal", "valueCurrency")[0],
        "sub_total": get_value("SubTotal", "valueCurrency")[0],
        "total_tax": get_value("TotalTax", "valueCurrency")[0],
        "total_discount": get_value("TotalDiscount", "valueCurrency")[0],
    }

    return result


if __name__ == "__main__":
    # Quick manual test: point this at a saved JSON output from
    # Document Intelligence Studio to sanity check the extraction.
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python invoice_extractor.py <path_to_analyze_result.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    print(json.dumps(extract_invoice_fields(data), indent=2, default=str))

#run this on the terminal: python3 -m app.services.extraction.invoice_extractor sample-outputs/uae_invoice_analyze_result.json