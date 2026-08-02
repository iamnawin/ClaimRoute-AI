"""Local batch contracts use synthetic images and stub page receipts."""
from __future__ import annotations

import csv
import inspect
import io
import json
import os

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import service, workspace
from app import streamlit_app
from app.intake import FileRole, inspect_content
from engine.schemas import (
    Attempt, FieldResult, FieldState, PageResult, ValidationStamp, Verdict,
)


def _image_bytes(fmt="PNG", frames=1):
    images = [Image.new("RGB", (32, 24), "white") for _ in range(frames)]
    stream = io.BytesIO()
    images[0].save(stream, format=fmt, save_all=frames > 1, append_images=images[1:])
    return stream.getvalue()


def _receipt(doc_id="safe"):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "patient_name", "SYNTHETIC PERSON",
                        FieldState.ACCEPT, 0.95)
    field.attempts = [Attempt("primary_ocr", "stub", field.value, 0.95)]
    page.fields = {"patient_name": field}
    page.decisions = {"patient_name": [("ACCEPT", "test")]}
    return service.build_receipt(page, [], "balanced", 10.0, source_kind="local_workspace")


def _empty_receipt(doc_id="safe", document_type="unstructured"):
    page = PageResult(doc_id, "p1", document_type, quality_score=0.9)
    return service.build_receipt(page, [], "balanced", 10.0,
                                 source_kind="local_workspace")


def _unresolved_receipt(doc_id="safe"):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "patient_dob", None,
                        FieldState.ESCALATE, 0.2)
    field.attempts = [Attempt("primary_ocr", "stub", None, 0.2),
                      Attempt("retry_ocr", "stub", None, 0.2)]
    page.fields = {"patient_dob": field}
    page.decisions = {"patient_dob": [
        ("RETRY", "test"), ("ESCALATE", "retry exhausted")
    ]}
    return service.build_receipt(page, [], "balanced", 10.0,
                                 source_kind="local_workspace")


def _inapplicable_receipt(doc_id="safe"):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "line2_cpt_code", None,
                        FieldState.ACCEPT, 0.0)
    field.stamps = [ValidationStamp(
        "service_line_activation", Verdict.INAPPLICABLE, "inactive row")]
    field.attempts = [Attempt("primary_ocr", "stub", None, 0.0)]
    page.fields = {"line2_cpt_code": field}
    page.decisions = {"line2_cpt_code": [("INAPPLICABLE", "inactive row")]}
    return service.build_receipt(page, [], "balanced", 10.0,
                                 source_kind="local_workspace")


def _human_review_receipt(doc_id="safe", *, attempted=False):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "patient_dob", None,
                        FieldState.HUMAN_REVIEW, 0.2)
    field.attempts = [Attempt("primary_ocr", "stub", None, 0.2)]
    if attempted:
        field.attempts.append(Attempt("multimodal", "offline-oracle", None, 0.2))
        page.escalations = {"patient_dob": {
            "model": "offline-oracle", "escalated": True,
            "decision": "rejected_by_grounding",
        }}
    page.fields = {"patient_dob": field}
    page.decisions = {"patient_dob": [("HUMAN_REVIEW", "test")]}
    return service.build_receipt(page, [], "balanced", 10.0,
                                 source_kind="local_workspace")


def test_local_workspace_source_disables_external_escalation(tmp_path):
    calls = []

    def runner(image, doc_id, ledger, **kwargs):
        calls.append(kwargs)
        page = PageResult(doc_id, "p1", "cms1500")
        return page

    service.process_document(
        Image.new("RGB", (20, 20)), "safe", "balanced",
        source_kind="local_workspace", runner=runner, ledger_dir=tmp_path,
    )
    assert calls == [{"preset_name": "balanced", "run_escalate": False,
                      "escalate_model": None, "tier": "clean"}]


def test_processing_without_ground_truth_uses_unified_contract():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(item, page_processor=lambda *args: _receipt())
    assert result["processing_status"] == "COMPLETED"
    assert result["evaluation"] is None
    assert result["page_count"] == 1
    assert result["source_role"] == FileRole.CLAIM_DOCUMENT.value
    assert result["escalation_summary"]["external_provider_calls"] == 0


def test_empty_extraction_is_failed_with_numeric_unresolved_count():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _empty_receipt())

    assert result["processing_status"] == "FAILED_EXTRACTION"
    assert result["unresolved_fields"] == 0
    assert result["warnings"] == [
        "Document classified as unstructured; the page decoded but no fields "
        "were extracted, so it was not successfully processed."
    ]


def test_failed_extraction_only_batch_reports_completed_with_errors():
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _empty_receipt()))

    assert batch["processing_status"] == "COMPLETED_WITH_ERRORS"
    assert batch["summary"]["success"] == 0
    assert batch["summary"]["partial"] == 0
    assert batch["summary"]["failed_extraction"] == 1
    assert batch["summary"]["unresolved_fields"] == 0


def test_summary_tolerates_legacy_none_unresolved_value():
    result = workspace._failed_result(
        inspect_content("synthetic.png", _image_bytes()), "legacy", status="PARTIAL")
    result["unresolved_fields"] = None

    summary = workspace.summarize_results([result])

    assert summary["unresolved_fields"] == 0
    assert isinstance(summary["unresolved_fields"], int)


