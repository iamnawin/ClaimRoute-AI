"""Synthetic contracts for the local CMS-1500 retry batching path."""
from __future__ import annotations

from PIL import Image

from app import local_retry
from engine.ocr.base import OcrWord
from engine.schemas import Attempt, FieldResult, FieldState, PageResult
from eval.official.ocr_retry import RetryCandidate


def _page(field_name="patient_dob"):
    page = PageResult("synthetic", "p1", "cms1500", quality_score=.95)
    field = FieldResult(
        "synthetic", "p1", field_name, None, confidence=0.0,
        bbox=(10, 10, 110, 50),
    )
    field.attempts = [Attempt("primary_ocr", "stub", None, 0.0)]
    field.set_state(FieldState.RETRY)
    page.fields[field_name] = field
    page.decisions[field_name] = [("RETRY", "fixture")]
    return page


def test_governor_accepted_atlas_candidate_early_exits_without_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(local_retry, "_atlas_candidates", lambda specs, engine: ({
        "line1_date_from": [RetryCandidate("01012000", .99, 1, "atlas", 1)]
    }, {"invocation_id": "atlas", "engine": "paddle", "latency_ms": 1.0,
        "process_startups": 0, "unique_crops": 1, "deduplicated_crops": 0,
        "started_ms": 0.0, "ended_ms": 1.0}))
    monkeypatch.setattr(
        local_retry, "official_retry_candidate",
        lambda *args, **kwargs: calls.append(args) or None,
    )

    receipts = local_retry.retry_cms1500_page(
        _page("line1_date_from"), Image.new("RGB", (140, 80), "white"), engine=object())

    assert calls == []
    assert len(receipts) == 1
    assert receipts[0]["candidate_selected"] is True


def test_narrow_service_line_quantity_keeps_targeted_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(local_retry, "_atlas_candidates", lambda specs, engine: ({
        "line1_units": [RetryCandidate("1", .99, 1, "atlas", 1)]
    }, {"invocation_id": "atlas", "engine": "paddle", "latency_ms": 1.0,
        "process_startups": 0, "unique_crops": 1, "deduplicated_crops": 0,
        "started_ms": 0.0, "ended_ms": 1.0}))

    def fallback(*args, **kwargs):
        calls.append(kwargs["form"])
        return {"value": "1", "confidence": .99, "n_spans": 1,
                "source": "crop_paddle", "latency_ms": 2.0}

    monkeypatch.setattr(local_retry, "official_retry_candidate", fallback)
    local_retry.retry_cms1500_page(
        _page("line1_units"), Image.new("RGB", (140, 80), "black"), engine=object())

    assert calls == ["cms1500"]


def test_invalid_date_uses_one_bounded_targeted_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(local_retry, "_atlas_candidates", lambda specs, engine: ({
        "patient_dob": [RetryCandidate("invalid", .99, 1, "atlas", 1)]
    }, {"invocation_id": "atlas", "engine": "paddle", "latency_ms": 1.0,
        "process_startups": 0, "unique_crops": 1, "deduplicated_crops": 0,
        "started_ms": 0.0, "ended_ms": 1.0}))

    def fallback(*args, **kwargs):
        calls.append(kwargs["form"])
        return {"value": "01012000", "confidence": .99, "n_spans": 1,
                "source": "crop_paddle", "latency_ms": 2.0}

    monkeypatch.setattr(local_retry, "official_retry_candidate", fallback)
    receipts = local_retry.retry_cms1500_page(
        _page(), Image.new("RGB", (140, 80), "black"), engine=object())

    assert calls == ["cms1500"]
    assert len(receipts[0]["invocations"]) == 2
    assert {row["candidate_outcome"] for row in receipts[0]["invocations"]} <= {
        "SELECTED", "REJECTED", "NO_CANDIDATE",
    }


def test_inactive_field_never_reaches_retry_engine():
    page = _page("line2_units")
    page.fields["line2_units"].set_state(FieldState.ACCEPT)

    class FailEngine:
        def extract(self, image):
            raise AssertionError("inactive crop reached OCR")

    assert local_retry.retry_cms1500_page(
        page, Image.new("RGB", (140, 80), "white"), engine=FailEngine()) == []


def test_identical_crop_profile_is_packed_once_and_order_is_stable():
    crop = Image.new("L", (20, 10), "white")
    profile = {"engine": "paddle", "scale": 1}
    specs = [
        local_retry.RetrySpec(name, "text", crop, crop, profile, False, 0.0)
        for name in ("patient_name", "insured_name")
    ]

    _, placements, keys = local_retry._pack_unique(specs)

    assert list(keys) == ["patient_name", "insured_name"]
    assert len(placements) == 1
    assert keys["patient_name"] == keys["insured_name"]


def test_field_family_profiles_remain_bounded_and_deterministic():
    page = _page("patient_dob")
    second = FieldResult(
        "synthetic", "p1", "line1_units", None, confidence=0.0,
        bbox=(115, 10, 135, 50),
    )
    second.attempts = [Attempt("primary_ocr", "stub", None, 0.0)]
    second.set_state(FieldState.RETRY)
    page.fields["line1_units"] = second
    page.decisions["line1_units"] = [("RETRY", "fixture")]

    specs = local_retry._retry_specs(page, Image.new("RGB", (150, 80), "white"))

    assert [spec.field_name for spec in specs] == ["patient_dob", "line1_units"]
    assert [spec.family for spec in specs] == ["date", "quantity"]
    assert all(spec.profile["engine"] == "paddle" for spec in specs)
