"""Tier C freeze-review contracts; all field values are synthetic."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.layout.official_ub04_registration import load_official_ub04_template
from engine.schemas import Attempt, FieldResult, FieldState, Verdict
from engine.validators.registry import icd10_dictionary, patient_dob_valid
from eval.official.extraction import require_official_field_confirmation
from eval.official.extraction import validate_official_field
from eval.official.ub04_freeze_review import (
    FREEZE_FILES, candidate_manifest, retry_funnel, stable_sha256,
)


POLICY_PATH = Path("eval/official/ub04_denominator_policy.yaml")
VERSION_PATH = Path("eval/official/icd10_dictionary_version.yaml")
MANIFEST_PATH = Path("eval/results/official_ub04_freeze_manifest_candidate.json")
RECEIPT_PATH = Path("eval/results/official_ub04_freeze_review_summary.json")


def test_patient_dob_validator_accepts_supported_complete_formats():
    ctx = {"statement_from": "01012026"}
    for value in ("01012001", "20010101", "01/01/2001", "010101"):
        assert patient_dob_valid(value, ctx)[0] == Verdict.PASS


def test_patient_dob_validator_rejects_partial_adjacent_invalid_and_implausible_dates():
    ctx = {"statement_from": "01012026"}
    for value in ("0101200", "DOB01012001", "01012001 02022002", "02312001",
                  "01012030", "01011800"):
        assert patient_dob_valid(value, ctx)[0] == Verdict.FAIL


def test_official_ub04_dob_requires_independent_retry_before_accept():
    field = FieldResult("safe", "p1", "patient_dob", "01012001", confidence=.99)
    field.attempts = [Attempt("primary_ocr", "tesseract", field.value, .99)]
    result = require_official_field_confirmation("ub04", field, FieldState.ACCEPT)
    assert result and result[0] == FieldState.RETRY and field.state == FieldState.RETRY
    field.attempts.append(Attempt("retry_ocr", "paddle", field.value, .99))
    assert require_official_field_confirmation("ub04", field, FieldState.ACCEPT) is None


def test_strict_dob_validator_is_scoped_to_official_ub04():
    context = {"statement_from": "01012026"}
    assert validate_official_field(
        "ub04", "patient_dob", "DOB01012001", context
    )[0].verdict == Verdict.FAIL
    assert validate_official_field(
        "cms1500", "patient_dob", "DOB01012001", context
    )[0].validator == "date_valid"


def test_retry_funnel_definitions_are_unambiguous():
    rows = [
        {"retry_eligible": True, "retry_attempted": True, "primary_correct": False,
         "primary_confidence_category": "low", "blank_field": False,
         "retry_candidate_correct": True, "retry_selected_as_final": True,
         "final_correct": True},
        {"retry_eligible": True, "retry_attempted": True, "primary_correct": True,
         "primary_confidence_category": "medium", "blank_field": False,
         "retry_candidate_correct": True, "retry_selected_as_final": False,
         "final_correct": True},
    ]
    assert retry_funnel(rows) == {
        "fields_eligible_for_retry": 2, "fields_actually_retried": 2,
        "primary_wrong_fields_retried": 1,
        "primary_correct_low_confidence_fields_retried": 1,
        "blank_fields_retried": 0, "retry_candidates_matching_expected": 2,
        "retry_candidates_selected_as_final": 1, "unresolved_fields": 0,
    }


def test_denominator_policy_is_complete_and_each_field_has_exactly_one_policy():
    artifact = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    fields, allowed = artifact["fields"], set(artifact["meta"]["allowed_policies"])
    template = set(load_official_ub04_template()["fields"])
    assert template <= set(fields)
    assert {"provider_npi", "payer_name", "attending_qualifier", "attending_npi",
            "line1_service_date", "line2_service_date", "line3_service_date"} <= set(fields)
    assert all(row["policy"] in allowed for row in fields.values())
    assert all(isinstance(row["included"], bool) for row in fields.values())


def test_fl3b_fl5_and_unprinted_repeated_rows_remain_excluded():
    fields = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))["fields"]
    assert fields["medical_record_no"]["included"] is False
    assert fields["federal_tax_no"]["included"] is False
    for row in (2, 3):
        for family in ("rev_code", "units", "charges"):
            assert fields[f"line{row}_{family}"]["policy"] == "not_printed_and_excluded"


def test_icd_version_and_dictionary_hash_are_stable_and_unknown_sibling_fails():
    version = yaml.safe_load(VERSION_PATH.read_text(encoding="utf-8"))
    assert version["source_version"] == "FY 2026 ICD-10-CM"
    assert stable_sha256(Path(version["dictionary_path"])) == version["dictionary_stable_sha256"]
    assert icd10_dictionary("F25.8", {})[0] == Verdict.FAIL


def test_stable_hash_ignores_platform_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.txt", tmp_path / "crlf.txt"
    lf.write_bytes(b"a\nb\n")
    crlf.write_bytes(b"a\r\nb\r\n")
    assert stable_sha256(lf) == stable_sha256(crlf)


def test_candidate_manifest_covers_exact_freeze_inputs():
    manifest = candidate_manifest()
    assert [row["path"] for row in manifest["files"]] == list(FREEZE_FILES)
    assert all(len(row["sha256"]) == 64 for row in manifest["files"])
    if MANIFEST_PATH.exists():
        assert json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) == manifest


def test_freeze_receipt_has_no_values_or_holdout_access():
    if not RECEIPT_PATH.exists():
        return
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["summary"]["holdout_access_count"] == 0
    forbidden = {"value", "expected", "ocr_text", "organiser_value", "filename"}
    assert all(not forbidden.intersection(row) for row in receipt["field_rows"])