def test_unresolved_fields_are_partial_and_explicitly_pending_not_sent():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _unresolved_receipt())

    assert result["processing_status"] == "PARTIAL"
    assert result["unresolved_fields"] == 1
    assert result["escalation_summary"] == {
        "fields_escalated": 0,
        "pending_multimodal": 1,
        "multimodal_attempted": 0,
        "multimodal_failed": 0,
        "pending_human_review": 0,
        "external_provider_calls": 0,
    }
    assert result["warnings"] == [
        "1 field(s) pending escalation; external providers are disabled and no data was sent."
    ]
    assert result["resolution_summary"] == {
        "accepted_without_retry": 0,
        "accepted_after_local_retry": 0,
        "accepted_with_flag": 0,
        "inapplicable": 0,
        "pending_local_retry": 0,
        "pending_multimodal": 1,
        "multimodal_attempted": 0,
        "multimodal_eligible": 1,
        "paid_calls_avoided": 1,
        "pending_human_review": 0,
        "external_provider_calls": 0,
    }

    provider = result["provider_escalations"][0]
    assert provider == {
        "page": 1,
        "field_name": "patient_dob",
        "multimodal_eligible": True,
        "provider_enabled": False,
        "provider_name": "openrouter",
        "configured_model": "openai/gpt-5-nano",
        "credential_available": bool(os.environ.get("OPENROUTER_API_KEY")),
        "external_call_attempted": False,
        "external_call_count": 0,
        "reason_not_attempted": "disabled by policy",
        "final_workflow_state": "PENDING_MULTIMODAL_PROVIDER_DISABLED",
        "no_data_sent": True,
    }


def test_provider_state_distinguishes_disabled_missing_key_and_missing_model():
    base = {
        "enabled": True,
        "active_provider": "openrouter",
        "live_provider": {"enabled": True, "provider": "openrouter"},
        "providers": {"openrouter": {
            "model": "synthetic/model", "api_key_env": "SYNTHETIC_TEST_KEY",
        }},
    }
    disabled = workspace._provider_policy_snapshot(
        {**base, "enabled": False}, env={"SYNTHETIC_TEST_KEY": "not-rendered"})
    missing_key = workspace._provider_policy_snapshot(base, env={})
    no_model = workspace._provider_policy_snapshot({
        **base,
        "providers": {"openrouter": {"api_key_env": "SYNTHETIC_TEST_KEY"}},
    }, env={"SYNTHETIC_TEST_KEY": "not-rendered"})

    assert disabled["reason_not_attempted"] == "disabled by policy"
    assert disabled["final_workflow_state"] == "PENDING_MULTIMODAL_PROVIDER_DISABLED"
    assert missing_key["credential_available"] is False
    assert missing_key["final_workflow_state"] == "PENDING_MULTIMODAL_CREDENTIAL_MISSING"
    assert no_model["configured_model"] == ""
    assert no_model["final_workflow_state"] == "PENDING_MULTIMODAL_MODEL_NOT_CONFIGURED"
    assert all(state["external_call_attempted"] is False
               and state["external_call_count"] == 0
               for state in (disabled, missing_key, no_model))
    assert "not-rendered" not in json.dumps([disabled, missing_key, no_model])


def test_inapplicable_service_line_field_is_not_unresolved():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _inapplicable_receipt())

    assert result["processing_status"] == "COMPLETED"
    assert result["unresolved_fields"] == 0
    assert result["governor_summary"] == {"INAPPLICABLE": 1}
    assert result["resolution_summary"]["inapplicable"] == 1


def test_complete_batch_summary_is_numeric_without_double_counting():
    unresolved = workspace.process_item(
        inspect_content("unresolved.png", _image_bytes()),
        page_processor=lambda *args: _unresolved_receipt(),
    )
    inapplicable = workspace.process_item(
        inspect_content("inapplicable.png", _image_bytes() + b"unique"),
        page_processor=lambda *args: _inapplicable_receipt(),
    )
    failed = workspace.process_item(
        inspect_content("empty.png", _image_bytes() + b"empty"),
        page_processor=lambda *args: _empty_receipt(),
    )
    human = workspace.process_item(
        inspect_content("human.png", _image_bytes() + b"human"),
        page_processor=lambda *args: _human_review_receipt(),
    )
    multimodal_failed = workspace.process_item(
        inspect_content("multimodal.png", _image_bytes() + b"multimodal"),
        page_processor=lambda *args: _human_review_receipt(attempted=True),
    )

    summary = workspace.summarize_results([
        unresolved, inapplicable, failed, human, multimodal_failed])

    required = {
        "files", "pages", "success", "partial", "failed_extraction", "failed",
        "total_fields", "accepted", "accepted_with_flag", "retry_attempted",
        "retry_resolved", "unresolved_fields", "inapplicable", "pending_multimodal",
        "multimodal_attempted", "multimodal_failed", "human_review_required",
        "external_calls", "measured_cost_usd", "projected_cost_usd",
        "throughput_pages_per_minute",
    }
    assert required <= summary.keys()
    assert all(isinstance(summary[key], (int, float)) for key in required)
    assert summary["failed_extraction"] == 1
    assert summary["total_fields"] == 4
    assert summary["retry_attempted"] == 1
    assert summary["retry_resolved"] == 0
    assert summary["unresolved_fields"] == 3
    assert summary["inapplicable"] == 1
    assert summary["pending_multimodal"] == 1
    assert summary["multimodal_attempted"] == 1
    assert summary["multimodal_failed"] == 1
    assert summary["human_review_required"] == 2
    assert summary["external_calls"] == 0
    assert human["provider_escalations"][0]["final_workflow_state"] == (
        "HUMAN_REVIEW_REQUIRED")
    assert multimodal_failed["provider_escalations"][0]["final_workflow_state"] == (
        "MULTIMODAL_FAILED")


