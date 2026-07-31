"""Official UB-04 registration contracts use generated monochrome forms only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.governor import apply
from engine.layout.mapper import load_template
from engine.layout.official_ub04_registration import (
    TEMPLATE_PATH, load_official_ub04_template, normalize_official_ub04_page,
    official_ub04_field_region, register_official_ub04,
)
from engine.ocr.base import OcrWord
from engine.schemas import FieldResult, FieldState, PageResult
from eval.official.extraction import (
    _quantity_component_candidates, map_monochrome_fields, retry_official_page,
)
from eval.official.normalization import classify_field
from eval.official.ocr_retry import candidate_values


PROOF_FIELDS = {
    "patient_control_no", "admission_date", "line1_units", "total_charges",
    "principal_dx",
}


def _form(*, edge_artifact: bool = False) -> Image.Image:
    page = np.full((1100, 850), 255, dtype=np.uint8)
    top, span = 50, 1000
    normalized_rules = [
        0, .06, .075, .09, .105, .12, .14, .17, .25, .268,
        .619, .635, .65, .70, .715, .76, .775, .84, .855, .87,
        .89, .91, .93, 1,
    ]
    ys = [round(top + value * span) for value in normalized_rules]
    for y in ys:
        cv2.line(page, (25, y), (825, y), 0, 2)
    for y0, y1 in zip(ys, ys[1:]):
        if y1 - y0 >= 15:
            for x in (25, 210, 510, 825):
                cv2.line(page, (x, y0 + 3), (x, y1 - 3), 0, 2)
    if edge_artifact:
        cv2.line(page, (0, 1094), (849, 1094), 0, 8)
    return Image.fromarray(page)


def test_official_template_is_separate_from_synthetic_ub04_family():
    official = load_official_ub04_template()
    synthetic = load_template("ub04", 3)
    assert TEMPLATE_PATH.name == "ub04_cms1450.yaml"
    assert official["layout_family"] == "official_monochrome_ub04"
    assert official["synthetic_template_family"] is False
    assert set(official["fields"]) == PROOF_FIELDS
    assert set(synthetic["fields"]) != PROOF_FIELDS


def test_registration_metadata_confidence_and_normalized_coordinate_bounds():
    image = _form()
    registration = register_official_ub04(image)
    assert registration is not None
    assert registration.form_type == "ub04" and registration.revision == "CMS-1450"
    assert registration.confidence >= .70
    assert "23-line revenue grid" in registration.anchors
    for name, field in load_official_ub04_template()["fields"].items():
        assert all(0 <= value <= 1 for key in ("x_region", "y_region")
                   for value in field[key])
        x0, y0, x1, y1 = official_ub04_field_region(image, name, registration)
        assert 0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height


def test_cardinal_orientation_is_corrected_and_weak_pages_abstain():
    result = normalize_official_ub04_page(_form().rotate(180))
    assert result is not None and result[1].confidence >= .70
    assert normalize_official_ub04_page(Image.new("L", (850, 1100), 255)) is None


def test_border_artifact_is_rejected_without_changing_registered_extent():
    clean = register_official_ub04(_form())
    artifact = register_official_ub04(_form(edge_artifact=True))
    assert clean is not None and artifact is not None
    assert abs(clean.y1 - artifact.y1) <= 2
    assert "page-edge dark artifact rejected" in artifact.warnings


def test_five_proof_fields_map_by_overlap_with_bounded_padding():
    image = _form()
    empty = map_monochrome_fields([], image, "ub04")
    assert set(empty) == PROOF_FIELDS
    target = empty["line1_units"]["bbox"]
    word = OcrWord("1", [target[0] + 2, target[1] + 2,
                         target[2] - 2, target[3] - 2], .98)
    mapped = map_monochrome_fields([word], image, "ub04")
    assert mapped["line1_units"]["value"] == "1"
    assert all(mapped[name]["value"] == "" for name in PROOF_FIELDS - {"line1_units"})
    template = load_official_ub04_template()["fields"]["line1_units"]
    registration = register_official_ub04(image)
    raw_width = (template["x_region"][1] - template["x_region"][0]) * (
        registration.x1 - registration.x0
    )
    assert round(target[2] - target[0] - raw_width) == sum(
        (template["padding_px"][0], template["padding_px"][2])
    )


def test_proof_fields_route_through_all_five_normalization_families():
    assert {classify_field(name) for name in PROOF_FIELDS} == {
        "text", "date", "quantity", "money", "code",
    }


def test_principal_diagnosis_retry_keeps_the_complete_typed_code():
    words = [OcrWord("A12.3456", [1, 1, 30, 12], .95)]
    values = {candidate.value for candidate in candidate_values("principal_dx", words)}
    assert "A12.3456" in values


def test_money_retry_prefers_validator_compatible_typed_representation():
    candidates = candidate_values("total_charges", [OcrWord("6", [1, 1, 10, 12], .95)])
    assert [candidate.value for candidate in candidates] == ["6.00"]


def test_quantity_component_retry_removes_touching_box_rules(monkeypatch):
    crop = np.full((40, 70), 255, dtype=np.uint8)
    cv2.line(crop, (68, 0), (68, 39), 0, 2)
    cv2.putText(crop, "6", (53, 29), cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 2)

    class FakeEngine:
        def extract(self, image, psm=None):
            assert psm == 13 and image.width < crop.shape[1] * 8
            return [OcrWord("6", [1, 1, 10, 20], .9)]

    monkeypatch.setattr("eval.official.extraction.get_engine", lambda name: FakeEngine())
    candidates = _quantity_component_candidates("line1_units", Image.fromarray(crop), 1)
    assert [candidate.value for candidate in candidates] == ["6"]


def test_ub04_retry_reenters_validation_and_governor(monkeypatch):
    page = PageResult("safe-dev", "p1", "ub04", quality_score=.95)
    field = FieldResult("safe-dev", "p1", "line1_units", None, confidence=0.0)
    field.set_state(FieldState.RETRY)
    page.fields[field.field_name] = field
    page.decisions[field.field_name] = [("RETRY", "fixture")]
    monkeypatch.setattr(
        "eval.official.extraction.official_retry_candidate",
        lambda image, name, **kwargs: {
            "value": "1", "confidence": .99, "n_spans": 1, "latency_ms": 1.0,
            "mode": "isolated-quantity", "source": "crop_tesseract", "attempts_used": 1,
        },
    )
    receipts = retry_official_page(page, _form())
    assert receipts[0]["mode"] == "isolated-quantity"
    assert field.value == "1" and all(stamp.verdict.value != "FAIL" for stamp in field.stamps)
    assert field.attempts[-1].rung == "retry_ocr" and field.state == FieldState.ACCEPT


def test_optional_blank_and_mapping_exclusions_remain_explicit():
    optional = FieldResult("safe", "p1", "line1_hcpcs", None, confidence=0.0)
    assert apply(optional)[0] == FieldState.ACCEPT
    template_fields = set(load_official_ub04_template()["fields"])
    assert "patient_address" not in template_fields
    assert "attending_qualifier" not in template_fields


def test_dynamic_holdout_guard_no_expected_value_registration_and_synthetic_regression():
    split = json.loads(Path("eval/official/splits/tier_c_split_v1.json").read_text())
    forbidden = {row["source_id"] for row in split["holdout"] + split["excluded"]}
    registration_paths = [Path("engine/layout/official_ub04_registration.py"), TEMPLATE_PATH]
    paths = [*registration_paths, Path(__file__)]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not forbidden.intersection(text)
    registration_text = "\n".join(
        path.read_text(encoding="utf-8") for path in registration_paths
    )
    assert "expected_value" not in registration_text
    assert "organiser_value" not in registration_text
    digest = hashlib.sha256(Path(
        "engine/layout/templates/ub04_v3.json"
    ).read_bytes()).hexdigest()
    assert digest == "b6714b96eb6b13a5670b523228366449263236d294e47fb931779bfcfdaca506"
