"""Official UB-04 crosswalk contracts; fixtures contain synthetic values only."""
from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

from engine.governor import field_policy
from eval.official.evaluator import claimroute_expected
from eval.official.normalization import classify_field
from eval.official.parsers import OfficialRecord


MAP_PATH = Path("eval/official/ub04_field_map.yaml")
SPLIT_PATH = Path("eval/official/splits/tier_c_split_v1.json")
DOC_PATH = Path("docs/evaluation/official_ub04_mapping.md")
REQUIRED = {
    "official_field", "official_record_field", "claimroute_field", "ub04_locator",
    "normalization", "validators", "criticality", "optional", "scored", "supported",
    "geometrically_ambiguous", "status", "known_limitation",
}
FAMILIES = {"text", "date", "money", "quantity", "code"}


def _mapping() -> dict:
    return yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))


def _evaluated_names() -> set[str]:
    fields = {
        "federal_tax_no": "000000000", "provider_name": "MASKED FACILITY",
        "patient_control_no": "MASKED-CONTROL", "patient_name": "EXAMPLE, PATIENT",
        "patient_sex": "U", "patient_dob": "01012001",
        "patient_address": "MASKED ADDRESS", "admission_date": "20260101",
        "statement_from": "20260101", "statement_to": "20260102",
        "medical_record_no": "MASKED-RECORD", "type_of_bill": "111",
        "principal_dx": "A123456", "attending_qualifier": "XX",
        "attending_identifier": "0000000000", "total_charges": "1.00",
    }
    lines = [{"revenue_code": "0001", "procedure_code": "00000",
              "units": "1", "charge": "1.00"} for _ in range(3)]
    return set(claimroute_expected(OfficialRecord(1, "UB192", fields, lines)))


def _expanded_scored_names(rows: list[dict]) -> set[str]:
    names = set()
    for row in rows:
        name = row["claimroute_field"]
        if not row["scored"] or not name:
            continue
        if "{n}" in name:
            names.update(name.format(n=index) for index in range(1, 4))
        else:
            names.add(name)
    return names


def test_all_evaluated_ub192_names_are_represented_once():
    rows = _mapping()["fields"]
    assert _expanded_scored_names(rows) == _evaluated_names()
    assert len([row["official_field"] for row in rows]) == len(
        set(row["official_field"] for row in rows)
    )


def test_required_columns_statuses_and_known_families():
    rows = _mapping()["fields"]
    assert all(REQUIRED <= set(row) for row in rows)
    assert all(row["normalization"] in FAMILIES for row in rows if row["normalization"])
    assert {row["status"] for row in rows} <= {
        "mapped_supported", "parser_only", "policy_only", "absent_from_expected_output",
        "unsupported",
    }
    assert all(row["known_limitation"].strip() for row in rows)


def test_supported_fields_resolve_to_real_policy_and_mechanical_columns():
    config = yaml.safe_load(Path("configs/field_policy.yaml").read_text(encoding="utf-8"))
    known = set(config["fields"]) | set(config.get("ub04_fields", {}))
    line_known = set(config["service_line_template"])
    for row in _mapping()["fields"]:
        name = row["claimroute_field"]
        if not row["supported"]:
            assert row["known_limitation"] != "None."
            continue
        if "{n}" in name:
            assert name.split("}_", 1)[1] in line_known
            concrete = name.format(n=1)
        else:
            assert name in known
            concrete = name
        policy = field_policy(concrete)
        assert row["normalization"] == classify_field(concrete)
        assert row["validators"] == policy["required_validators"]
        assert row["criticality"] == policy["criticality"]
        assert row["optional"] == policy["optional"]


def test_scoreability_and_geometry_are_independent_and_exclusions_are_explained():
    rows = _mapping()["fields"]
    assert any(row["scored"] and row["geometrically_ambiguous"] for row in rows)
    assert all(row["known_limitation"] != "None."
               for row in rows if not row["scored"] or not row["supported"])


def test_proof_fields_are_scored_supported_unambiguous_and_populated_in_both_dev_rows():
    mapping = _mapping()
    by_name = {row["claimroute_field"]: row for row in mapping["fields"]}
    safe_rows = [json.loads(line) for line in Path(
        "eval/official/results/official_sample_rows.jsonl"
    ).read_text(encoding="utf-8").splitlines()]
    dev_ids = set(mapping["meta"]["development_source_ids"])
    dev = [row for row in safe_rows if row["source_id"] in dev_ids]
    assert len(dev) == 2
    for name in mapping["meta"]["proof_fields"]:
        row = by_name.get(name)
        if row is None:
            row = next(item for key, item in by_name.items()
                       if key and "{n}" in key and key.format(n=1) == name)
        assert row["scored"] and row["supported"] and not row["geometrically_ambiguous"]
        assert all(name in {field["field_name"] for field in item["field_results"]}
                   for item in dev)


def test_dynamic_holdout_guard_and_repository_safe_mapping():
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    forbidden = {row["source_id"] for row in split["holdout"] + split["excluded"]}
    text = MAP_PATH.read_text(encoding="utf-8") + DOC_PATH.read_text(encoding="utf-8")
    assert not forbidden.intersection(text)
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)
    assert "expected_value" not in text and "organiser_value" not in text