def test_missing_optional_summaries_contribute_zero():
    result = workspace._failed_result(
        inspect_content("synthetic.png", _image_bytes()), "legacy", status="PARTIAL")
    result.update({"fields": [{"page": 1, "fields": {}}],
                   "resolution_summary": None, "escalation_summary": None})

    summary = workspace.summarize_results([result])

    assert summary["total_fields"] == 0
    assert summary["retry_attempted"] == 0
    assert summary["retry_resolved"] == 0
    assert summary["pending_multimodal"] == 0
    assert summary["human_review_required"] == 0


def test_multipage_processing_calls_each_page_in_order():
    item = inspect_content("synthetic.003", _image_bytes("TIFF", frames=3))
    calls = []

    def process(page, doc_id, mode):
        calls.append(doc_id)
        return _receipt(doc_id)

    result = workspace.process_item(item, page_processor=process)
    assert calls == [f"{item.safe_source_id}-p{index}" for index in (1, 2, 3)]
    assert result["page_count"] == 3


def test_one_corrupt_document_does_not_abort_batch():
    good = inspect_content("good.png", _image_bytes())
    with pytest.warns(UserWarning, match="Corrupt EXIF data"):
        corrupt = inspect_content("corrupt.001", b"II*\x00not-a-real-tiff")

    def process(item, mode):
        if item.filename.startswith("corrupt"):
            raise RuntimeError("raw value must not escape")
        return workspace.process_item(item, page_processor=lambda *args: _receipt())

    batch = workspace.run_batch([corrupt, good], processor=process)
    statuses = {row["source_file"]: row["processing_status"] for row in batch["documents"]}
    assert statuses == {"corrupt.001": "FAILED", "good.png": "COMPLETED"}
    assert "raw value" not in workspace.export_batch_json(batch)
    assert batch["processing_status"] == "COMPLETED_WITH_ERRORS"


def test_duplicate_hash_is_processed_once():
    content = _image_bytes()
    first = inspect_content("a.png", content)
    second = inspect_content("b.001", content)
    calls = []

    def process(item, mode):
        calls.append(item.filename)
        return workspace.process_item(item, page_processor=lambda *args: _receipt())

    batch = workspace.run_batch([second, first], processor=process)
    assert calls == ["a.png"]
    assert [row["processing_status"] for row in batch["documents"]] == [
        "COMPLETED", "DUPLICATE"
    ]


def test_retry_safe_existing_result_is_reused():
    item = inspect_content("synthetic.png", _image_bytes())
    prior = workspace._failed_result(item, "prior", status="COMPLETED")
    batch = workspace.run_batch(
        [item], processor=lambda *_: (_ for _ in ()).throw(AssertionError("called")),
        existing_results={item.safe_source_id: prior},
    )
    assert batch["documents"] == [prior]


def test_stop_callback_marks_unstarted_documents_cancelled():
    items = [inspect_content(f"{name}.png", _image_bytes("PNG") + name.encode())
             for name in ("a", "b")]
    batch = workspace.run_batch(items, stop_requested=lambda: True)
    assert {row["processing_status"] for row in batch["documents"]} == {"CANCELLED"}


def test_json_and_csv_exports_exclude_private_and_absolute_paths(tmp_path):
    item = inspect_content("synthetic.png", _image_bytes(), relative_path=str(tmp_path / "x"))
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    json_text = workspace.export_batch_json(batch)
    csv_text = workspace.export_batch_csv(batch)
    assert str(tmp_path) not in json_text + csv_text
    assert "_linkage_text" not in json_text
    assert json.loads(json_text)["summary"]["success"] == 1
    assert list(csv.DictReader(io.StringIO(csv_text)))[0]["processing_status"] == "COMPLETED"
    document = batch["documents"][0]
    assert json.loads(workspace.export_document_json(document))["source_file"] == "synthetic.png"
    assert list(csv.DictReader(io.StringIO(workspace.export_document_csv(document))))[0][
        "field_name"] == "patient_name"


def test_evaluation_with_synthetic_expected_output_is_post_extraction_only():
    document = inspect_content("synthetic.png", _image_bytes(), group_key="dataset")
    expected = inspect_content("synthetic.json", json.dumps({
        "doc_id": "synthetic",
        "fields": {"patient_name": {"value": "SYNTHETIC PERSON"}},
    }).encode(), group_key="dataset")
    process_only = workspace.run_batch(
        [document], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    evaluated = workspace.run_batch(
        [expected, document], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()), evaluate=True)

    evaluated_document = next(
        row for row in evaluated["documents"] if row["processing_status"] == "COMPLETED")
    assert process_only["documents"][0]["fields"] == evaluated_document["fields"]
    assert evaluated["evaluation"]["accuracy"] == 1.0
    assert evaluated["evaluation"]["denominator"] == 1
    assert evaluated["evaluation"]["deterministic_pairs"] == 1
    assert evaluated["evaluation"]["ground_truth_stage"] == "post_extraction_only"


