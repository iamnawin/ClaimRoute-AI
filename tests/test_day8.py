"""Day 8 escalation harness: resume, honest costs, and governor re-entry."""
import json

from PIL import Image

from engine.ledger import CostLedger
from engine.schemas import Attempt, FieldResult, FieldState, ValidationStamp, Verdict
from engine.vision.base import VisionResponse
from eval import day8_escalation as harness


def _field() -> FieldResult:
    fr = FieldResult(doc_id="d", page_id="p1", field_name="billing_provider_npi",
                     value="1393521955", confidence=0.2, state=FieldState.ESCALATE,
                     bbox=(10, 10, 80, 40))
    fr.stamps = [ValidationStamp("npi_checksum", Verdict.FAIL, "checksum")]
    fr.attempts = [
        Attempt("primary_ocr", "paddle", "1393521955", 0.2),
        Attempt("retry_ocr", "tesseract", "1393521955", 0.3),
    ]
    return fr


def test_cli_argument_parsing():
    args = harness.build_parser().parse_args(
        ["--tiers", "clean", "ugly", "--limit", "3", "--summarize"])
    assert args.tiers == ["clean", "ugly"]
    assert args.limit == 3 and args.summarize is True


def test_tier_filtering_and_limit():
    targets = list(harness.iter_targets(["a", "b"], ["noisy"], set(),
                                        "offline-oracle", limit=1))
    assert targets == [("a", "noisy")]


def test_completed_target_is_skipped():
    completed = {("a", "clean", "offline-oracle")}
    targets = list(harness.iter_targets(["a", "b"], ["clean"], completed,
                                        "offline-oracle"))
    assert targets == [("b", "clean")]


def test_resumable_output_preserves_rows_and_prevents_duplicates(tmp_path):
    path = tmp_path / "rows.jsonl"
    seen = set()
    row = {"run_id": "r", "document_id": "d", "field_name": "npi"}
    keys = ("run_id", "document_id", "field_name")
    assert harness.append_once(path, row, keys, seen) is True
    original = path.read_text()
    assert harness.append_once(path, row, keys, seen) is False
    assert path.read_text() == original
    assert len(harness.read_jsonl(path)) == 1


def test_oracle_mode_label_and_cost_separation():
    attempt = Attempt("multimodal", "offline-oracle", "x", 0.9,
                      cost_usd=0.000031)
    costs = harness.cost_columns(
        "offline-oracle", {"input_tokens": 430, "output_tokens": 24}, attempt)
    assert harness.provider_details("offline-oracle") == ("offline-oracle", "oracle")
    assert costs["total_api_cost_usd"] == 0.0
    assert costs["projected_cost_usd"] == attempt.cost_usd
    assert costs["input_tokens"] == 430


def test_live_cost_is_measured_not_projected():
    attempt = Attempt("multimodal", "gpt-5-nano", "x", 0.9,
                      cost_usd=0.000031)
    costs = harness.cost_columns(
        "gpt-5-nano", {"input_tokens": 100, "output_tokens": 10}, attempt)
    assert costs["total_api_cost_usd"] == attempt.cost_usd
    assert costs["projected_cost_usd"] == 0.0
    assert costs["input_cost_usd"] > 0 and costs["output_cost_usd"] > 0


def test_summary_aggregation():
    pages = [{
        "document_id": "d", "total_fields": 10, "primary_resolved_fields": 6,
        "retry_routed_fields": 4, "retry_resolved_fields": 2,
        "escalated_fields": 2, "correct_fields": 9, "critical_fields": 4,
        "critical_correct_fields": 3, "human_review_fields": 1,
        "unresolved_fields": 1, "local_cost_usd": 0.001,
        "total_latency_ms": 1000,
    }]
    fields = [
        {"final_decision": "ACCEPT", "resolved_correctly": True,
         "total_api_cost_usd": 0.0, "projected_cost_usd": 0.00003,
         "field_name": "a"},
        {"final_decision": "HUMAN_REVIEW", "resolved_correctly": False,
         "total_api_cost_usd": 0.0, "projected_cost_usd": 0.00003,
         "field_name": "b"},
    ]
    out = harness.aggregate(pages, fields)
    assert out["primary_resolution_rate"] == 0.6
    assert out["retry_resolution_rate"] == 0.5
    assert out["escalation_resolution_rate"] == 0.5
    assert out["field_accuracy"] == 0.9
    assert out["projected_api_cost_per_page_usd"] == 0.00006
    assert out["projected_total_automated_cost_per_page_usd"] == 0.00106
    assert out["failures_by_field_type"] == {"b": 1}


