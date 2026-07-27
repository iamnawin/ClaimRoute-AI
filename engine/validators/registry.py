"""Healthcare validation layer — deterministic, free, explainable.

v1.2: validator verdicts are DECISION SIGNALS for the governor, not fused into
the confidence score. Every validator returns a ValidationStamp; cross-field
validators receive the whole page's values as context.

Independent of data_factory by design (the engine must not import its own test
data generator): NPI Luhn is reimplemented here and covered by tests.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from engine.schemas import ValidationStamp, Verdict

_DICT_DIR = Path(__file__).parent / "dictionaries"


def _load_dict(name: str) -> set:
    return set((_DICT_DIR / f"{name}.txt").read_text().split())


_CPT = _load_dict("cpt")
_ICD10 = _load_dict("icd10")
_REV = _load_dict("revenue_codes")


# ---------- helpers ----------

def _luhn_check_digit(digits: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return (10 - total % 10) % 10


def _parse_date(s: str) -> date | None:
    s = re.sub(r"[^\d]", " ", str(s)).strip()
    parts = s.split()
    fmts = []
    if len(parts) == 3:
        m, d, y = parts
        y = ("20" + y if int(y) <= 26 else "19" + y) if len(y) == 2 else y
        fmts = [f"{m.zfill(2)} {d.zfill(2)} {y}"]
    elif len(parts) == 1 and len(parts[0]) in (6, 8):
        raw = parts[0]
        y = raw[4:]
        y = ("20" + y if int(y) <= 26 else "19" + y) if len(y) == 2 else y
        fmts = [f"{raw[:2]} {raw[2:4]} {y}"]
    for f in fmts:
        try:
            return datetime.strptime(f, "%m %d %Y").date()
        except ValueError:
            continue
    return None


# ---------- validators (name -> fn(value, ctx) -> (verdict, detail)) ----------

def npi_checksum(v, ctx):
    v = re.sub(r"\D", "", str(v))
    if len(v) != 10:
        return Verdict.FAIL, f"NPI length {len(v)}"
    ok = _luhn_check_digit("80840" + v[:9]) == int(v[9])
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "Luhn check failed")


def cpt_format(v, ctx):
    ok = re.fullmatch(r"\d{5}", str(v).strip()) is not None
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "not 5 digits")


def cpt_dictionary(v, ctx):
    ok = str(v).strip() in _CPT
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "unknown CPT")


def icd10_format(v, ctx):
    ok = re.fullmatch(r"[A-TV-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?", str(v).strip().upper())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad ICD-10 shape")


def icd10_dictionary(v, ctx):
    ok = str(v).strip().upper() in _ICD10
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "unknown ICD-10")


def date_valid(v, ctx):
    return (Verdict.PASS, "") if _parse_date(v) else (Verdict.FAIL, "unparseable date")


def dob_before_service(v, ctx):
    d = _parse_date(v)
    if d is None:
        return Verdict.FAIL, "unparseable"
    dob = _parse_date(ctx.get("patient_dob", "")) if "patient_dob" in ctx else None
    if dob and d != dob and d < dob:
        return Verdict.FAIL, "service date before DOB"
    if d > date(2026, 12, 31):
        return Verdict.FAIL, "date in the future"
    return Verdict.PASS, ""


def currency_format(v, ctx):
    ok = re.fullmatch(r"\d{1,7}\.\d{2}", str(v).strip())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "not a currency amount")


def claim_arithmetic(v, ctx):
    total_key = "total_charge" if "total_charge" in ctx else "total_charges"
    try:
        total = round(float(ctx[total_key]) * 100)
        lines = [round(float(val) * 100) for key, val in ctx.items()
                 if re.fullmatch(r"line\d+_charges", key) and val]
    except (KeyError, ValueError, TypeError):
        return Verdict.INAPPLICABLE, "amounts unparseable"
    if not lines:
        return Verdict.INAPPLICABLE, "no line charges"
    ok = sum(lines) == total
    return (Verdict.PASS, "") if ok else (
        Verdict.FAIL, f"lines sum {sum(lines)} != total {total}")


def numeric_format(v, ctx):
    ok = re.fullmatch(r"\d{1,4}", str(v).strip())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "not a small integer")


def zip_format(v, ctx):
    ok = re.fullmatch(r"\d{5}(-\d{4})?", str(v).strip())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad ZIP")


def tax_id_format(v, ctx):
    ok = re.fullmatch(r"\d{2}-?\d{7}", str(v).strip())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad EIN shape")


def id_format(v, ctx):
    ok = re.fullmatch(r"[A-Z0-9]{6,15}", str(v).strip().upper())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad member-ID shape")


def name_format(v, ctx):
    s = str(v).strip()
    if not (2 <= len(s) <= 40):
        return Verdict.FAIL, "implausible length"
    if s.count(",") != 1:
        return Verdict.FAIL, f"{s.count(',')} commas (merged/failed span?)"
    ok = re.fullmatch(r"[A-Za-z .'-]+,\s*[A-Za-z .'-]+", s)
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad Last, First shape")


def revenue_code_format(v, ctx):
    ok = str(v).strip() in _REV or re.fullmatch(r"0\d{3}", str(v).strip())
    return (Verdict.PASS, "") if ok else (Verdict.FAIL, "bad revenue code")


_VALIDATORS = {f.__name__: f for f in [
    npi_checksum, cpt_format, cpt_dictionary, icd10_format, icd10_dictionary,
    date_valid, dob_before_service, currency_format, claim_arithmetic,
    numeric_format, zip_format, tax_id_format, id_format, name_format,
    revenue_code_format]}


# ---------- policy wiring ----------

_POLICY = yaml.safe_load(open("configs/field_policy.yaml"))
_FIELDS = {**_POLICY["fields"], **_POLICY.get("ub04_fields", {})}


def _policy_for(field_name: str) -> dict:
    m = re.fullmatch(r"line\d+_(\w+)", field_name)
    if m:
        return _POLICY["service_line_template"].get(m.group(1), {})
    return _FIELDS.get(field_name, {})


def validate_field(field_name: str, value, ctx: dict) -> list[ValidationStamp]:
    """Run the field's required validators from configs/field_policy.yaml."""
    names = _policy_for(field_name).get("required_validators", [])
    stamps = []
    for n in names:
        fn = _VALIDATORS.get(n)
        if fn is None:
            stamps.append(ValidationStamp(n, Verdict.INAPPLICABLE, "unknown validator"))
            continue
        if value in (None, ""):
            stamps.append(ValidationStamp(n, Verdict.FAIL, "empty value"))
            continue
        verdict, detail = fn(value, ctx)
        stamps.append(ValidationStamp(n, verdict, detail))
    return stamps


def run_validators(values: dict) -> dict:
    """Validate a whole page: {field: [ValidationStamp, ...]}."""
    return {f: validate_field(f, v, values) for f, v in values.items()}