def test_evaluation_dashboard_counts_missing_false_positive_precision_and_recall():
    document = inspect_content("synthetic.png", _image_bytes(), group_key="dataset")
    expected = inspect_content("synthetic.json", json.dumps({
        "doc_id": "synthetic",
        "fields": {
            "patient_name": {"value": "SYNTHETIC PERSON"},
            "patient_dob": {"value": "2000-01-01"},
        },
    }).encode(), group_key="dataset")
    page = PageResult("safe", "p1", "cms1500", quality_score=0.9)
    for name, value in (("patient_name", "SYNTHETIC PERSON"),
                        ("patient_city", "SYNTHETIC CITY")):
        field = FieldResult("safe", "p1", name, value, FieldState.ACCEPT, 0.95)
        field.attempts = [Attempt("primary_ocr", "stub", value, 0.95)]
        page.fields[name] = field
        page.decisions[name] = [("ACCEPT", "test")]
    receipt = service.build_receipt(
        page, [], "balanced", 10.0, source_kind="local_workspace")

    batch = workspace.run_batch(
        [expected, document], evaluate=True,
        processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: receipt))
    evaluation = batch["evaluation"]

    assert evaluation["documents_evaluated"] == 1
    assert evaluation["evaluated_fields"] == 2
    assert evaluation["correct_fields"] == 1
    assert evaluation["incorrect_fields"] == 0
    assert evaluation["missing_fields"] == 1
    assert evaluation["false_positive_fields"] == 1
    assert evaluation["accuracy"] == 0.5
    assert evaluation["precision"] == 0.5
    assert evaluation["recall"] == 0.5
    assert evaluation["accuracy_by_document_type"][0]["document_type"] == "cms1500"
    assert {row["field_name"] for row in evaluation["accuracy_by_field"]} == {
        "patient_name", "patient_dob", "patient_city"}


def test_zero_pair_evaluation_reports_accuracy_unavailable_with_pair_counts():
    document = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [document], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()), evaluate=True)

    evaluation = batch["evaluation"]
    assert evaluation["accuracy"] is None
    assert evaluation["critical_accuracy"] is None
    assert evaluation["documents_found"] == 1
    assert evaluation["expected_records_found"] == 0
    assert evaluation["deterministic_pairs"] == 0
    assert evaluation["ambiguous_pairs"] == 0
    assert evaluation["unmatched_documents"] == 1
    assert evaluation["unmatched_expected_records"] == 0
    assert evaluation["evaluated_fields"] == 0
    assert evaluation["denominator"] == 0


def test_process_documents_mode_never_parses_expected_output(monkeypatch):
    document = inspect_content("synthetic.png", _image_bytes())
    expected = inspect_content("synthetic.json", json.dumps({
        "doc_id": "synthetic", "fields": {"patient_name": {"value": "EXPECTED"}}
    }).encode())
    monkeypatch.setattr(
        workspace, "parse_expected_output",
        lambda *_: (_ for _ in ()).throw(AssertionError("ground truth leaked")),
    )
    batch = workspace.run_batch(
        [document, expected], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()), evaluate=False)
    assert batch["evaluation"] is None


def test_fixed_width_expected_output_is_parsed_only_for_evaluation():
    row = ("BA0" + " " * 317 + "\n" +
           "CA0" + " " * 20 + "SYNTHETIC".ljust(20) + "PERSON".ljust(12)
           + " " * (320 - 3 - 20 - 20 - 12) + "\n").encode("ascii")
    item = inspect_content("expected.txt", row)
    assert item.role == FileRole.EXPECTED_OUTPUT
    assert isinstance(workspace.parse_expected_output(item), list)


def test_folder_tier_router_symbol_is_absent():
    assert "_official" + "_tier" not in inspect.getsource(workspace)


def test_official_container_preserves_adapter_evidence_semantics(monkeypatch):
    item = inspect_content(
        "synthetic.001", _image_bytes("TIFF"), group_key="Group A")
    calls = []
    stages = []

    monkeypatch.setattr(
        workspace, "local_ocr",
        lambda page: ([], "HEALTH INSURANCE CLAIM FORM CMS-1500 PATIENT INSURED", 1.0),
    )

    def structured(image, words, form, doc_id, **kwargs):
        calls.append((form, kwargs))
        return _page_for_official(doc_id)

    monkeypatch.setattr(workspace, "structured_page", structured)
    result = workspace.process_item(item, progress=stages.append)

    assert len(calls) == 1 and calls[0][0] == "cms1500"
    assert calls[0][1]["preset"] == "balanced"
    assert calls[0][1]["run_retry"] is False
    assert calls[0][1]["stage_latency"] is not None
    assert result["processing_status"] == "COMPLETED"
    assert result["evidence_semantics"] == "official_monochrome_adapter"
    assert result["escalation_summary"]["external_provider_calls"] == 0
    assert workspace.ProcessingStage.LOCAL_RETRY.value in {
        event["stage"] for event in stages
    }


def test_single_monochrome_cms1500_falls_back_to_official_adapter(monkeypatch):
    item = inspect_content("synthetic.001", _image_bytes("TIFF"))
    monkeypatch.setattr(
        workspace, "_default_page_processor",
        lambda image, doc_id, mode: _empty_receipt(doc_id),
    )
    monkeypatch.setattr(
        workspace, "local_ocr",
        lambda page: ([], "HEALTH INSURANCE CLAIM FORM CMS-1500 PATIENT INSURED", 1.0),
    )
    monkeypatch.setattr(
        workspace, "structured_page",
        lambda image, words, form, doc_id, **kwargs: _page_for_official(doc_id),
    )

    result = workspace.process_item(item)

    assert result["processing_status"] == "COMPLETED"
    assert result["document_type"] == "cms1500"
    assert result["fields"][0]["fields"]
    assert result["validations"]
    assert result["governor_summary"] == {"ACCEPT": 1}
    assert result["evidence_semantics"] == "official_monochrome_adapter"
    assert result["escalation_summary"]["external_provider_calls"] == 0
    assert set(result["latency"]["stages_ms"]) == {
        "tiff_decode", "preprocessing", "registration", "crop_generation",
        "primary_ocr", "retry_ocr", "normalization", "validation", "governor",
        "reporting",
    }
    assert result["latency"]["unattributed_ms"] >= 0


