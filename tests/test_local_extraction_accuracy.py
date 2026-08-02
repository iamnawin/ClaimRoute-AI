"""Local-first extraction contracts.

These tests protect the property the product story depends on: as much of a
document as possible must be resolved by local processing, correctly, before
anything becomes eligible for a paid multimodal call.

Success is never "OCR returned some text". It is: correct route, correct crop,
usable candidate, validator-approved value, and no unsafe acceptance.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import workspace
from app.intake import inspect_content


def _text_page(lines: list[str], *, size: int = 40) -> bytes:
    page = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except OSError:                                   # pragma: no cover - font box
        font = ImageFont.load_default()
    for index, line in enumerate(lines):
        draw.text((120, 160 + index * size * 2), line, fill="black", font=font)
    stream = io.BytesIO()
    page.save(stream, format="PNG")
    return stream.getvalue()


STATEMENT_LINES = [
    "PATIENT STATEMENT",
    "Patient Name: SYNTHETIC PERSON",
    "Member ID: ZZ9999999",
    "Date of Birth: 03/04/1980",
    "Total Charges: 250.00",
    "Provider NPI: 1234567893",
]


@pytest.fixture(scope="module")
def statement_result() -> dict:
    item = inspect_content("synthetic_statement.png", _text_page(STATEMENT_LINES))
    return workspace.process_item(item)


def test_unstructured_page_is_extracted_instead_of_failing(statement_result):
    """A readable page with labelled values must not be reported as a failure."""
    fields = statement_result["fields"][0]["fields"]

    assert statement_result["document_type"] == "unstructured"
    assert statement_result["processing_status"] != "FAILED_EXTRACTION"
    assert fields
    assert fields["provider_npi"]["value"] == "1234567893"
    assert fields["patient_dob"]["value"] == "03/04/1980"


def test_unstructured_values_do_not_swallow_the_next_printed_label(statement_result):
    """Greedy label patterns used to return 'SYNTHETIC PERSON MEMBER ID'."""
    fields = statement_result["fields"][0]["fields"]

    assert fields["patient_name"]["value"] == "SYNTHETIC PERSON"
    for field in fields.values():
        value = str(field["value"]).upper()
        assert "MEMBER ID" not in value
        assert "DATE OF BIRTH" not in value
        assert not value.endswith("NPI")


def test_unstructured_extraction_is_flagged_and_costs_no_external_call(
        statement_result):
    fields = statement_result["fields"][0]["fields"]

    assert all(field["state"] == "ACCEPT_WITH_FLAG" for field in fields.values())
    assert statement_result["escalation_summary"]["external_provider_calls"] == 0
    assert any("limited" in warning.lower()
               for warning in statement_result["warnings"])


def test_trimming_keeps_a_legitimate_multi_word_value():
    """Trimming must cut at printed labels, not at every capitalised token."""
    from app.workspace import _trim_label_bleed

    assert _trim_label_bleed("MARY ANN VAN DER BERG") == "MARY ANN VAN DER BERG"
    assert _trim_label_bleed("ST LUKE'S REGIONAL MEDICAL CENTER") == \
        "ST LUKE'S REGIONAL MEDICAL CENTER"


def test_trimming_does_not_fire_on_a_label_inside_a_longer_word():
    """'GROUP' is a label; 'GROUPER' is somebody's surname."""
    from app.workspace import _trim_label_bleed

    assert _trim_label_bleed("GROUPER SMITH") == "GROUPER SMITH"
    assert _trim_label_bleed("DOBSON RIVERA") == "DOBSON RIVERA"


def test_a_capture_that_is_only_a_label_yields_no_value():
    """The frozen name pattern can capture the *next* label when the real value
    is missing. A label is not a value, and reporting one is worse than
    reporting nothing."""
    from app.workspace import _trim_label_bleed

    assert _trim_label_bleed("MEMBER ID ZZ9999999") == ""
    assert _trim_label_bleed("DATE OF BIRTH") == ""
    assert _trim_label_bleed("NPI") == ""


def test_dropping_label_only_captures_still_keeps_organisation_names():
    """'GROUP' and 'ADDRESS' are printed labels, but they are also ordinary
    words inside real provider names. A single-word label at the start of a
    capture is not enough to throw the whole value away."""
    from app.workspace import _trim_label_bleed

    assert _trim_label_bleed("GROUP HEALTH COOPERATIVE") == \
        "GROUP HEALTH COOPERATIVE"


def test_blank_and_whitespace_captures_yield_nothing():
    from app.workspace import _trim_label_bleed

    assert _trim_label_bleed("") == ""
    assert _trim_label_bleed("   \n  ") == ""
    assert _trim_label_bleed(None) == ""


