"""Value comparison in memory and aggregate-only PHI-safe receipts."""
from __future__ import annotations

from eval.official.normalization import normalize_value
from eval.official.parsers import OfficialRecord


def claimroute_expected(record: OfficialRecord) -> dict[str, object]:
    """Map spec names to the existing ClaimRoute schema without inventing fields."""
    aliases = {
        "provider_name": "billing_provider_name" if record.format_name == "NSF320" else "provider_name",
        "provider_npi": "billing_provider_npi" if record.format_name == "NSF320" else "provider_npi",
        "referring_npi": "referring_provider_npi",
        "diagnosis_1": "diagnosis_code_a", "diagnosis_2": "diagnosis_code_b",
        "diagnosis_3": "diagnosis_code_c", "diagnosis_4": "diagnosis_code_d",
    }
    output = {aliases.get(name, name): value for name, value in record.fields.items()
              if value not in (None, "") and name != "attending_identifier"}
    if record.fields.get("attending_qualifier") == "XX":
        output["attending_npi"] = record.fields.get("attending_identifier", "")
    for index, line in enumerate(record.service_lines[:3], 1):
        line_aliases = ({"service_from": "date_from", "service_to": "date_to",
                         "place_of_service": "place_of_service", "procedure_code": "cpt_code",
                         "diagnosis_pointer": "diagnosis_pointer", "charge": "charges",
                         "units": "units"} if record.format_name == "NSF320" else
                        {"revenue_code": "rev_code", "procedure_code": "hcpcs",
                         "service_date": "service_date", "charge": "charges", "units": "units"})
        for source, target in line_aliases.items():
            if line.get(source) not in (None, ""):
                output[f"line{index}_{target}"] = line[source]
    return output


def compare_fields(expected: dict[str, object], extracted: dict[str, object]) -> list[dict]:
    rows = []
    for name, expected_value in expected.items():
        if expected_value in (None, ""):
            continue
        actual = extracted.get(name)
        rows.append({"field_name": name,
                     "correct": normalize_value(name, expected_value) == normalize_value(name, actual),
                     "present": actual not in (None, "")})
    return rows


def phi_safe_document_row(*, source_id: str, tier: str, page_count: int,
                          linkage: dict, comparisons: list[dict], latency_ms: float,
                          cost_usd: float, **extra) -> dict:
    return {
        "source_id": source_id, "tier": tier, "page_count": page_count,
        "linkage": linkage, "evaluated_fields": len(comparisons),
        "correct_fields": sum(row["correct"] for row in comparisons),
        "present_fields": sum(row["present"] for row in comparisons),
        "field_results": comparisons, "latency_ms": round(latency_ms, 3),
        "local_cost_usd": round(cost_usd, 9), **extra,
    }