def test_official_marker_abstention_falls_through_to_normal_preprocessed_route(monkeypatch):
    item = inspect_content("synthetic.png", _image_bytes())
    calls = []
    monkeypatch.setattr(workspace, "_red_router_abstains", lambda _item: True)
    monkeypatch.setattr(
        workspace, "_process_official_item",
        lambda *args, **kwargs: calls.append(kwargs) or None,
    )
    monkeypatch.setattr(
        workspace, "_default_page_processor", lambda *args: _receipt())

    result = workspace.process_item(item)

    assert calls[0]["require_detection"] is True
    assert result["processing_status"] == "COMPLETED"
    assert result["document_type"] == "cms1500"


def _page_for_official(doc_id):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "patient_name", "SYNTHETIC PERSON",
                        FieldState.ACCEPT, 0.95)
    field.attempts = [Attempt("primary_ocr", "official_local", field.value, 0.95)]
    page.fields = {"patient_name": field}
    page.decisions = {"patient_name": [("ACCEPT", "test")]}
    return page


def _workspace_ui_state(item=None, batch=None, mode="balanced"):
    state = streamlit_app._new_workspace_state({})
    state["operating_mode"] = mode
    if item is not None:
        state["inventory"] = [item]
        state["selected_document_ids"] = [item.safe_source_id]
    if batch is not None:
        streamlit_app._store_workspace_batch(state, batch)
    return state


