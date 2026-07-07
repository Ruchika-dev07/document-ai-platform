# Enterprise IDP Platform

Intelligent Document Processing platform for invoices, passports, Emirates IDs,
contracts, purchase orders, and other document types, using OCR + AI extraction.

Architecture and full project scope: see `Enterprise_IDP_Technical_Architecture.pdf`.

## Status

**Working today:**
- Azure Document Intelligence (`prebuilt-invoice` model) integration tested and
  validated against a real bilingual (Arabic/English) UAE tax invoice.
- Confirmed: Azure's prebuilt model correctly maps VAT Registration Number to
  `VendorTaxId` / `CustomerTaxId` — no custom extraction needed there.
- Identified gap: `VendorName` extraction is unreliable on Arabic/RTL invoices
  (44.7% confidence on test document, incorrect value).
- Built a confidence-based fallback (`app/services/extraction/invoice_extractor.py`)
  that uses raw OCR line data when the labeled field's confidence is too low.

**Not yet built:**
- Passport / Emirates ID / contract / PO extractors (same pattern, different fields)
- Validation engine (duplicate detection, VAT math checks)
- SharePoint / ERP integration
- Frontend upload/review UI
- Custom-trained model for Arabic vendor name extraction (longer-term fix)

## Setup

```bash
pip install -r requirements.txt --break-system-packages
```

Set environment variables (don't commit real keys):

```bash
export AZURE_DOCINTEL_ENDPOINT="https://your-resource.cognitiveservices.azure.com/"
export AZURE_DOCINTEL_KEY="your-key-here"
```

## Testing the extractor against a saved sample

```bash
python app/services/extraction/invoice_extractor.py sample-outputs/uae_invoice_analyze_result.json
```

## Project structure

See `Enterprise_IDP_Technical_Architecture.pdf` section 4 for the full intended
structure. Folders are scaffolded; most service files are placeholders (`pass`)
pending build-out beyond the invoice pipeline proof-of-concept.
