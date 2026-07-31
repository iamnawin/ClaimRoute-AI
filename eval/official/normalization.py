"""Field-aware comparison normalization; it never changes extraction output."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

DATE_FIELDS = {"patient_dob", "admission_date", "statement_from", "statement_to",
               "service_from", "service_to", "service_date"}
MONEY_FIELDS = {"total_charge", "total_charges", "charge", "service_charge"}
CODE_FIELDS = {"diagnosis_1", "diagnosis_2", "diagnosis_3", "diagnosis_4",
               "principal_dx", "procedure_code", "revenue_code", "provider_npi",
               "referring_npi", "attending_npi", "federal_tax_id", "federal_tax_no"}
QUANTITY_FIELDS = {"units"}

# ``claimroute_expected`` renames spec fields to the ClaimRoute schema and builds
# line-item names as f"line{n}_{target}", so the names arriving here are generated,
# not enumerable. Suffix rules classify that generated space; the sets above keep
# classifying the spec names, which still arrive un-aliased on the UB-04 path.
DATE_SUFFIXES = ("_date_from", "_date_to", "_service_date", "_dob")
MONEY_SUFFIXES = ("_charges", "_charge")
QUANTITY_SUFFIXES = ("_units",)


def classify_field(field_name: str) -> str:
    """Return the comparison family for a spec or ClaimRoute field name.

    Kept separate from ``normalize_value`` so the routing is directly testable
    and so an unknown field provably falls through to ``text`` rather than
    landing in a typed branch by accident.
    """
    if field_name in DATE_FIELDS or field_name.endswith(DATE_SUFFIXES):
        return "date"
    if field_name in MONEY_FIELDS or field_name.endswith(MONEY_SUFFIXES):
        return "money"
    if field_name in QUANTITY_FIELDS or field_name.endswith(QUANTITY_SUFFIXES):
        return "quantity"
    if field_name in CODE_FIELDS:
        return "code"
    return "text"


def normalize_value(field_name: str, value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if field_name == "type_of_bill":
        # UB-192 stores the three significant bill-type digits; CMS-1450
        # prints the National Uniform Billing Committee's leading zero.
        digits = re.sub(r"\D", "", text)
        return digits[-3:]
    family = classify_field(field_name)
    if family == "date":
        digits = re.sub(r"\D", "", text)
        if len(digits) == 6:
            try:
                return datetime.strptime(digits, "%m%d%y").strftime("%Y%m%d")
            except ValueError:
                return digits
        if len(digits) == 8:
            for fmt in ("%Y%m%d", "%m%d%Y"):
                try:
                    return datetime.strptime(digits, fmt).strftime("%Y%m%d")
                except ValueError:
                    pass
        return digits
    if family == "money":
        try:
            return f"{Decimal(re.sub(r'[^0-9.-]', '', text)):.2f}"
        except InvalidOperation:
            return re.sub(r"[^0-9.-]", "", text)
    if family == "quantity":
        # The NSF parser scales units to one decimal ("1.0") while the form
        # prints a bare integer ("1"); compare on numeric value, not digits.
        try:
            return f"{Decimal(re.sub(r'[^0-9.-]', '', text)).normalize():f}"
        except InvalidOperation:
            return re.sub(r"[^A-Z0-9]", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)
