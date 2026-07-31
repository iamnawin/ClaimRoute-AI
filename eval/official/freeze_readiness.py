"""Deterministic candidate hashes for later Tier A CMS-1500 freeze review."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path


FREEZE_FILES = (
    "engine/layout/templates/official/cms1500_02_12.yaml",
    "engine/layout/official_cms1500_registration.py",
    "eval/official/extraction.py",
    "eval/official/normalization.py",
    "eval/official/ocr_retry.py",
    "eval/official/ocr_retry_profiles.yaml",
    "eval/official/cms1500_field_map.yaml",
    "configs/field_policy.yaml",
    "configs/pipeline.yaml",
    "configs/prices.yaml",
    "engine/validators/registry.py",
    "engine/governor.py",
    "eval/official/evaluator.py",
    "eval/official/splits/tier_a_split_v1.json",
)


def candidate_manifest(root: Path = Path(".")) -> dict:
    files = []
    for relative in FREEZE_FILES:
        data = (root / relative).read_bytes()
        files.append({"path": relative, "sha256": sha256(data).hexdigest()})
    return {
        "manifest_type": "candidate_only_not_frozen",
        "split_id": "tier_a_official_v1",
        "form_revision": "CMS-1500 (02-12)",
        "hash_algorithm": "SHA-256",
        "files": files,
    }
