"""Day 7 tests: governor decisions from all four inputs, attempt budgets,
optional-field thrift, retry rung mechanics, and automated-state discipline."""
import pytest
from PIL import Image

from engine.governor import BUDGET, decide, field_policy
from engine.ledger import CostLedger
from engine.ocr.base import OcrWord, normalize_text
from engine.retry_rung import red_dropout, retry_field
from engine.schemas import (AUTOMATED_STATES, Attempt, FieldResult, FieldState,
                            ValidationStamp, Verdict)


def _field(name="billing_provider_npi", value="1393521954", conf=0.95,
           stamps=None, attempts=()):
    fr = FieldResult(doc_id="d", page_id="p1", field_name=name, value=value,
                     confidence=conf)
    fr.stamps = stamps if stamps is not None else [
        ValidationStamp("npi_checksum", Verdict.PASS)]
    fr.attempts = list(attempts)
    return fr


def test_accept_when_validators_clean_and_confident():
    state, reason = decide(_field())
    assert state == FieldState.ACCEPT and "validators clean" in reason


def test_validator_failure_overrides_high_confidence():
    fr = _field(conf=0.99, stamps=[ValidationStamp("npi_checksum", Verdict.FAIL, "Luhn")])
    state, reason = decide(fr)
    assert state == FieldState.RETRY and "validator FAIL" in reason


def test_attempt_budget_exhaustion_walks_the_ladder():
    """RETRY -> ESCALATE -> HUMAN_REVIEW as budgets are consumed."""
    fail = [ValidationStamp("npi_checksum", Verdict.FAIL, "Luhn")]
    fr = _field(conf=0.4, stamps=fail)
    assert decide(fr)[0] == FieldState.RETRY
    fr.attempts.append(Attempt(rung="retry_ocr", engine="tesseract",
                               value="x", confidence=0.4))
    assert decide(fr)[0] == FieldState.ESCALATE
    fr.attempts.append(Attempt(rung="multimodal", engine="nano",
                               value="x", confidence=0.4))
    state, reason = decide(fr)
    assert state == FieldState.HUMAN_REVIEW and "exhausted" in reason
    assert fr.attempts_used("retry_ocr") == BUDGET["retry_ocr"]


def test_optional_empty_field_costs_nothing():
    """The thrift rule: never spend on a box the form allows to be blank."""
    fr = _field(name="diagnosis_code_d", value=None, conf=0.0, stamps=[])
    state, reason = decide(fr)
    assert state == FieldState.ACCEPT and "optional" in reason
    assert field_policy("diagnosis_code_d")["optional"] is True


def test_required_empty_field_does_not_accept():
    fr = _field(name="diagnosis_code_a", value=None, conf=0.0,
                stamps=[ValidationStamp("icd10_format", Verdict.FAIL, "empty value")])
    assert decide(fr)[0] == FieldState.RETRY


def test_low_criticality_middle_band_accepts_with_flag():
    fr = _field(name="patient_address", value="4941 Carrie Pass", conf=0.80,
                stamps=[])
    assert decide(fr)[0] == FieldState.ACCEPT_WITH_FLAG


def test_governor_never_emits_the_human_only_state():
    for conf in (0.0, 0.5, 0.99):
        for stamps in ([], [ValidationStamp("npi_checksum", Verdict.FAIL, "x")]):
            fr = _field(conf=conf, stamps=stamps)
            assert decide(fr)[0] in AUTOMATED_STATES


def test_unicode_normalization_of_ocr_output():
    assert normalize_text("Friedman， Jennifer") == "Friedman, Jennifer"
    assert OcrWord("Smith：John", [0, 0, 1, 1], 0.9).text == "Smith:John"


def test_red_dropout_whitens_form_ink():
    img = Image.new("RGB", (20, 20), (255, 255, 255))
    img.putpixel((5, 5), (192, 80, 70))         # form red
    img.putpixel((7, 7), (25, 25, 30))          # value ink
    out = red_dropout(img)
    assert out.getpixel((5, 5)) == (255, 255, 255)
    assert out.getpixel((7, 7)) == (25, 25, 30)


def test_retry_rung_logs_cost_and_revalidates(tmp_path):
    led = CostLedger(tmp_path / "l.jsonl")
    doc = "cms1500_42_0005"
    img = Image.open(f"data/generated/cms1500/clean/images/{doc}.png")
    fr = _field(name="patient_name", value="WRONG VALUE", conf=0.3,
                stamps=[ValidationStamp("name_format", Verdict.FAIL, "0 commas")])
    fr.bbox = (120, 190, 620, 240)
    rec = retry_field(fr, img, "cms1500", 3, {}, 0.9, led)
    assert rec["retried"] is True
    assert fr.attempts_used("retry_ocr") == 1
    entries = [e for e in led.entries() if e["operation"] == "retry_tesseract"]
    assert entries and entries[0]["cost_usd"] > 0      # local compute, NOT free
    assert entries[0]["field"] == "patient_name"
