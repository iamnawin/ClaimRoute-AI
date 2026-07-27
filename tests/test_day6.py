"""Day 6 tests: every validator, policy wiring, fusion behavior, and the
integration case Day 5 exposed (merged name spans must FAIL name_format)."""
import json

from PIL import Image

from engine.extract import run_page
from engine.fusion import fuse, span_sanity
from engine.ledger import CostLedger
from engine.schemas import Verdict
from engine.validators import validate_field
from engine.validators.registry import (claim_arithmetic, cpt_dictionary,
                                        currency_format, date_valid,
                                        dob_before_service, icd10_format,
                                        name_format, npi_checksum, zip_format)


def test_npi_checksum():
    assert npi_checksum("1393521954", {})[0] == Verdict.PASS      # factory-valid
    assert npi_checksum("1393521955", {})[0] == Verdict.FAIL
    assert npi_checksum("123", {})[0] == Verdict.FAIL


def test_code_validators():
    assert cpt_dictionary("99213", {})[0] == Verdict.PASS
    assert cpt_dictionary("99999", {})[0] == Verdict.FAIL
    assert icd10_format("E11.9", {})[0] == Verdict.PASS
    assert icd10_format("11.9E", {})[0] == Verdict.FAIL


def test_dates_and_cross_field():
    assert date_valid("02 27 26", {})[0] == Verdict.PASS
    assert date_valid("13 45 26", {})[0] == Verdict.FAIL
    ctx = {"patient_dob": "01 10 1946"}
    assert dob_before_service("02 27 26", ctx)[0] == Verdict.PASS
    assert dob_before_service("02 27 1940", ctx)[0] == Verdict.FAIL


def test_arithmetic():
    ctx = {"total_charge": "1172.50", "line1_charges": "539.50",
           "line2_charges": "116.25", "line3_charges": "516.75"}
    assert claim_arithmetic("1172.50", ctx)[0] == Verdict.PASS
    ctx["line1_charges"] = "500.00"
    assert claim_arithmetic("1172.50", ctx)[0] == Verdict.FAIL


def test_formats():
    assert currency_format("1172.50", {})[0] == Verdict.PASS
    assert currency_format("1,172.50", {})[0] == Verdict.FAIL
    assert zip_format("55456", {})[0] == Verdict.PASS


def test_name_format_catches_merged_spans():
    assert name_format("Parker, Lori", {})[0] == Verdict.PASS
    v, detail = name_format("Parker, Lori Parker, Lori", {})
    assert v == Verdict.FAIL and "commas" in detail


def test_policy_wiring_line_fields():
    stamps = validate_field("line2_rendering_npi", "1393521954", {})
    assert [s.validator for s in stamps] == ["npi_checksum"]
    assert stamps[0].verdict == Verdict.PASS


def test_fusion_penalizes_span_explosion_not_verdicts():
    good = fuse(0.95, 0.8, 1, "99213", ["cpt_format"])
    swept = fuse(0.95, 0.8, 8, "99213 extra junk here", ["cpt_format"])
    assert good > swept
    assert span_sanity(0) == 0.0


def test_spine_now_emits_stamps_and_fused_conf(tmp_path):
    led = CostLedger(tmp_path / "l.jsonl")
    doc = "cms1500_42_0000"
    img = Image.open(f"data/generated/cms1500/clean/images/{doc}.png")
    page = run_page(img, doc, led)
    npi = page.fields["billing_provider_npi"]
    assert any(s.validator == "npi_checksum" and s.verdict == Verdict.PASS
               for s in npi.stamps)
    assert 0.0 < npi.confidence <= 1.0
    out = page.to_json_dict()
    assert out["billing_provider_npi"]["stamps"]
