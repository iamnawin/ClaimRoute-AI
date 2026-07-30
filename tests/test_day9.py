"""Day 9 replay calibration: deterministic modes, costs, and policy gates."""
import json

from eval import day9_calibration as calibration


def _mode(local_threshold, model_threshold, criticalities, flags):
    return {
        "local_accept_confidence": local_threshold,
        "multimodal_accept_confidence": model_threshold,
        "paid_escalation_criticalities": criticalities,
        "accept_with_flag_criticalities": flags,
        "retry_before_escalation": True,
        "allow_optional_escalation": False,
    }


def _row(name, criticality, local_confidence, *, cost=0.00003):
    return {
        "document_id": "cms1500_42_0000",
        "tier": "clean",
        "page": "p1",
        "field_name": name,
        "field_criticality": criticality,
        "ground_truth": "RIGHT",
        "primary_candidate": "WRONG",
        "primary_confidence": local_confidence - 0.1,
        "retry_candidate": "RIGHT",
        "retry_confidence": local_confidence,
        "escalation_candidate": "RIGHT",
        "escalation_confidence": 0.94,
        "final_value": "RIGHT",
        "final_decision": "ACCEPT",
        "resolved_correctly": True,
        "validation_results": [{"validator": "shape", "verdict": "PASS"}],
        "grounding_rejections": [],
        "escalation_decision": "escalation_higher_confidence",
        "projected_cost_usd": cost,
        "total_api_cost_usd": 0.0,
    }


def _pages(total_fields=4, correct_fields=4, critical_fields=1):
    return [{
        "document_id": "cms1500_42_0000",
        "tier": "clean",
        "page": "p1",
        "total_fields": total_fields,
        "correct_fields": correct_fields,
        "critical_fields": critical_fields,
        "critical_correct_fields": critical_fields,
        "local_cost_usd": 0.001,
    }]


def test_operating_mode_configuration_loading(tmp_path):
    path = tmp_path / "modes.yaml"
    path.write_text(
        "modes:\n"
        "  economy:\n"
        "    local_accept_confidence: 0.8\n"
        "    multimodal_accept_confidence: 0.93\n"
        "    paid_escalation_criticalities: [high]\n"
        "    accept_with_flag_criticalities: [low, med]\n"
        "    retry_before_escalation: true\n"
        "    allow_optional_escalation: false\n"
    )
    modes = calibration.load_modes(path)
    assert modes["economy"]["paid_escalation_criticalities"] == ["high"]


def test_threshold_sweep_is_reproducible():
    sweep = {
        "local_accept_confidence": [0.88, 0.80],
        "multimodal_accept_confidence": [0.92, 0.88],
        "paid_escalation_criticalities": [["high", "med"], ["high"]],
        "accept_with_flag": [True, False],
    }
    first = calibration.build_sweep(sweep)
    assert first == calibration.build_sweep(sweep)
    assert [point["point_id"] for point in first] == sorted(
        point["point_id"] for point in first)


def test_modes_produce_separate_escalation_rates():
    rows = [
        _row("billing_provider_npi", "high", 0.79),
        _row("insurance_plan_name", "med", 0.83),
        _row("patient_city", "low", 0.90),
    ]
    pages = _pages()
    modes = {
        "economy": _mode(0.80, 0.93, ["high"], ["low", "med"]),
        "balanced": _mode(0.88, 0.90, ["high", "med"], ["low", "med"]),
        "accuracy": _mode(0.95, 0.88, ["high", "med", "low"], []),
    }
    metrics = {name: calibration.simulate(rows, pages, mode)
               for name, mode in modes.items()}
    assert (metrics["economy"]["escalated_fields"] <
            metrics["balanced"]["escalated_fields"] <
            metrics["accuracy"]["escalated_fields"])


def test_projected_cost_stays_separate_from_measured_cost():
    result = calibration.simulate(
        [_row("billing_provider_npi", "high", 0.70)], _pages(total_fields=2),
        _mode(0.80, 0.90, ["high"], []))
    assert result["measured_api_cost_per_page_usd"] == 0.0
    assert result["projected_api_cost_per_page_usd"] == 0.00003
    assert result["projected_total_automated_cost_per_page_usd"] == 0.00103


def test_economy_escalates_only_critical_fields():
    rows = [
        _row("billing_provider_npi", "high", 0.70),
        _row("insurance_plan_name", "med", 0.70),
    ]
    result = calibration.simulate(
        rows, _pages(total_fields=3),
        _mode(0.80, 0.90, ["high"], ["med"]))
    assert result["escalated_fields"] == 1
    assert result["escalations_by_criticality"] == {"high": 1}


def test_optional_fields_are_never_escalated():
    optional = _row("diagnosis_code_b", "high", 0.10)
    result = calibration.simulate(
        [optional], _pages(total_fields=2),
        _mode(0.95, 0.88, ["high", "med", "low"], []))
    assert result["escalated_fields"] == 0
    assert result["optional_escalations"] == 0


def test_summary_generation_is_deterministic():
    rows = [_row("billing_provider_npi", "high", 0.70)]
    pages = _pages(total_fields=2)
    modes = {"balanced": _mode(0.88, 0.90, ["high", "med"], ["med"])}
    first = calibration.calibrate(rows, pages, modes)
    second = calibration.calibrate(rows, pages, modes)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
