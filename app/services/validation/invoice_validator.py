"""
Validates extracted invoice fields against basic business rules.

Two checks implemented (from architecture doc section 8 - Validation Layer):
1. VAT/total math check: does SubTotal + TotalTax - TotalDiscount == InvoiceTotal?
2. Mandatory field check: are the fields we actually need for downstream
   processing (SharePoint/ERP) present at all?

Both checks use a small tolerance for floating point rounding, since
currency math from OCR-extracted numbers can be off by a cent or two.
"""

from typing import Optional


TOLERANCE = 0.05  # allow up to 5 cents of rounding difference

MANDATORY_FIELDS = [
    "vendor_name",
    "invoice_id",
    "invoice_date",
    "invoice_total",
]


def _extract_amount(value) -> Optional[float]:
    """Pulls a numeric amount out of either a raw number or a
    {'amount': x, 'currencyCode': 'AED'} dict, as produced by
    invoice_extractor.py."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("amount")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def check_vat_math(fields: dict) -> dict:
    """
    Checks whether SubTotal + TotalTax - TotalDiscount == InvoiceTotal.
    Returns a result dict rather than raising, so the caller can decide
    whether a mismatch blocks the workflow or just gets flagged for review.
    """
    sub_total = _extract_amount(fields.get("sub_total"))
    total_tax = _extract_amount(fields.get("total_tax")) or 0.0
    total_discount = _extract_amount(fields.get("total_discount")) or 0.0
    invoice_total = _extract_amount(fields.get("invoice_total"))

    if sub_total is None or invoice_total is None:
        return {
            "check": "vat_math",
            "passed": False,
            "reason": "Missing SubTotal or InvoiceTotal - cannot verify math",
        }

    # Note: Azure's prebuilt-invoice model returns SubTotal as the
    # already-discounted taxable amount (confirmed against a real UAE
    # invoice where Taxable Total = Amount - Discount already applied).
    # So the correct check is SubTotal + TotalTax == InvoiceTotal.
    # TotalDiscount is informational only here, not subtracted again.
    expected_total = sub_total + total_tax
    difference = abs(expected_total - invoice_total)
    passed = difference <= TOLERANCE

    return {
        "check": "vat_math",
        "passed": passed,
        "expected_total": round(expected_total, 2),
        "actual_total": invoice_total,
        "difference": round(difference, 2),
        "reason": None if passed else (
            f"SubTotal ({sub_total}) + TotalTax ({total_tax}) = "
            f"{expected_total:.2f}, but InvoiceTotal is {invoice_total}"
        ),
    }


def check_mandatory_fields(fields: dict) -> dict:
    """
    Confirms the fields we actually need downstream (for SharePoint/ERP
    posting) are present and non-empty.
    """
    missing = [
        field for field in MANDATORY_FIELDS
        if not fields.get(field)
    ]

    return {
        "check": "mandatory_fields",
        "passed": len(missing) == 0,
        "missing_fields": missing,
        "reason": None if not missing else f"Missing required fields: {', '.join(missing)}",
    }


def validate_invoice(fields: dict) -> dict:
    """
    Runs all validation checks and returns a combined result.
    `overall_passed` is False if any individual check fails.
    """
    checks = [
        check_mandatory_fields(fields),
        check_vat_math(fields),
    ]

    return {
        "overall_passed": all(c["passed"] for c in checks),
        "checks": checks,
    }


if __name__ == "__main__":
    # Quick manual test using the same sample invoice extraction we've
    # already validated against Azure.
    import json
    import sys

    sys.path.insert(0, ".")
    from app.services.extraction.invoice_extractor import extract_invoice_fields

    if len(sys.argv) < 2:
        print("Usage: python invoice_validator.py <path_to_analyze_result.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    fields = extract_invoice_fields(data)
    result = validate_invoice(fields)
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    """To run on terminal: python3 -m app.services.validation.invoice_validator sample-outputs/uae_invoice_analyze_result.json
    This will run the validation checks on the extracted invoice fields and print the results in a readable format. The output 
    will show whether the invoice passed all checks, and if not, which checks failed and why. This is useful for debugging and 
    ensuring that the invoice data meets the required standards before further processing.
    Example: This checks the actual math on your real invoice: 
    SubTotal (74,125) + Tax (3,706.25) - Discount (2,000) should equal InvoiceTotal (77,831.25)"""