def test_two_labelled_fields_on_one_line_do_not_absorb_each_other():
    """The adjacent-field case: one OCR line carrying two printed labels."""
    from eval.official.extraction import unstructured_fields

    from app.workspace import _trim_label_bleed

    line = "PATIENT NAME: MARY ANN SMITH DATE OF BIRTH: 01/02/1990"
    fields = {name: _trim_label_bleed(value)
              for name, value in unstructured_fields(line).items()}

    assert fields["patient_name"] == "MARY ANN SMITH"
    assert fields["patient_dob"] == "01/02/1990"


def _degraded_field(name: str, value, conf: float, stamps=None):
    from engine.schemas import Attempt, FieldResult, FieldState

    field = FieldResult("doc", "p1", name, value, FieldState.RETRY, conf)
    field.stamps = stamps or []
    field.attempts = [Attempt("primary_ocr", "paddle", value, conf)]
    return field


@pytest.fixture(scope="module")
def ugly_ub04_page():
    from pathlib import Path

    from engine.preprocess import preprocess_page

    path = Path("data/generated/ub04/ugly/images/ub04_42_0000.png")
    if not path.exists():
        pytest.skip("generated dataset is not present")
    return preprocess_page(Image.open(path))["processed"]


def test_retry_ladder_records_every_rendition_and_profile_it_tried(
        ugly_ub04_page, tmp_path):
    """Each retry has to be explainable: what was tried, and why one won."""
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field

    field = _degraded_field("line1_charges", None, 0.1)
    record = retry_field(field, ugly_ub04_page, "ub04", 3, {}, 0.35,
                         CostLedger(tmp_path / "ledger.jsonl"))

    assert record["retried"] is True
    assert record["attempts"], "the ladder must report what it tried"
    for attempt in record["attempts"]:
        assert set(attempt) >= {"rendition", "profile", "value", "confidence",
                                "validators_passed"}
    assert record["selected"] in {attempt["rendition"] for attempt in
                                  record["attempts"]} | {"primary"}
    assert "reason" in record


def test_retry_ladder_is_bounded_and_different_from_the_primary_pass(
        ugly_ub04_page, tmp_path):
    """A retry that repeats the primary pass is not a retry, and an unbounded
    ladder is not a cheap rung."""
    from engine.ledger import CostLedger
    from engine.retry_rung import MAX_LADDER_ATTEMPTS, retry_field

    ledger = CostLedger(tmp_path / "ledger.jsonl")
    field = _degraded_field("provider_npi", None, 0.1)
    record = retry_field(field, ugly_ub04_page, "ub04", 3, {}, 0.35, ledger)

    assert 1 <= len(record["attempts"]) <= MAX_LADDER_ATTEMPTS
    renditions = [attempt["rendition"] for attempt in record["attempts"]]
    assert len(set(renditions)) == len(renditions), "no rendition repeats"
    assert all(entry["cost_usd"] > 0 for entry in ledger.entries())


def test_retry_ladder_uses_a_digit_profile_for_numeric_fields(
        ugly_ub04_page, tmp_path):
    from engine.ledger import CostLedger
    from engine.retry_rung import field_profiles

    numeric = [profile.name for profile in field_profiles("line1_charges")]
    dates = [profile.name for profile in field_profiles("statement_from")]
    names = [profile.name for profile in field_profiles("patient_name")]

    assert numeric[0] in {"money", "digits"}
    assert dates[0] in {"date", "digits"}
    assert names[0] == "text"
    assert all(set(profile.whitelist or "") <= set("0123456789.,$-/")
               for profile in field_profiles("line1_charges"))


def test_retry_records_exactly_one_field_attempt_however_many_it_tried(
        ugly_ub04_page, tmp_path):
    """The ladder is one logical rung; the receipt must not inflate attempts."""
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field

    field = _degraded_field("patient_name", None, 0.1)
    retry_field(field, ugly_ub04_page, "ub04", 3, {}, 0.35,
                CostLedger(tmp_path / "ledger.jsonl"))

    assert field.attempts_used("retry_ocr") == 1


def test_retry_never_accepts_a_candidate_that_fails_its_validators(
        ugly_ub04_page, tmp_path):
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field
    from engine.schemas import Verdict

    field = _degraded_field("provider_npi", None, 0.1)
    retry_field(field, ugly_ub04_page, "ub04", 3, {}, 0.35,
                CostLedger(tmp_path / "ledger.jsonl"))

    if field.value:
        assert not any(stamp.verdict == Verdict.FAIL for stamp in field.stamps)


def test_retry_never_invents_a_value_for_an_empty_box(tmp_path):
    """A character whitelist makes the engine try harder to see digits. On a
    blank box that pressure can turn speckle into a number, which is the one
    failure mode worse than leaving the field unresolved."""
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field

    blank = Image.new("RGB", (400, 300), "white")
    field = _degraded_field("line1_units", None, 0.1)
    field.bbox = (40, 40, 360, 90)

    retry_field(field, blank, "cms1500", 3, {}, 0.9,
                CostLedger(tmp_path / "ledger.jsonl"))

    assert not field.value, f"invented {field.value!r} for an empty box"


