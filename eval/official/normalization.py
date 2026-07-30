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


def normalize_value(field_name: str, value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if field_name in DATE_FIELDS:
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            for fmt in ("%Y%m%d", "%m%d%Y"):
                try:
                    return datetime.strptime(digits, fmt).strftime("%Y%m%d")
                except ValueError:
                    pass
        return digits
    if field_name in MONEY_FIELDS:
        try:
            return f"{Decimal(re.sub(r'[^0-9.-]', '', text)):.2f}"
        except InvalidOperation:
            return re.sub(r"[^0-9.-]", "", text)
    if field_name in CODE_FIELDS:
        return re.sub(r"[^A-Z0-9]", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)

