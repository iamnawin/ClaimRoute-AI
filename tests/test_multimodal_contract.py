"""Request/result contract: strict parsing, grounding, usage, and cost separation.

Synthetic values only. Every "claim value" here is invented for the test; none
comes from the organiser sample, the development split, or the holdout.
No test in this file opens a socket.
"""
import json

import pytest
from PIL import Image

from engine.escalation.contract import (CostBreakdown, CropImage, MultimodalRequest,
                                        UsageMetadata, ground_answer, parse_answer)

# A synthetic NPI with a valid Luhn check digit, invented for these tests.
SYNTHETIC_NPI = "1393521955"


def _crop(w=80, h=30):
    return Image.new("RGB", (w, h), "white")


def _body(**kw):
    payload = {"value": "ACME CLINIC", "visible": True, "confidence": 0.97}
    payload.update(kw)
    return json.dumps(payload)


# ------------------------------------------------------------------ crop input

def test_crop_repr_never_exposes_pixel_bytes():
    crop = CropImage.from_pil(_crop(), source_page_px=(1700, 2200))
    text = repr(crop)
    assert "sha256=" in text and str(crop.png_bytes) not in text
    # The safe dict is what reaches audit records: identifiers and sizes only.
    assert set(crop.safe_dict()) == {"crop_sha256", "crop_px", "crop_bytes",
                                     "region_px", "source_page_px", "page_fraction"}
    assert "png_bytes" not in crop.safe_dict()


def test_page_fraction_uses_source_region_not_upscaled_image():
    # engine/cropper.py upscales small boxes; a 40x20 region rendered at 320x160
    # must still be measured as 40x20 of the page.
    crop = CropImage.from_pil(_crop(320, 160), source_page_px=(1000, 1000),
                              region_px=(40, 20))
    assert crop.page_fraction == pytest.approx(800 / 1_000_000)


def test_page_fraction_is_none_without_provenance():
    assert CropImage.from_pil(_crop()).page_fraction is None


def test_request_id_is_deterministic_for_identical_crop_and_field():
    a = MultimodalRequest("patient_name", CropImage.from_pil(_crop()))
    b = MultimodalRequest("patient_name", CropImage.from_pil(_crop()))
    c = MultimodalRequest("insured_name", CropImage.from_pil(_crop()))
    assert a.request_id == b.request_id
    assert a.request_id != c.request_id


# ------------------------------------------------------------------ parsing

def test_valid_response_parses():
    payload, rejects = parse_answer(_body())
    assert rejects == []
    assert payload["value"] == "ACME CLINIC"


def test_json_code_fence_is_tolerated():
    payload, rejects = parse_answer("```json\n" + _body() + "\n```")
    assert rejects == [] and payload["visible"] is True


def test_invalid_json_is_rejected():
    payload, rejects = parse_answer('{"value": "x", "visible": true,}')
    assert payload is None and "invalid JSON" in rejects[0]


def test_explanatory_prose_is_rejected_not_mined_for_json():
    # A model that explains itself has broken the contract. The embedded object
    # must NOT be fished out — that would reward the wrong behaviour.
    prose = ('I can see this is a provider name box. Here is the result: '
             + _body())
    payload, rejects = parse_answer(prose)
    assert payload is None
    assert "prose or non-JSON body" in rejects[0]


def test_missing_required_key_is_rejected():
    payload, rejects = parse_answer(json.dumps({"value": "x", "visible": True}))
    assert payload is None and "missing required keys" in rejects[0]
    assert "confidence" in rejects[0]


def test_multiple_unrelated_fields_are_rejected():
    body = json.dumps({"value": "x", "visible": True, "confidence": 0.9,
                       "patient_name": "OTHER, BOX", "total_charge": "125.00"})
    payload, rejects = parse_answer(body)
    assert payload is None
    assert "multiple unrelated fields" in rejects[0]


def test_non_object_json_is_rejected():
    payload, rejects = parse_answer('["value"]')
    assert payload is None and "expected a JSON object" in rejects[0]


def test_empty_body_is_rejected():
    payload, rejects = parse_answer("")
    assert payload is None and rejects == ["empty response body"]


# ------------------------------------------------------------------ grounding

def test_grounded_answer_is_accepted():
    payload, _ = parse_answer(_body(value=SYNTHETIC_NPI))
    answer, rejects = ground_answer(payload, "billing_provider_npi")
    assert rejects == []
    assert answer.value == SYNTHETIC_NPI and answer.visible is True


@pytest.mark.parametrize("confidence", [-0.1, 1.1, 42])
def test_confidence_outside_zero_to_one_is_rejected(confidence):
    payload, _ = parse_answer(_body(confidence=confidence))
    answer, rejects = ground_answer(payload, "patient_name")
    assert answer is None and "outside 0-1" in rejects[0]