def test_summary_writes_flat_csv_without_nested_failure_map(monkeypatch, tmp_path):
    pages = tmp_path / "pages.jsonl"
    rows = tmp_path / "rows.jsonl"
    split = tmp_path / "split.json"
    summary_json = tmp_path / "summary.json"
    summary_csv = tmp_path / "summary.csv"
    page = {
        "run_id": harness.run_id_for("offline-oracle"), "document_id": "d",
        "tier": "clean", "page": "p1", "model": "offline-oracle",
        "total_fields": 1, "primary_resolved_fields": 0,
        "retry_routed_fields": 1, "retry_resolved_fields": 0,
        "escalated_fields": 1, "correct_fields": 0, "critical_fields": 1,
        "critical_correct_fields": 0, "human_review_fields": 1,
        "unresolved_fields": 1, "local_cost_usd": 0.0,
        "total_latency_ms": 1.0,
    }
    field = {
        "run_id": page["run_id"], "document_id": "d", "tier": "clean",
        "field_name": "provider_npi", "final_decision": "HUMAN_REVIEW",
        "resolved_correctly": False, "total_api_cost_usd": 0.0,
        "projected_cost_usd": 0.00003,
    }
    pages.write_text(json.dumps(page) + "\n")
    rows.write_text(json.dumps(field) + "\n")
    split.write_text(json.dumps({"calibration": ["d"]}))
    monkeypatch.setattr(harness, "PAGES", pages)
    monkeypatch.setattr(harness, "ROWS", rows)
    monkeypatch.setattr(harness, "SPLIT", split)
    monkeypatch.setattr(harness, "SUMMARY_JSON", summary_json)
    monkeypatch.setattr(harness, "SUMMARY_CSV", summary_csv)
    monkeypatch.setattr(harness, "RESULTS", tmp_path)
    report = harness.summarize(["clean"], "offline-oracle")
    assert report["blended"]["failures_by_field_type"] == {"provider_npi": 1}
    assert "failures_by_field_type" not in summary_csv.read_text()


def test_failed_provider_call_routes_critical_field_to_human(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(harness, "escalate_field", fail)
    fr = _field()
    rec, error, _ = harness.execute_escalation(
        fr, Image.new("RGB", (100, 60), "white"), "cms1500", 0, {}, 0.9,
        CostLedger(tmp_path / "ledger.jsonl"), "offline-oracle", "clean")
    assert rec["decision"] == "provider_error"
    assert "provider unavailable" in error
    assert fr.state == FieldState.HUMAN_REVIEW


def test_escalation_reenters_real_validation_and_governor(monkeypatch, tmp_path):
    import engine.escalate as escalation

    class GoodEngine:
        def read_field(self, *args, **kwargs):
            return VisionResponse("1393521954", "1393521954", 0.99,
                                  model="offline-oracle", input_tokens=10,
                                  output_tokens=2, cost_usd=0.00003)

    monkeypatch.setattr(escalation, "CACHE_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(escalation, "_CACHE", {})
    monkeypatch.setattr(escalation, "get_vision_engine", lambda model: GoodEngine())
    fr = _field()
    rec, error, _ = harness.execute_escalation(
        fr, Image.new("RGB", (500, 200), "white"), "cms1500", 0, {}, 0.9,
        CostLedger(tmp_path / "ledger.jsonl"), "offline-oracle", "clean")
    assert error is None
    assert fr.stamps[0].verdict == Verdict.PASS
    assert fr.state == FieldState.ACCEPT
    assert rec["final_state"] == "ACCEPT"


def test_unresolved_critical_field_is_not_silently_accepted(monkeypatch, tmp_path):
    def unresolved(fr, *args, **kwargs):
        fr.attempts.append(Attempt("multimodal", "offline-oracle", None, 0.0))
        return {"decision": "rejected_by_grounding", "rejects": ["unstructured"],
                "cached": False}

    monkeypatch.setattr(harness, "escalate_field", unresolved)
    fr = _field()
    rec, _, _ = harness.execute_escalation(
        fr, Image.new("RGB", (100, 60), "white"), "cms1500", 0, {}, 0.9,
        CostLedger(tmp_path / "ledger.jsonl"), "offline-oracle", "clean")
    assert rec["final_state"] == "HUMAN_REVIEW"
    assert fr.state != FieldState.ACCEPT