def test_the_ladder_gives_up_on_a_box_that_two_engines_read_as_empty(tmp_path):
    """Measured on the degraded corpus: where the tight crop and the second
    engine both read nothing, the remaining rungs never recovered a real value
    - they returned noise off the surrounding form ('Dm Oe wrvnes'). Paying for
    those rungs buys candidates the validators have to throw away."""
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field

    blank = Image.new("RGB", (400, 300), "white")
    field = _degraded_field("line1_charges", None, 0.1)
    field.bbox = (40, 40, 360, 90)

    record = retry_field(field, blank, "cms1500", 3, {}, 0.35,
                         CostLedger(tmp_path / "ledger.jsonl"))

    assert len(record["attempts"]) == 2, "kept reading an empty box"
    assert record["reason"] in {"no_candidate", "abandoned_empty"}


def test_low_confidence_noise_cannot_outrank_a_clean_primary_value(tmp_path):
    from engine.ledger import CostLedger
    from engine.retry_rung import retry_field

    blank = Image.new("RGB", (400, 300), "white")
    field = _degraded_field("patient_name", "SYNTHETIC PERSON", 0.62)
    field.bbox = (40, 40, 360, 90)

    retry_field(field, blank, "cms1500", 3, {}, 0.9,
                CostLedger(tmp_path / "ledger.jsonl"))

    assert field.value == "SYNTHETIC PERSON"


def test_a_retry_read_may_fill_a_box_the_primary_pass_missed():
    """A blank primary is not a wall. Refusing every retry read into an empty
    box was measured and rejected: it removed the whole CMS-1500 noisy gain
    (+3.3pp -> +0.0pp), because that is where those recoveries come from."""
    from engine.retry_rung import decide_retry

    recovered = decide_retry(agreement=False, prim_failed=False,
                             candidate="1234567893", cand_failed=False,
                             cand_fused=0.93, primary_confidence=0.12)

    assert recovered.take_candidate is True


def test_agreement_never_preserves_a_primary_value_that_fails_validation():
    """Agreement says two reads saw the same marks. It does not say the value
    is legal. When the primary fails its validators and a retry candidate
    passes, the passing candidate must win - otherwise a punctuation-blind
    match pins the field to an invalid value and it stays unresolved."""
    from engine.retry_rung import decide_retry

    outcome = decide_retry(agreement=True, prim_failed=True,
                           candidate="01/15/2025", cand_failed=False,
                           cand_fused=0.90, primary_confidence=0.50)

    assert outcome.take_candidate is True
    assert outcome.decision == "retry_passes_validators"


def test_agreement_still_confirms_a_primary_value_that_passes():
    from engine.retry_rung import decide_retry

    outcome = decide_retry(agreement=True, prim_failed=False,
                           candidate="01/15/2025", cand_failed=False,
                           cand_fused=0.90, primary_confidence=0.50)

    assert outcome.take_candidate is False
    assert outcome.decision == "agree"


def test_an_empty_candidate_is_no_candidate_before_validators_are_consulted():
    from engine.retry_rung import decide_retry

    outcome = decide_retry(agreement=False, prim_failed=False, candidate="",
                           cand_failed=True, cand_fused=0.0,
                           primary_confidence=0.50, abandoned=True)

    assert outcome.take_candidate is False
    assert outcome.decision == "abandoned_empty"


def test_agreement_on_money_still_respects_the_decimal_point():
    """On a name a comma is noise; on an amount the decimal point is the
    magnitude. A measured failure: primary read '00°0', retry read '0.00', and
    a punctuation-blind comparison called that agreement — then kept the
    garbage primary at confidence 1.0."""
    from engine.retry_rung import values_agree

    assert not values_agree("amount_paid", "00°0", "0.00")
    assert not values_agree("total_charge", "100.00", "10000")
    assert values_agree("total_charge", "$1,250.00", "1250.00")
    assert values_agree("total_charge", " 250.00 ", "250.00")


def test_two_engines_agree_across_punctuation_but_not_across_digits():
    """Cross-engine agreement is evidence about the value, not about the
    separators. '02/23/26' and '022326' are the same date read twice; '022326'
    and '022325' are not."""
    from engine.retry_rung import _norm

    assert _norm("02/23/26") == _norm("022326")
    assert _norm("Hernandez, Shelley") == _norm("HERNANDEZ SHELLEY")
    assert _norm("022326") != _norm("022325")
    assert _norm("1234567893") != _norm("123456789")


def test_page_without_extractable_labels_stays_an_honest_failure():
    """No labels, no values. The product must not invent a result."""
    item = inspect_content("synthetic_routing_slip.png", _text_page([
        "INTERNAL ROUTING SLIP",
        "Reference 00-11-22",
        "No claim form markers are present on this page.",
    ]))

    result = workspace.process_item(item)

    assert result["processing_status"] == "FAILED_EXTRACTION"
    assert result["unresolved_fields"] == 0
    assert result["escalation_summary"]["external_provider_calls"] == 0
