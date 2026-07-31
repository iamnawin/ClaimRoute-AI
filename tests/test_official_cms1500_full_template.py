"""Full official template contracts use generated metadata and images only."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from engine.layout.official_cms1500_registration import load_official_template
from eval.official.freeze_readiness import FREEZE_FILES, candidate_manifest


MAP = yaml.safe_load(Path("eval/official/cms1500_field_map.yaml").read_text())
TEMPLATE = load_official_template()
SCOREABLE = {"mapped_supported", "blank_but_valid"}


def _expanded(row: dict) -> list[str]:
    name = row.get("claimroute_field")
    if not name:
        return []
    if row["repeats"]:
        return [name.replace("{n}", str(index)) for index in range(1, 4)]
    return [name]


def _eligible() -> set[str]:
    return {
        name
        for row in MAP["fields"]
        if row["status"] in SCOREABLE
        and row["schema_supported"]
        and not row["box_ambiguous"]
        and row["official_field"] is not None
        for name in _expanded(row)
    }


def test_all_and_only_eligible_fields_are_authored():
    assert set(TEMPLATE["fields"]) == _eligible()
    assert len(_eligible()) == 41


def test_revision_metadata_and_service_line_cap_are_explicit():
    assert TEMPLATE["form"] == "cms1500"
    assert TEMPLATE["revision"] == "02-12"
    assert TEMPLATE["coord_frame"] == "official ruled-form grid"
    assert TEMPLATE["field_map_id"] == MAP["meta"]["map_id"]
    assert TEMPLATE["service_line_cap"] == MAP["meta"]["service_line_cap"] == 3


def test_only_supported_service_line_indices_are_authored():
    line_names = [name for name in TEMPLATE["fields"] if name.startswith("line")]
    assert {int(re.match(r"line(\d+)_", name).group(1)) for name in line_names} == {1, 2, 3}
    assert all(TEMPLATE["fields"][name]["service_line_index"] ==
               int(re.match(r"line(\d+)_", name).group(1)) for name in line_names)


def test_excluded_categories_never_enter_the_template():
    assert not {"patient_control_no", "patient_account_no", "insurance_plan_name"} & set(TEMPLATE["fields"])
    assert not {"amount_paid", "line1_rendering_npi", "line2_rendering_npi",
                "line3_rendering_npi"} & set(TEMPLATE["fields"])
    assert all("modifier" not in name for name in TEMPLATE["fields"])


def test_regions_have_required_authoring_metadata():
    for name, field in TEMPLATE["fields"].items():
        assert field["cms1500_box"] and field["field_type"]
        assert field["abstain_below_registration_confidence"] is True
        assert len(field["padding_px"]) == 4
        for axis in ("x_region", "y_region"):
            low, high = field[axis]
            assert 0 <= low < high <= 1, (name, axis)


def test_service_line_columns_do_not_materially_overlap():
    suffixes = ["date_from", "date_to", "place_of_service", "cpt_code",
                "diagnosis_pointer", "charges", "units"]
    for index in range(1, 4):
        regions = [TEMPLATE["fields"][f"line{index}_{suffix}"]["x_region"]
                   for suffix in suffixes]
        for left, right in zip(regions, regions[1:]):
            assert left[1] - right[0] <= .01


def test_registration_and_extraction_never_lookup_expected_values():
    text = "\n".join(Path(path).read_text(encoding="utf-8") for path in (
        "engine/layout/official_cms1500_registration.py",
        "eval/official/extraction.py",
        "eval/official/ocr_retry.py",
    ))
    assert "expected_value" not in text and "organiser_value" not in text


def test_holdout_guard_remains_dynamic_for_full_template():
    split = json.loads(Path("eval/official/splits/tier_a_split_v1.json").read_text())
    forbidden = {row["source_id"] for row in split["holdout"] + split["excluded"]}
    text = "\n".join(Path(path).read_text(encoding="utf-8") for path in (
        "engine/layout/templates/official/cms1500_02_12.yaml",
        __file__,
    ))
    assert not forbidden.intersection(text)


def test_candidate_freeze_manifest_is_deterministic_and_nonvolatile():
    first, second = candidate_manifest(), candidate_manifest()
    assert first == second
    assert first["manifest_type"] == "candidate_only_not_frozen"
    assert [row["path"] for row in first["files"]] == list(FREEZE_FILES)
    assert all(len(row["sha256"]) == 64 for row in first["files"])
    assert not any("results/" in path or "diagnostics/" in path for path in FREEZE_FILES)
    committed = json.loads(Path(
        "eval/results/official_cms1500_freeze_manifest_candidate.json"
    ).read_text())
    assert committed == first