def test_visible_false_with_a_value_is_rejected():
    payload, _ = parse_answer(_body(value="ACME CLINIC", visible=False))
    answer, rejects = ground_answer(payload, "billing_provider_name")
    assert answer is None
    assert rejects == ["visible=false with a non-null value"]


def test_visible_false_with_null_value_is_a_legitimate_blank():
    payload, _ = parse_answer(_body(value=None, visible=False, confidence=0.0))
    answer, rejects = ground_answer(payload, "diagnosis_code_b")
    assert rejects == [] and answer.value is None and answer.visible is False


def test_empty_string_value_is_normalised_to_none():
    payload, _ = parse_answer(_body(value="", visible=False, confidence=0.1))
    answer, rejects = ground_answer(payload, "diagnosis_code_b")
    assert rejects == [] and answer.value is None


@pytest.mark.parametrize("value,visible,confidence", [
    (123, True, 0.9),            # value must be a string or null
    ("x", "yes", 0.9),           # visible must be a real boolean
    ("x", True, "0.9"),          # confidence must be a number
    ("x", True, True),           # bool is not a confidence, despite subclassing int
])
def test_incompatible_primitive_types_are_rejected(value, visible, confidence):
    payload = {"value": value, "visible": visible, "confidence": confidence}
    answer, rejects = ground_answer(payload, "patient_name")
    assert answer is None and rejects


def test_value_incompatible_with_requested_field_type_is_rejected():
    payload, _ = parse_answer(_body(value="ACME CLINIC"))
    answer, rejects = ground_answer(payload, "billing_provider_npi")
    assert answer is None
    assert "type mismatch" in rejects[0] and "npi" in rejects[0]


def test_rejection_reasons_never_echo_the_extracted_value():
    secret = "9998887776"          # synthetic, fails the NPI checksum shape rule
    payload, _ = parse_answer(_body(value=secret + "123"))
    answer, rejects = ground_answer(payload, "billing_provider_npi")
    assert answer is None
    assert all(secret not in r for r in rejects)


def test_paragraph_length_value_is_rejected():
    payload, _ = parse_answer(_body(value="A" * 200))
    answer, rejects = ground_answer(payload, "patient_name", max_value_chars=120)
    assert answer is None and "too long" in rejects[0]


def test_full_width_punctuation_is_normalised_at_the_boundary():
    # PP-OCR and multilingual model heads emit full-width glyphs; every downstream
    # validator is ASCII-only (repo-wide rule).
    payload, _ = parse_answer(_body(value="SMITH，JOHN"))
    answer, rejects = ground_answer(payload, "patient_name")
    assert rejects == [] and answer.value == "SMITH,JOHN"


def test_answer_audit_dict_reports_shape_not_content():
    payload, _ = parse_answer(_body(value="SMITH, JOHN"))
    answer, _ = ground_answer(payload, "patient_name")
    safe = answer.safe_dict()
    assert safe == {"has_value": True, "value_chars": 11, "visible": True,
                    "confidence": 0.97}
    assert "SMITH" not in json.dumps(safe)


# ------------------------------------------------------------------ usage/cost

def test_unavailable_token_counts_stay_unknown():
    usage = UsageMetadata(input_tokens=430, output_tokens=24)
    as_dict = usage.to_dict()
    assert as_dict["input_tokens"] == 430
    # Never defaulted to zero, and image tokens are never invented. Unknown is
    # carried as None -- `null` in JSON -- rather than as the string "unknown".
    # The intent here is unchanged; the encoding was the defect. A string in a
    # field typed Optional[int] raised ValueError in every reader that trusted
    # the schema and did arithmetic on it, which is what took down the Cost tab.
    assert as_dict["image_tokens"] is None
    assert as_dict["cached_tokens"] is None
    assert as_dict["reasoning_tokens"] is None
    # The guarantee that actually matters: absent is not zero.
    assert as_dict["image_tokens"] != 0
    assert usage.billable_known is True


def test_partial_usage_is_not_billable_known():
    assert UsageMetadata(input_tokens=430).billable_known is False


def test_cost_keeps_measured_and_estimated_apart():
    measured = CostBreakdown(basis="measured_usage", measured_usd=0.000031,
                             price_row="gpt-5-nano")
    assert measured.to_dict()["estimated_usd"] is None

    estimated = CostBreakdown(basis="estimated_usage", estimated_usd=0.000012,
                              price_row="gpt-5-nano",
                              estimate_excludes_image_tokens=True)
    d = estimated.to_dict()
    assert d["measured_usd"] is None
    # An estimate that omits image tokens must announce itself as a lower bound.
    assert d["estimate_is_lower_bound"] is True
