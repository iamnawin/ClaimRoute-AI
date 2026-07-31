"""Five-field official mapping contracts use generated fixtures only."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.layout.official_cms1500_registration import load_official_template
from engine.layout.official_cms1500_registration import official_mark_regions
from engine.ocr.base import OcrWord
from eval.official.extraction import (
    _npi_check_digit, _typed_retry_value, map_monochrome_fields,
    official_retry_mode, retry_official_page,
)
from engine.schemas import FieldResult, FieldState, PageResult


def _form() -> Image.Image:
    page = np.full((1100, 850), 255, dtype=np.uint8)
    ys = [120, 180, 240, 300, 360, 420, 480, 540, 600,
          660, 720, 780, 840, 900, 990, 1040]
    for y in ys:
        cv2.line(page, (35, y), (815, y), 0, 2)
    for top, bottom in zip(ys, ys[1:]):
        for x in (35, 300, 510, 815):
            cv2.line(page, (x, top + 5), (x, bottom - 5), 0, 2)
    return Image.fromarray(page)


def test_official_mapper_returns_the_full_evaluated_template():
    mapped = map_monochrome_fields([], _form(), "cms1500")
    assert set(mapped) == set(load_official_template()["fields"])
    assert len(mapped) == 41
    assert all(row["bbox"] is not None for row in mapped.values())


def test_official_mapper_uses_overlap_inside_registered_regions():
    image = _form()
    empty = map_monochrome_fields([], image, "cms1500")
    box = empty["line1_units"]["bbox"]
    word = OcrWord("1", [box[0] + 2, box[1] + 2, box[2] - 2, box[3] - 2], .95)
    mapped = map_monochrome_fields([word], image, "cms1500")
    assert mapped["line1_units"]["value"] == "1"
    assert all(mapped[name]["value"] == "" for name in mapped if name != "line1_units")


def test_checkbox_policy_selects_the_marked_synthetic_option():
    image = _form().convert("L")
    marks = official_mark_regions(image, "patient_sex")
    target = marks["M"]
    array = np.asarray(image).copy()
    x0, y0, x1, y1 = [round(value) for value in target]
    cv2.line(array, (x0 + 2, y0 + 2), (x1 - 2, y1 - 2), 0, 3)
    cv2.line(array, (x1 - 2, y0 + 2), (x0 + 2, y1 - 2), 0, 3)
    mapped = map_monochrome_fields([], Image.fromarray(array), "cms1500")
    assert mapped["patient_sex"]["value"] == "M"


def test_holdout_guard_remains_dynamic_and_no_expected_values_enter_registration():
    split = json.loads(Path("eval/official/splits/tier_a_split_v1.json").read_text())
    forbidden = {row["source_id"] for row in split["holdout"] + split["excluded"]}
    paths = [
        Path("engine/layout/official_cms1500_registration.py"),
        Path("engine/layout/templates/official/cms1500_02_12.yaml"),
        Path(__file__),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not forbidden.intersection(text)
    registration_text = paths[0].read_text(encoding="utf-8")
    assert "expected_value" not in registration_text
    assert "organiser_value" not in registration_text


def test_field_specific_retry_normalization_is_deterministic():
    assert _typed_retry_value("patient_dob", "11: 11 27 1998 M") == "11271998"
    assert _typed_retry_value("line1_charges", "125 100") == "125.00"
    assert _typed_retry_value("line1_charges", "250") == "250.00"
    assert _typed_retry_value("line1_units", "T") == "1"
    assert _typed_retry_value("federal_tax_id", "12-3456789") == "123456789"
    assert _typed_retry_value("line2_date_from", "03/15/2024") == "03152024"
    assert _typed_retry_value("total_charge", "$1,250.00") == "1250.00"
    assert official_retry_mode("line3_cpt_code") == "procedure-code"
    assert official_retry_mode("patient_relationship") == "checkbox-mark-detection"


def test_npi_retry_repairs_only_the_check_digit():
    first_nine = "123456789"
    value = first_nine + _npi_check_digit(first_nine)
    assert len(value) == 10
    from engine.validators import validate_field
    assert not any(stamp.verdict.value == "FAIL"
                   for stamp in validate_field("billing_provider_npi", value, {}))


def test_official_retry_reenters_validation_and_governor(monkeypatch):
    page = PageResult("safe-dev", "p1", "cms1500", quality_score=.95)
    field = FieldResult("safe-dev", "p1", "line1_units", None, confidence=0.0)
    field.set_state(FieldState.RETRY)
    page.fields[field.field_name] = field
    page.decisions[field.field_name] = [("RETRY", "fixture")]
    monkeypatch.setattr(
        "eval.official.extraction.official_retry_candidate",
        lambda image, name: {"value": "1", "confidence": .99,
                             "n_spans": 1, "latency_ms": 1.0,
                             "mode": "isolated-quantity"},
    )
    receipts = retry_official_page(page, _form())
    assert receipts[0]["mode"] == "isolated-quantity"
    assert field.value == "1" and field.attempts[-1].rung == "retry_ocr"
    assert field.attempts[-1].confidence == field.confidence
    assert field.state == FieldState.ACCEPT
