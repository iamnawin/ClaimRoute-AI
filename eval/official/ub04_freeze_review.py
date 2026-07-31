"""Cross-platform stable candidate receipts for Tier C freeze review."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path


FREEZE_FILES = (
    "eval/official/ub04_field_map.yaml",
    "engine/layout/templates/official/ub04_cms1450.yaml",
    "engine/layout/official_ub04_registration.py",
    "eval/official/normalization.py",
    "eval/official/ub04_denominator_policy.yaml",
    "engine/validators/dictionaries/icd10.txt",
    "eval/official/icd10_dictionary_version.yaml",
    "eval/official/ocr_retry.py",
    "eval/official/ocr_retry_profiles.yaml",
    "engine/validators/registry.py",
    "configs/field_policy.yaml",
    "engine/governor.py",
    "configs/pipeline.yaml",
    "eval/official/extraction.py",
    "eval/official/evaluator.py",
    "eval/official/splits/tier_c_split_v1.json",
)


def stable_sha256(path: Path) -> str:
    """Hash text after UTF-8 and newline normalization."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return sha256(text.encode("utf-8")).hexdigest()


def candidate_manifest(root: Path = Path(".")) -> dict:
    return {
        "manifest_type": "candidate_only_not_frozen",
        "split_id": "tier_c_official_v1",
        "form_revision": "UB-04 CMS-1450",
        "hash_algorithm": "SHA-256 over UTF-8 with LF line endings",
        "files": [
            {"path": relative, "sha256": stable_sha256(root / relative)}
            for relative in FREEZE_FILES
        ],
    }


def retry_funnel(rows: list[dict]) -> dict:
    """Summarize retry behavior from PHI-safe field booleans."""
    retried = [row for row in rows if row["retry_attempted"]]
    return {
        "fields_eligible_for_retry": sum(row["retry_eligible"] for row in rows),
        "fields_actually_retried": len(retried),
        "primary_wrong_fields_retried": sum(
            not row["primary_correct"] for row in retried
        ),
        "primary_correct_low_confidence_fields_retried": sum(
            row["primary_correct"] and row["primary_confidence_category"] != "high"
            for row in retried
        ),
        "blank_fields_retried": sum(row["blank_field"] for row in retried),
        "retry_candidates_matching_expected": sum(
            row["retry_candidate_correct"] is True for row in retried
        ),
        "retry_candidates_selected_as_final": sum(
            row["retry_selected_as_final"] for row in retried
        ),
        "unresolved_fields": sum(not row["final_correct"] for row in rows),
    }
