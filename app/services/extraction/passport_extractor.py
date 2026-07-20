"""
Passport metadata extractor.

Passports have a highly standardized Machine Readable Zone (MRZ) - two
44-character lines at the bottom of the photo page, always in a fixed
format. This is the most reliable way to extract passport data, far
more reliable than reading the visual fields above it.

MRZ format (TD3, standard passport):
Line 1: P<COUNTRYCODESURNAME<<GIVENNAMES<<<<<<<<<<<<<<<<<<<<<<<
Line 2: PASSPORTNO<CHECKDIGITNATIONALITYDOB<CHECKSEXEXPIRY<CHECK...

This is a best-effort parser - if the MRZ isn't cleanly readable (poor
scan quality, cropped image), fields come back as None rather than
guessed, matching the same honesty pattern as invoice/JV extraction.
"""

import re
from typing import Optional


def _find_mrz_lines(text: str) -> Optional[list]:
    """Looks for two consecutive lines starting with P< (or similar) and 40+ chars."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i in range(len(lines) - 1):
        if lines[i].upper().startswith("P<") and len(lines[i]) >= 30:
            return [lines[i], lines[i + 1]] if i + 1 < len(lines) else [lines[i]]
    return None


def _parse_mrz(mrz_lines: list) -> dict:
    line1 = mrz_lines[0].replace(" ", "")
    line2 = mrz_lines[1].replace(" ", "") if len(mrz_lines) > 1 else ""

    result = {"passport_number": None, "nationality": None, "surname": None, "given_names": None, "date_of_birth": None, "expiry_date": None}

    # Line 1: P<CCCSURNAME<<GIVEN<NAMES<<<<...
    match = re.match(r"P<([A-Z]{3})([A-Z<]+)", line1)
    if match:
        result["nationality"] = match.group(1)
        name_parts = match.group(2).split("<<")
        result["surname"] = name_parts[0].replace("<", " ").strip() if name_parts else None
        if len(name_parts) > 1:
            result["given_names"] = name_parts[1].replace("<", " ").strip()

    # Line 2: passport number is first 9 characters
    if len(line2) >= 9:
        result["passport_number"] = line2[:9].replace("<", "").strip()

    # DOB (positions 13-19, YYMMDD) and expiry (positions 21-27, YYMMDD) per TD3 spec
    if len(line2) >= 20:
        dob_raw = line2[13:19]
        if dob_raw.isdigit():
            result["date_of_birth"] = f"20{dob_raw[0:2]}-{dob_raw[2:4]}-{dob_raw[4:6]}" if int(dob_raw[0:2]) < 30 else f"19{dob_raw[0:2]}-{dob_raw[2:4]}-{dob_raw[4:6]}"
    if len(line2) >= 27:
        exp_raw = line2[21:27]
        if exp_raw.isdigit():
            result["expiry_date"] = f"20{exp_raw[0:2]}-{exp_raw[2:4]}-{exp_raw[4:6]}"

    return result


def extract_passport_fields(raw_text: str) -> dict:
    """
    Takes raw OCR text from a passport page and returns best-effort
    structured fields, parsed from the MRZ when found.
    """
    mrz_lines = _find_mrz_lines(raw_text)

    if not mrz_lines:
        return {
            "passport_number": None,
            "nationality": None,
            "surname": None,
            "given_names": None,
            "date_of_birth": None,
            "expiry_date": None,
            "extraction_method": "mrz_parse",
            "note": "Could not locate a Machine Readable Zone (MRZ) in the OCR text. "
                    "Verify manually against the page image - scan quality or cropping "
                    "may have cut off the MRZ lines at the bottom of the photo page.",
        }

    parsed = _parse_mrz(mrz_lines)
    parsed["extraction_method"] = "mrz_parse"
    parsed["note"] = "Extracted from the passport's Machine Readable Zone (MRZ). Verify against the photo page."
    return parsed