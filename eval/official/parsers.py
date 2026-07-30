"""Spec-derived NSF 320 and UB 192 fixed-width parsers.

Positions are one-based and inclusive, matching the organiser Word specifications.
Unknown records remain in ``raw_records`` but values are never logged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OfficialRecord:
    ordinal: int
    format_name: str
    fields: dict[str, str]
    service_lines: list[dict[str, str]] = field(default_factory=list)
    raw_records: dict[str, list[bytes]] = field(default_factory=dict, repr=False)


def _slice(row: bytes | None, start: int, end: int) -> str:
    return row[start - 1:end].decode("latin-1").strip() if row else ""


def _money(value: str, scale: int = 2) -> str:
    raw = value.strip().replace(",", "")
    if not raw:
        return ""
    sign = -1 if raw.endswith("-") or raw.startswith("-") else 1
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    amount = Decimal(int(digits) * sign).scaleb(-scale)
    return f"{amount:.{scale}f}"


def _name(last: str, first: str, middle: str = "") -> str:
    right = " ".join(part for part in (first, middle) if part)
    return f"{last}, {right}".strip(" ,")


def _lines(data: bytes, width: int) -> list[bytes]:
    rows = data.splitlines()
    bad = [len(row) for row in rows if len(row) != width]
    if bad:
        raise ValueError(f"expected {width}-character records; observed widths {sorted(set(bad))}")
    return rows


def _blocks(rows: list[bytes], anchor: bytes) -> list[list[bytes]]:
    blocks, current = [], []
    for row in rows:
        if row.startswith(anchor):
            if current:
                blocks.append(current)
            current = [row]
        elif current:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def _by_type(block: list[bytes], width: int) -> dict[str, list[bytes]]:
    out: dict[str, list[bytes]] = defaultdict(list)
    for row in block:
        out[row[:width].decode("ascii")].append(row)
    return dict(out)


def parse_nsf_bytes(data: bytes) -> list[OfficialRecord]:
    claims = []
    for ordinal, block in enumerate(_blocks(_lines(data, 320), b"BA0"), 1):
        records = _by_type(block, 3)
        ca = (records.get("CA0") or [None])[0]
        if ca is None:  # provider/file trailer without a claim
            continue
        ba = (records.get("BA0") or [None])[0]
        da = (records.get("DA0") or [None])[0]
        ea = (records.get("EA0") or [None])[0]
        xa = (records.get("XA0") or [None])[0]
        fields = {
            "patient_control_no": _slice(ca, 6, 22),
            "patient_name": _name(_slice(ca, 23, 42), _slice(ca, 43, 54), _slice(ca, 55, 55)),
            "patient_dob": _slice(ca, 59, 66),
            "patient_sex": _slice(ca, 67, 67),
            "patient_address": _slice(ca, 69, 98),
            "patient_city": _slice(ca, 129, 148),
            "patient_state": _slice(ca, 149, 150),
            "patient_zip": _slice(ca, 151, 159),
            "insurance_plan_name": _slice(da, 36, 68),
            "patient_relationship": _slice(da, 155, 156),
            "insured_id": _slice(da, 157, 181),
            "insured_name": _name(_slice(da, 182, 201), _slice(da, 202, 213), _slice(da, 214, 214)),
            "referring_npi": _slice(ea, 140, 149),
            "admission_date": _slice(ea, 150, 157),
            "diagnosis_1": _slice(ea, 174, 180),
            "diagnosis_2": _slice(ea, 181, 187),
            "diagnosis_3": _slice(ea, 188, 194),
            "diagnosis_4": _slice(ea, 195, 201),
            "federal_tax_id": _slice(ba, 32, 40),
            "provider_npi": _slice(ba, 48, 62),
            "provider_name": _slice(ba, 165, 197),
            "patient_account_no": _slice(ea, 6, 22),
            "total_charge": _money(_slice(xa, 78, 84)),
        }
        service_lines = []
        for row in records.get("FA0", []):
            service_lines.append({
                "service_from": _slice(row, 40, 47), "service_to": _slice(row, 48, 55),
                "place_of_service": _slice(row, 56, 57),
                "procedure_code": _slice(row, 60, 64), "modifiers": _slice(row, 65, 70),
                "charge": _money(_slice(row, 71, 77)), "diagnosis_pointer": _slice(row, 78, 81),
                "units": _money(_slice(row, 82, 85), 1),
            })
        claims.append(OfficialRecord(ordinal, "NSF320", fields, service_lines, records))
    return claims


def parse_ub_bytes(data: bytes) -> list[OfficialRecord]:
    claims = []
    for ordinal, block in enumerate(_blocks(_lines(data, 192), b"10"), 1):
        records = _by_type(block, 2)
        r10, r20 = (records.get("10") or [None])[0], (records.get("20") or [None])[0]
        if r20 is None:
            continue
        r40 = (records.get("40") or [None])[0]
        r70 = (records.get("70") or [None])[0]
        r80 = (records.get("80") or [None])[0]
        r90 = (records.get("90") or [None])[0]
        accommodation = Decimal(_money(_slice(r90, 43, 52)) or "0")
        ancillary = Decimal(_money(_slice(r90, 63, 72)) or "0")
        fields = {
            "federal_tax_no": _slice(r10, 8, 17), "provider_name": _slice(r10, 97, 121),
            "patient_control_no": _slice(r20, 5, 24),
            "patient_name": _name(_slice(r20, 25, 44), _slice(r20, 45, 53), _slice(r20, 54, 54)),
            "patient_sex": _slice(r20, 55, 55), "patient_dob": _slice(r20, 56, 63),
            "patient_address": _slice(r20, 67, 122), "admission_date": _slice(r20, 123, 130),
            "statement_from": _slice(r20, 133, 140), "statement_to": _slice(r20, 141, 148),
            "medical_record_no": _slice(r20, 173, 189), "type_of_bill": _slice(r40, 25, 27),
            "principal_dx": _slice(r70, 25, 31),
            "attending_qualifier": _slice(r80, 25, 26),
            "attending_identifier": _slice(r80, 27, 42),
            "total_charges": f"{accommodation + ancillary:.2f}",
        }
        service_lines = []
        for record_type, specs in {
            "50": ((25, 28, None, 38, 41, 42, 51), (67, 70, None, 80, 83, 84, 93),
                   (109, 112, None, 122, 125, 126, 135), (151, 154, None, 164, 167, 168, 177)),
            "60": ((25, 28, (29, 33), 38, 44, 45, 54), (81, 84, (85, 89), 94, 100, 101, 110),
                   (137, 140, (141, 145), 150, 156, 157, 166)),
            "61": ((25, 28, (29, 33), 38, 44, 51, 60), (81, 84, (85, 89), 94, 100, 107, 116),
                   (137, 140, (141, 145), 150, 156, 163, 172)),
        }.items():
            for row in records.get(record_type, []):
                for rev_start, rev_end, hcpcs, units_start, units_end, charge_start, charge_end in specs:
                    revenue = _slice(row, rev_start, rev_end)
                    if revenue:
                        service_lines.append({
                            "revenue_code": revenue,
                            "procedure_code": _slice(row, *hcpcs) if hcpcs else "",
                            "units": _slice(row, units_start, units_end),
                            "charge": _money(_slice(row, charge_start, charge_end)),
                        })
        claims.append(OfficialRecord(ordinal, "UB192", fields, service_lines, records))
    return claims
