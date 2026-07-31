"""Synthetic contracts for official OCR optimization."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from engine.ocr import get_engine
from engine.ocr.base import OcrWord
from eval.official.normalization import normalize_value
from eval.official.extraction import map_monochrome_fields, retry_official_page
from eval.official.ocr_retry import (
    RetryCandidate,
    candidate_values,
    load_retry_profiles,
    preprocess_crop,
    select_best_candidate,
    should_stop_retry,
)


def test_field_family_retry_profiles_load_with_bounded_attempts():
    profiles = load_retry_profiles()
    required = {"date", "money", "quantity", "identifier", "diagnosis_code",
                "procedure_code", "code", "text"}
    assert required <= set(profiles["field_families"])
    assert all(1 <= row["max_attempts"] <= len(row["attempts"])
               for row in profiles["field_families"].values())


def test_line_suppression_removes_form_rules_but_preserves_decimal_dot():
    array = np.full((40, 120), 255, dtype=np.uint8)
    cv2.line(array, (0, 5), (119, 5), 0, 2)
    cv2.line(array, (8, 0), (8, 39), 0, 2)
    cv2.circle(array, (65, 29), 2, 0, -1)
    result = np.asarray(preprocess_crop(
        Image.fromarray(array),
        {"scale": 1, "threshold": "none", "remove_lines": True,
         "border_trim": 0, "invert": False},
    ))
    assert result[5].mean() > 245
    assert result[:, 8].mean() > 245
    assert result[29, 65] < 100


def test_candidate_generation_preserves_dates_npi_codes_and_quantities():
    date = candidate_values("line1_date_from", [OcrWord("03 15 24", [0, 0, 10, 10], .9)])
    npi = candidate_values(
        "billing_provider_npi",
        [OcrWord("33A 1234567893", [0, 0, 20, 10], .8)],
    )
    code = candidate_values(
        "diagnosis_code_a", [OcrWord("21A M54.5", [0, 0, 20, 10], .8)]
    )
    quantity = candidate_values("line1_units", [OcrWord("1", [0, 0, 5, 10], .9)])
    assert any(normalize_value("line1_date_from", candidate.value) == "20240315"
               for candidate in date)
    assert any(candidate.value == "1234567893" for candidate in npi)
    assert any(candidate.value == "M54.5" for candidate in code)
    assert any(candidate.value == "1" for candidate in quantity)


def test_six_digit_date_normalization_expands_deterministically():
    assert normalize_value("line1_date_from", "03 15 24") == "20240315"
    assert normalize_value("patient_dob", "12/31/99") == "19991231"


def test_candidate_ranking_prefers_fewer_validator_failures_then_confidence():
    candidates = [
        RetryCandidate("21A M54.5", .99, 1, "page", 0),
        RetryCandidate("M54.5", .75, 1, "crop", 1),
    ]
    selected = select_best_candidate("diagnosis_code_a", candidates, {})
    assert selected.candidate.value == "M54.5"


def test_validated_candidate_stops_retry_but_unvalidated_text_does_not():
    valid = select_best_candidate(
        "line1_units", [RetryCandidate("1", .9, 1, "crop", 0)], {}
    )
    plain = select_best_candidate(
        "patient_city", [RetryCandidate("AUSTIN", .9, 1, "crop", 0)], {}
    )
    assert should_stop_retry(valid, .75)
    assert not should_stop_retry(plain, .75)


def test_ocr_engine_registry_reuses_instances():
    assert get_engine("tesseract") is get_engine("tesseract")


def _registered_form() -> Image.Image:
    page = np.full((1100, 850), 255, dtype=np.uint8)
    ys = [120, 180, 240, 300, 360, 420, 480, 540, 600,
          660, 720, 780, 840, 900, 990, 1040]
    for y in ys:
        cv2.line(page, (35, y), (815, y), 0, 2)
    for top, bottom in zip(ys, ys[1:]):
        for x in (35, 300, 510, 815):
            cv2.line(page, (x, top + 5), (x, bottom - 5), 0, 2)
    return Image.fromarray(page)


def test_mapper_reuses_one_registration_for_all_fields(monkeypatch):
    from eval.official import extraction
    real = extraction.register_official_cms1500
    calls = []

    def counted(image):
        calls.append(image)
        return real(image)

    monkeypatch.setattr(extraction, "register_official_cms1500", counted)
    map_monochrome_fields([], _registered_form(), "cms1500")
    assert len(calls) == 1


def test_retry_page_reuses_one_shared_page_ocr(monkeypatch):
    from engine.schemas import FieldResult, FieldState, PageResult
    from eval.official import extraction

    page = PageResult("synthetic", "p1", "cms1500", quality_score=.95)
    for name in ("line1_units", "line2_units"):
        field = FieldResult("synthetic", "p1", name, None, confidence=0.0,
                            bbox=(10, 10, 30, 30))
        field.set_state(FieldState.RETRY)
        page.fields[name] = field
        page.decisions[name] = [("RETRY", "fixture")]

    class FakeEngine:
        def __init__(self):
            self.calls = 0

        def extract(self, image):
            self.calls += 1
            return []

    engine = FakeEngine()
    monkeypatch.setattr(
        extraction, "extract_profile",
        lambda image, profile: engine.extract(image),
    )
    monkeypatch.setattr(
        extraction, "official_retry_candidate",
        lambda image, name, **kwargs: {
            "value": "1", "confidence": .99, "n_spans": 1,
            "latency_ms": 1.0, "mode": "isolated-quantity",
            "source": "crop_paddle", "attempts_used": 1,
        },
    )
    retry_official_page(page, _registered_form())
    assert engine.calls == 1
