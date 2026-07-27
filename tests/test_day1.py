"""Day 1 tests: NPI validity, schema state guard, ledger accounting, determinism."""
import pytest

from data_factory.generator import generate_claim, make_npi, validate_npi, flatten_ground_truth
from engine.schemas import FieldResult, FieldState
from engine.ledger import CostLedger
import random


def test_generated_npis_pass_checksum():
    rng = random.Random(7)
    for _ in range(200):
        assert validate_npi(make_npi(rng))


def test_corrupted_npi_fails_checksum():
    rng = random.Random(7)
    npi = make_npi(rng)
    bad = npi[:-1] + str((int(npi[-1]) + 1) % 10)
    assert not validate_npi(bad)


def test_claim_arithmetic_consistent():
    claim = generate_claim(123)
    total = sum(round(float(l["charges"]) * 100) for l in claim["service_lines"])
    assert claim["total_charge"] == f"{total // 100}.{total % 100:02d}"


def test_generator_deterministic():
    assert generate_claim(42) == generate_claim(42)
    assert flatten_ground_truth(generate_claim(1)) != flatten_ground_truth(generate_claim(2))


def test_automated_paths_cannot_mint_override():
    fr = FieldResult(doc_id="d", page_id="p1", field_name="billing_provider_npi")
    with pytest.raises(PermissionError):
        fr.set_state(FieldState.ACCEPT_WITH_OVERRIDE)


def test_human_override_requires_identity_and_reason():
    fr = FieldResult(doc_id="d", page_id="p1", field_name="cpt_code")
    with pytest.raises(ValueError):
        fr.human_override(corrected_value="99213", failing_validator="cpt_dictionary",
                          reviewer_id="", reason="")
    audit = fr.human_override(corrected_value="99213", failing_validator="cpt_dictionary",
                              reviewer_id="rev-01", reason="new code, dict outdated")
    assert fr.state == FieldState.ACCEPT_WITH_OVERRIDE
    assert audit["reviewer_id"] == "rev-01" and audit["failing_validator"] == "cpt_dictionary"


def test_ledger_cost_per_page(tmp_path):
    led = CostLedger(tmp_path / "ledger.jsonl")
    led.log(doc_id="d1", page_id="p1", operation="ocr_primary", cost_usd=0.0001)
    led.log(doc_id="d1", page_id="p1", field_name="cpt_code",
            operation="escalation", cost_usd=0.00006)
    s = led.summary()
    assert s["pages"] == 1
    assert abs(s["cost_per_page_usd"] - 0.00016) < 1e-9
