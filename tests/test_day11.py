"""Day 11 frozen benchmark integrity, accounting, and resumability."""
import json

import pytest

from eval import day11_frozen as frozen


def test_append_once_prevents_duplicate_rows(tmp_path):
    path = tmp_path / "rows.jsonl"
    seen = set()
    record = {"document_id": "d", "tier": "clean", "field_name": "npi"}
    key = ("d", "clean", "npi")
    assert frozen.append_once(path, record, key, seen)
    assert not frozen.append_once(path, record, key, seen)
    assert len(path.read_text().splitlines()) == 1


def test_optional_empty_excluded_but_hallucination_included():
    policy = {"optional": True}
    assert frozen._included(None, policy, None) is False
    assert frozen._included(None, policy, "invented") is True
    assert frozen._included({"value": "I10"}, policy, "I10") is True


def test_percentile_is_nearest_rank():
    assert frozen._percentile([10, 20, 30, 40], 0.50) == 20
    assert frozen._percentile([10, 20, 30, 40], 0.95) == 40


def test_dataset_integrity_matches_frozen_split():
    result = frozen.validate_dataset()
    assert result["calibration_test_overlap"] == 0
    assert result["frozen_test_documents"] == 30
    assert result["frozen_test_pages"] == 90
    assert result["official_data_included"] is False


def test_aggregate_keeps_measured_and_projected_costs_separate():
    rows = [{
        "document_id": "d", "tier": "clean", "field_name": "npi",
        "included_in_accuracy": True, "resolved_correctly": True,
        "criticality": "high", "first_state": "RETRY",
        "pre_escalation_state": "ESCALATE", "final_state": "ACCEPT",
        "processing_path": [{"rung": "retry_ocr"}],
    }]
    pages = [{
        "document_id": "d", "tier": "clean", "full_wall_latency_ms": 1000,
        "measured_local_cost_usd": 0.001, "projected_api_cost_usd": 0.0002,
    }]
    result = frozen.aggregate(rows, pages)
    assert result["field_accuracy"] == 1.0
    assert result["measured_local_cost_per_page_usd"] == 0.001
    assert result["measured_api_spend_per_page_usd"] == 0.0
    assert result["projected_api_cost_per_page_usd"] == 0.0002
    assert result["projected_total_automated_cost_per_page_usd"] == 0.0012


def test_freeze_refuses_dirty_tree(monkeypatch):
    monkeypatch.setattr(frozen, "git", lambda *args: " M configs/pipeline.yaml")
    with pytest.raises(RuntimeError, match="clean working tree"):
        frozen.freeze()


def test_cli_requires_valid_nonnegative_limit():
    args = frozen.build_parser().parse_args(["run", "--limit", "4"])
    assert args.command == "run" and args.limit == 4
