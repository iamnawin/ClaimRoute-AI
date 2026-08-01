"""Local batch contracts use synthetic images and stub page receipts."""
from __future__ import annotations

import csv
import io
import json

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import service, workspace
from app.intake import FileRole, inspect_content
from engine.schemas import Attempt, FieldResult, FieldState, PageResult


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


def test_official_group_detection_is_path_based_not_filename_based():
    assert workspace._official_tier("Group A") == "A"
    assert workspace._official_tier("root/Group C/nested") == "C"
    assert workspace._official_tier("ordinary") is None


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

    assert calls == [("cms1500", {"preset": "balanced", "run_retry": True})]
    assert result["processing_status"] == "COMPLETED"
    assert result["evidence_semantics"] == "official_monochrome_adapter"
    assert result["escalation_summary"]["external_provider_calls"] == 0


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
