"""Local batch contracts use synthetic images and stub page receipts."""
from __future__ import annotations

import csv
import inspect
import io
import json

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
        "pending_human_review": 0,
        "external_provider_calls": 0,
    }


def test_inapplicable_service_line_field_is_not_unresolved():
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(
        item, page_processor=lambda *args: _inapplicable_receipt())

    assert result["processing_status"] == "COMPLETED"
    assert result["unresolved_fields"] == 0
    assert result["governor_summary"] == {"INAPPLICABLE": 1}
    assert result["resolution_summary"]["inapplicable"] == 1


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
    assert evaluated["evaluation"]["ground_truth_stage"] == "post_extraction_only"


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

    monkeypatch.setattr(
        workspace, "local_ocr",
        lambda page: ([], "HEALTH INSURANCE CLAIM FORM CMS-1500 PATIENT INSURED", 1.0),
    )

    def structured(image, words, form, doc_id, **kwargs):
        calls.append((form, kwargs))
        return _page_for_official(doc_id)

    monkeypatch.setattr(workspace, "structured_page", structured)
    result = workspace.process_item(item)

    assert len(calls) == 1 and calls[0][0] == "cms1500"
    assert calls[0][1]["preset"] == "balanced"
    assert calls[0][1]["run_retry"] is False
    assert calls[0][1]["stage_latency"] is not None
    assert result["processing_status"] == "COMPLETED"
    assert result["evidence_semantics"] == "official_monochrome_adapter"
    assert result["escalation_summary"]["external_provider_calls"] == 0


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


def _page_for_official(doc_id):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    field = FieldResult(doc_id, "p1", "patient_name", "SYNTHETIC PERSON",
                        FieldState.ACCEPT, 0.95)
    field.attempts = [Attempt("primary_ocr", "official_local", field.value, 0.95)]
    page.fields = {"patient_name": field}
    page.decisions = {"patient_name": [("ACCEPT", "test")]}
    return page


def test_local_workspace_ui_exposes_intake_without_public_controls(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.run(timeout=30)
    assert not app.exception
    assert any(item.value == "Intake" for item in app.subheader)
    assert [item.label for item in app.radio] == ["Workflow", "Input source"]
    assert len(app.get("file_uploader")) == 1
    assert not app.sidebar


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
    assert probe.options == [partial]


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


def test_workspace_job_does_not_start_twice_and_unlocks_after_success():
    state = {}
    calls = []
    assert streamlit_app._queue_workspace_job(state, "job")
    assert not streamlit_app._queue_workspace_job(state, "job")

    result = streamlit_app._run_workspace_job(
        state, "job", lambda: calls.append("run") or {"ok": True})

    assert result == {"ok": True}
    assert calls == ["run"]
    assert state["workspace_job_running"] is False
    assert "workspace_active_job" not in state
    assert streamlit_app._run_workspace_job(
        state, "job", lambda: calls.append("duplicate")) is None
    assert calls == ["run"]


def test_workspace_job_unlocks_after_failure():
    state = {}
    streamlit_app._queue_workspace_job(state, "job")

    result = streamlit_app._run_workspace_job(
        state, "job", lambda: (_ for _ in ()).throw(RuntimeError("sensitive")))

    assert result is None
    assert state["workspace_job_running"] is False
    assert "sensitive" not in state["workspace_job_error"]