def test_local_workspace_ui_uses_connected_tabs_and_status_only_sidebar(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.run(timeout=30)
    assert not app.exception
    assert any(item.value == "Intake" for item in app.subheader)
    assert [item.label for item in app.radio] == ["Workflow", "Input source"]
    assert len(app.get("file_uploader")) == 1
    assert [tab.label for tab in app.tabs] == [
        "Intake & Run", "Results", "Human Review", "Accuracy", "Cost"]
    assert not app.sidebar.radio
    assert [button.label for button in app.sidebar.button] == ["Reset session"]


def test_local_workspace_renders_accuracy_and_cost_dashboards_from_batch(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state(item, batch)

    app.run(timeout=30)

    assert not app.exception
    assert any(item.value == "Accuracy dashboard" for item in app.subheader)
    assert any(item.value == "Cost dashboard" for item in app.subheader)
    assert any("Coverage estimate" in item.value for item in app.info)


def test_local_workspace_renders_ground_truth_accuracy_dashboard(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    document = inspect_content("synthetic.png", _image_bytes(), group_key="dataset")
    expected = inspect_content("synthetic.json", json.dumps({
        "doc_id": "synthetic",
        "fields": {"patient_name": {"value": "SYNTHETIC PERSON"}},
    }).encode(), group_key="dataset")
    batch = workspace.run_batch(
        [expected, document], evaluate=True,
        processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    state = _workspace_ui_state(document, batch)
    state["inventory"] = [expected, document]
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state

    app.run(timeout=30)

    assert not app.exception
    assert any(item.label == "Exact field accuracy" and item.value == "100.00%"
               for item in app.metric)


def test_local_workspace_state_survives_tab_navigation_reruns(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state(item, batch)

    app.run(timeout=30)
    next(button for button in app.button if button.label == "Open Results").click().run(
        timeout=30)
    assert app.session_state["cr_workspace_tabs"] == "Results"
    for tab in ["Results", "Human Review", "Accuracy", "Cost", "Intake & Run"]:
        app.session_state["cr_workspace_tabs"] = tab
        app.run(timeout=30)
        assert not app.exception
        state = app.session_state[streamlit_app.WORKSPACE_STATE_KEY]
        assert state["inventory"][0].safe_source_id == item.safe_source_id
        assert state["selected_document_ids"] == [item.safe_source_id]
        assert state["batch_results"]["batch_job_id"] == batch["batch_job_id"]
    assert any(button.label == "Download document JSON"
               for button in app.get("download_button"))
    assert any(button.label == "Download batch JSON"
               for button in app.get("download_button"))
    assert any(item.value == "Accuracy dashboard" for item in app.subheader)
    assert any(item.value == "Cost dashboard" for item in app.subheader)
    assert not any("Build an inventory" in item.value for item in app.info)


def test_workspace_state_contract_is_initialized_once_without_overwriting_values():
    session = {}
    state = streamlit_app._workspace_state(session)
    required = {
        "workflow", "operating_mode", "inventory", "selected_document_ids",
        "scan_result", "batch_results", "selected_result_id", "processing_state",
        "retry_receipts", "review_queue", "review_corrections",
        "evaluation_summary", "cost_summary",
    }
    state["workflow"] = "Evaluate Dataset"
    state["review_corrections"].append({"field_name": "synthetic_field"})

    same_state = streamlit_app._workspace_state(session)

    assert required <= state.keys()
    assert same_state is state
    assert same_state["workflow"] == "Evaluate Dataset"
    assert same_state["review_corrections"] == [{"field_name": "synthetic_field"}]


def test_operating_mode_has_one_canonical_value_in_selector_header_and_sidebar(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30).run(timeout=30)

    next(item for item in app.selectbox if item.label == "Operating mode").set_value(
        "economy").run(timeout=30)

    state = app.session_state[streamlit_app.WORKSPACE_STATE_KEY]
    visible_html = "\n".join(item.value for item in app.markdown)
    assert state["operating_mode"] == "economy"
    assert app.session_state["cr_operating_mode"] == "economy"
    assert visible_html.count("Mode: Economy") == 2
    assert "Mode: Balanced" not in visible_html


def test_review_correction_survives_tab_navigation(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _unresolved_receipt()))
    state = _workspace_ui_state(item, batch)
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.run(timeout=30)

    next(widget for widget in app.selectbox
         if widget.label == "Review action").set_value("Mark not applicable").run(timeout=30)
    next(widget for widget in app.text_input
         if widget.label == "Correction reason").set_value(
             "Synthetic field is not applicable").run(timeout=30)
    next(button for button in app.button
         if button.label == "Save and next").click().run(timeout=30)

    corrected_state = app.session_state[streamlit_app.WORKSPACE_STATE_KEY]
    assert corrected_state["batch_results"]["summary"]["unresolved_fields"] == 0
    assert corrected_state["batch_results"]["documents"][0][
        "processing_status"] == "COMPLETED"
    assert corrected_state["review_queue"] == []
    assert len(corrected_state["review_corrections"]) == 1
    assert "INAPPLICABLE" in workspace.export_document_json(
        corrected_state["batch_results"]["documents"][0])

    navigation = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    navigation.session_state[streamlit_app.WORKSPACE_STATE_KEY] = corrected_state
    for tab in ["Human Review", "Accuracy", "Cost", "Intake & Run"]:
        navigation.session_state["cr_workspace_tabs"] = tab
        navigation.run(timeout=30)

    persisted = navigation.session_state[streamlit_app.WORKSPACE_STATE_KEY]
    assert len(persisted["review_corrections"]) == 1
    assert persisted["batch_results"]["summary"]["unresolved_fields"] == 0
    assert persisted["cost_summary"] == persisted["batch_results"]["summary"][
        "cost_dashboard"]


def test_reset_session_is_the_only_full_clear_action(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state(item, batch)
    app.run(timeout=30)

    app.sidebar.button[0].click().run(timeout=30)

    state = app.session_state[streamlit_app.WORKSPACE_STATE_KEY]
    assert state["inventory"] == []
    assert state["selected_document_ids"] == []
    assert state["batch_results"] is None
    assert state["review_corrections"] == []
    assert state["evaluation_summary"] is None
    assert state["cost_summary"] is None


def test_partial_document_is_available_to_streamlit_document_selector():
    class StopRendering(Exception):
        pass

    class SelectorProbe:
        def subheader(self, _label):
            pass

        def info(self, _message):
            raise AssertionError("PARTIAL output was hidden")

        def selectbox(self, _label, options, **_kwargs):
            self.options = options
            raise StopRendering

    partial = {"processing_status": "PARTIAL", "source_file": "synthetic.png"}
    failed = {"processing_status": "FAILED_EXTRACTION", "source_file": "empty.png"}
    probe = SelectorProbe()

    assert "PARTIAL" in workspace.PRODUCED_OUTPUT
    with pytest.raises(StopRendering):
        streamlit_app._render_local_document(
            probe, {"documents": [partial, failed]}, [])
    assert probe.options == [partial, failed]


def test_validation_rows_are_readable_and_not_raw_objects():
    rows = streamlit_app._validation_rows([{
        "page": 1,
        "field_name": "patient_dob",
        "results": [{
            "validator": "date_valid", "verdict": "FAIL",
            "detail": "synthetic invalid date",
        }],
    }])

    assert rows == [{
        "Page": 1,
        "Field": "patient_dob",
        "Validation": "date_valid",
        "Status": "FAIL",
        "Message": "synthetic invalid date",
        "Severity": "ERROR",
    }]
    assert "[object Object]" not in str(rows)


def test_provider_and_batch_render_rows_are_complete_and_secret_free():
    provider_rows = streamlit_app._provider_rows({"provider_escalations": [{
        "page": 1, "field_name": "patient_dob", "multimodal_eligible": True,
        "provider_enabled": False, "provider_name": "openrouter",
        "configured_model": "synthetic/model", "credential_available": True,
        "external_call_attempted": False, "external_call_count": 0,
        "reason_not_attempted": "disabled by policy",
        "final_workflow_state": "PENDING_MULTIMODAL_PROVIDER_DISABLED",
        "no_data_sent": True,
    }]})
    summary_rows = streamlit_app._batch_summary_rows({
        key: 0 for key in streamlit_app.BATCH_COUNTERS
    } | {"measured_cost_usd": 0.0, "projected_cost_usd": 0.0,
         "throughput_pages_per_minute": 0.0})

    assert provider_rows[0]["Provider"] == "OpenRouter"
    assert provider_rows[0]["Enabled"] == "No"
    assert provider_rows[0]["Credential available"] == "Yes"
    assert provider_rows[0]["External call attempted"] == "No"
    assert provider_rows[0]["External calls"] == 0
    assert provider_rows[0]["Reason not attempted"] == "disabled by policy"
    assert provider_rows[0]["No data sent"] == "Yes"
    assert "KEY" not in json.dumps(provider_rows).upper()
    assert all(isinstance(row["Value"], (int, float)) for row in summary_rows)
    assert "Unknown" not in json.dumps(summary_rows)


def test_evaluation_display_distinguishes_unavailable_and_valid_accuracy():
    unavailable = streamlit_app._evaluation_display({
        "accuracy": None, "critical_accuracy": None, "deterministic_pairs": 0,
        "evaluated_fields": 0, "denominator": 0,
    })
    zero_fields = streamlit_app._evaluation_display({
        "accuracy": None, "critical_accuracy": None, "deterministic_pairs": 1,
        "evaluated_fields": 0, "denominator": 0,
    })
    valid = streamlit_app._evaluation_display({
        "accuracy": 0.75, "critical_accuracy": 1.0, "deterministic_pairs": 1,
        "evaluated_fields": 4, "denominator": 4,
    })

    assert unavailable["message"] == "Accuracy unavailable — no valid evaluation pairs"
    assert zero_fields["message"] == "Accuracy unavailable — no valid evaluation pairs"
    assert valid == {"message": None, "field_accuracy": "75.00%",
                     "critical_accuracy": "100.00%"}


def test_workspace_job_does_not_start_twice_and_unlocks_after_success():
    state = streamlit_app._new_workspace_state({})
    calls = []
    assert streamlit_app._queue_workspace_job(state, "job")
    assert not streamlit_app._queue_workspace_job(state, "job")

    batch = {"batch_job_id": "job", "documents": [], "summary": {}, "evaluation": None}
    result = streamlit_app._run_workspace_job(
        state, "job", lambda: calls.append("run") or batch)

    assert result == batch
    assert calls == ["run"]
    assert state["processing_state"]["running"] is False
    assert state["processing_state"]["active_job"] is None
    assert streamlit_app._run_workspace_job(
        state, "job", lambda: calls.append("duplicate")) is None
    assert calls == ["run"]


def test_workspace_job_unlocks_after_failure():
    state = streamlit_app._new_workspace_state({})
    streamlit_app._queue_workspace_job(state, "job")

    result = streamlit_app._run_workspace_job(
        state, "job", lambda: (_ for _ in ()).throw(RuntimeError("sensitive")))

    assert result is None
    assert state["processing_state"]["running"] is False
    assert "sensitive" not in state["processing_state"]["error"]


def test_stage_progress_exposes_local_retry_and_final_partial_state():
    item = inspect_content("synthetic.png", _image_bytes())
    stages = []

    batch = workspace.run_batch(
        [item],
        processor=lambda _item, _mode: workspace.process_item(
            item, page_processor=lambda *args: _unresolved_receipt()),
        stage_progress=stages.append,
    )

    assert stages[0]["stage"] == workspace.ProcessingStage.QUEUED.value
    assert stages[-1]["stage"] == workspace.ProcessingStage.PARTIAL.value
    assert stages[-1]["document_number"] == 1
    assert batch["documents"][0]["processing_stage"] == "PARTIAL"


def test_operating_mode_changes_real_governor_policy_and_is_recorded():
    assert workspace.mode_policy("economy")["accept_threshold"] < (
        workspace.mode_policy("accuracy")["accept_threshold"]
    )
    item = inspect_content("synthetic.png", _image_bytes())

    batch = workspace.run_batch(
        [item], mode="accuracy", processor=lambda _item, _mode: workspace.process_item(
            item, mode=_mode, page_processor=lambda *args: _receipt()))

    assert batch["operating_mode"] == "accuracy"
    assert batch["mode_policy"]["external_calls_enabled"] is False


def test_coverage_excludes_inapplicable_and_is_not_accuracy():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _inapplicable_receipt())

    coverage = workspace.coverage_metrics(result)

    assert coverage == {
        "available": True,
        "schema_fields": 1,
        "applicable_fields": 0,
        "inapplicable_fields": 1,
        "fields_produced": 0,
        "validated_fields": 0,
        "unresolved_fields": 0,
        "extraction_coverage": None,
        "validated_coverage": None,
        "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
        "message": "Coverage estimate — no ground truth provided",
        "critical_fields": 0,
        "critical_fields_resolved": 0,
        "critical_fields_resolution_rate": None,
        "primary_ocr_resolution_rate": None,
        "retry_resolution_rate": None,
        "multimodal_resolution_rate": None,
        "human_review_rate": None,
    }
    assert "accuracy" not in coverage


def test_cost_dashboard_reconciles_components_counters_and_exports():
    item = inspect_content("synthetic.png", _image_bytes())
    receipt = _receipt()
    receipt["costs"].update({
        "primary_ocr": {"basis": "MEASURED", "value_usd": 0.0001},
        "retry_ocr": {"basis": "MEASURED", "value_usd": 0.0002},
        "local_compute_other": {"basis": "MEASURED", "value_usd": 0.0003},
        "local_compute": {"basis": "MEASURED", "value_usd": 0.0006},
        "api": {"basis": "PROJECTED", "value_usd": 0.0004},
        "measured_api": {"basis": "MEASURED", "value_usd": 0.0},
        "measured_total_automated": {"basis": "MEASURED", "value_usd": 0.0006},
        "projected_total_automated": {"basis": "PROJECTED", "value_usd": 0.001},
    })
    receipt["usage"] = {"input_tokens": 100, "output_tokens": 10}
    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=lambda *args: receipt))
    dashboard = batch["summary"]["cost_dashboard"]

    assert dashboard["components"]["local_compute"]["value_usd"] == 0.0006
    assert dashboard["components"]["projected_api"] == {
        "basis": "OFFLINE_ORACLE", "value_usd": 0.0004}
    assert dashboard["components"]["total_automated"]["value_usd"] == 0.0006
    assert dashboard["components"]["projected_total_automated"]["value_usd"] == 0.001
    assert dashboard["unit_costs"]["cost_per_page"]["value_usd"] == 0.0006
    assert dashboard["unit_costs"]["cost_per_correctly_resolved_field"][
        "value_usd"] is None
    assert dashboard["counters"]["input_tokens"] == 100
    assert dashboard["counters"]["output_tokens"] == 10
    assert all(row["basis"] == "PROJECTED" for row in dashboard["mode_comparison"])
    csv_row = list(csv.DictReader(io.StringIO(workspace.export_batch_csv(batch))))[0]
    assert json.loads(csv_row["cost_dashboard_json"]) == dashboard


def test_measured_cost_donut_uses_only_non_overlapping_measured_components():
    components = {
        "primary_ocr": {"basis": "MEASURED", "value_usd": 0.0001},
        "retry_ocr": {"basis": "MEASURED", "value_usd": 0.0002},
        "local_compute_other": {"basis": "MEASURED", "value_usd": 0.0003},
        "local_compute": {"basis": "MEASURED", "value_usd": 0.0006},
        "multimodal_input_tokens": {"basis": "MEASURED", "value_usd": 0.00004},
        "multimodal_output_tokens": {"basis": "MEASURED", "value_usd": 0.00006},
        "projected_api": {"basis": "OFFLINE_ORACLE", "value_usd": 0.001},
        "total_automated": {"basis": "MEASURED", "value_usd": 0.0007},
    }

    rows = streamlit_app._measured_cost_donut_rows(components)

    assert {row["Component"] for row in rows} == {
        "Primary OCR", "Retry OCR", "Other local compute",
        "Multimodal input tokens", "Multimodal output tokens",
    }
    assert sum(row["Cost USD"] for row in rows) == pytest.approx(0.0007)


def test_unknown_schema_reports_coverage_unavailable():
    result = workspace._failed_result(
        inspect_content("synthetic.png", _image_bytes()), "no schema",
        status="FAILED_EXTRACTION")

    assert workspace.coverage_metrics(result)["available"] is False


def test_retry_document_replaces_result_and_preserves_prior_attempt_in_memory():
    item = inspect_content("synthetic.png", _image_bytes())
    failed = workspace._failed_result(item, "first failure")
    batch = {
        "batch_job_id": "batch-test", "processing_status": "COMPLETED_WITH_ERRORS",
        "operating_mode": "balanced", "documents": [failed],
        "summary": workspace.summarize_results([failed]), "evaluation": None,
    }

    retried = workspace.retry_document(
        batch, item, processor=lambda _item, _mode: workspace.process_item(
            item, page_processor=lambda *args: _receipt()))

    document = retried["documents"][0]
    assert document["processing_status"] == "COMPLETED"
    assert document["retry_count"] == 1
    assert document["_prior_results"][0]["processing_status"] == "FAILED"
    assert document["retry_history"][0]["external_calls"] == 0


def test_human_review_correction_revalidates_updates_output_and_audit():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _unresolved_receipt())
    queue = workspace.build_review_queue(result)

    assert queue[0]["field_name"] == "patient_dob"
    corrected = workspace.apply_human_review(
        result, page=1, field_name="patient_dob", action="MARK_NOT_APPLICABLE",
        value=None, reason="Synthetic field is not applicable")

    field = corrected["fields"][0]["fields"]["patient_dob"]
    assert field["state"] == "INAPPLICABLE"
    assert corrected["unresolved_fields"] == 0
    assert corrected["human_review_summary"]["required"] == 0
    assert corrected["human_review_summary"]["completed"] == 1
    assert corrected["review_audit"][-1]["action"] == "MARK_NOT_APPLICABLE"
    assert "INAPPLICABLE" in workspace.export_document_json(corrected)

    repeated = workspace.apply_human_review(
        corrected, page=1, field_name="patient_dob", action="MARK_NOT_APPLICABLE",
        value=None, reason="Synthetic field remains not applicable")
    assert repeated["human_review_summary"] == {"required": 0, "completed": 1}


def test_valid_human_edit_is_exported_as_human_corrected_without_external_call():
    item = inspect_content("synthetic.png", _image_bytes())
    page = PageResult("safe", "p1", "cms1500", quality_score=0.9)
    field = FieldResult("safe", "p1", "patient_name", None,
                        FieldState.ESCALATE, 0.2)
    field.attempts = [Attempt("primary_ocr", "stub", None, 0.2)]
    page.fields = {"patient_name": field}
    page.decisions = {"patient_name": [("ESCALATE", "synthetic unresolved")]}
    receipt = service.build_receipt(
        page, [], "balanced", 10.0, source_kind="local_workspace")
    result = workspace.process_item(item, page_processor=lambda *args: receipt)

    corrected = workspace.apply_human_review(
        result, page=1, field_name="patient_name", action="EDIT_VALUE",
        value="DOE, JANE", reason="Synthetic visual confirmation")

    field = corrected["fields"][0]["fields"]["patient_name"]
    assert field["state"] == "ACCEPT_WITH_OVERRIDE"
    assert field["override"]["resolution"] == "HUMAN_CORRECTED"
    assert corrected["escalation_summary"]["external_provider_calls"] == 0
    assert "DOE, JANE" in workspace.export_document_json(corrected)
    assert "DOE, JANE" in workspace.export_document_csv(corrected)


def test_mode_changes_multimodal_field_eligibility_without_enabling_calls():
    item = inspect_content("synthetic.png", _image_bytes())

    def receipt(mode):
        page = PageResult("safe", "p1", "cms1500", quality_score=0.9)
        field = FieldResult("safe", "p1", "patient_city", "SYNTHETIC CITY",
                            FieldState.ESCALATE, 0.2)
        field.attempts = [Attempt("primary_ocr", "stub", field.value, 0.2)]
        page.fields = {"patient_city": field}
        page.decisions = {"patient_city": [("ESCALATE", "synthetic unresolved")]}
        return service.build_receipt(
            page, [], mode, 10.0, source_kind="local_workspace")

    economy = workspace.process_item(
        item, mode="economy", page_processor=lambda *args: receipt("economy"))
    accuracy = workspace.process_item(
        item, mode="accuracy", page_processor=lambda *args: receipt("accuracy"))

    assert economy["provider_escalations"][0]["multimodal_eligible"] is False
    assert accuracy["provider_escalations"][0]["multimodal_eligible"] is True
    assert economy["escalation_summary"]["external_provider_calls"] == 0
    assert accuracy["escalation_summary"]["external_provider_calls"] == 0
