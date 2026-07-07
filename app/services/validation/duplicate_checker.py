"""
Duplicate invoice detection.

Checks whether an invoice (identified by VendorTaxId + InvoiceId combo,
since invoice numbers alone can repeat across different vendors) has
already been processed.

For now this uses a simple local JSON file as a lightweight "seen
invoices" store, since there's no database wired up yet. This should be
swapped for a real DB table (see architecture doc section 13 - Database)
once app/database/ is built out.
"""

import json
import os


SEEN_INVOICES_FILE = "app/services/validation/_seen_invoices.json"


def _load_seen_invoices() -> dict:
    if not os.path.exists(SEEN_INVOICES_FILE):
        return {}
    with open(SEEN_INVOICES_FILE, "r") as f:
        return json.load(f)


def _save_seen_invoices(seen: dict) -> None:
    with open(SEEN_INVOICES_FILE, "w") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def _make_key(fields: dict) -> str:
    vendor_tax_id = fields.get("vendor_tax_id") or "UNKNOWN_VENDOR"
    invoice_id = fields.get("invoice_id") or "UNKNOWN_INVOICE_ID"
    return f"{vendor_tax_id}::{invoice_id}"


def check_duplicate(fields: dict, mark_as_seen: bool = True) -> dict:
    """
    Returns whether this invoice (by VendorTaxId + InvoiceId) has been
    seen before. If mark_as_seen=True (default), also records it as seen
    for future checks - set to False if you just want to check without
    committing the record (e.g. during a dry-run).
    """
    seen = _load_seen_invoices()
    key = _make_key(fields)

    is_duplicate = key in seen

    result = {
        "check": "duplicate_detection",
        "passed": not is_duplicate,
        "key": key,
        "reason": None if not is_duplicate else (
            f"Invoice {fields.get('invoice_id')} from vendor "
            f"{fields.get('vendor_tax_id')} was already processed "
            f"on {seen.get(key, {}).get('first_seen', 'unknown date')}"
        ),
    }

    if not is_duplicate and mark_as_seen:
        import datetime
        seen[key] = {
            "vendor_name": fields.get("vendor_name"),
            "invoice_total": fields.get("invoice_total"),
            "first_seen": datetime.datetime.utcnow().isoformat(),
        }
        _save_seen_invoices(seen)

    return result


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from app.services.extraction.invoice_extractor import extract_invoice_fields

    if len(sys.argv) < 2:
        print("Usage: python duplicate_checker.py <path_to_analyze_result.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    fields = extract_invoice_fields(data)
    result = check_duplicate(fields)
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    print("\nRun this same command again to see it correctly flag as a duplicate.")

    #To run on terminal initally: python3 -m app.services.validation.duplicate_checker sample-outputs/uae_invoice_analyze_result.json
    """The above command will check for duplicates and mark the invoice as seen.
    Running the same command again will show that it is a duplicate. These are steps below:
    1. Run the command: python3 -m app.services.validation.duplicate_checker sample-outputs/uae_invoice_analyze_result.json
    2. Run the command again: python3 -m app.services.validation.duplicate_checker sample-outputs/uae_invoice_analyze_result.json
    3. The second run will show that the invoice is a duplicate and will provide the date it was first seen.
    4. To reset the seen invoices, delete the file app/services/validation/_seen_invoices.json and run the command again to start fresh.
    """