"""Honest status semantics and content-based routing for the local workspace.

These contracts exist because a monochrome claim scan was reported as
`document_type=unstructured, fields={}, unresolved_fields=0, status=COMPLETED`.
An empty extraction is never a success.
"""
from __future__ import annotations

import io

from PIL import Image

from app import service, workspace
from app.intake import inspect_content
from data_factory.generator import generate_claim
from data_factory.render_cms1500 import render
from engine.router import route
from engine.schemas import Attempt, FieldResult, FieldState, PageResult


def _image_bytes(fmt="PNG", frames=1):
    images = [Image.new("RGB", (32, 24), "white") for _ in range(frames)]
    stream = io.BytesIO()
    images[0].save(stream, format=fmt, save_all=frames > 1, append_images=images[1:])
    return stream.getvalue()


def _receipt_with(fields: dict[str, FieldResult], doc_id="safe"):
    page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
    page.fields = fields
    page.decisions = {name: [(field.state.value, "test")] for name, field in fields.items()}
    return service.build_receipt(page, [], "balanced", 10.0, source_kind="local_workspace")


def _field(name, value, state):
    field = FieldResult("safe", "p1", name, value, state, 0.95)
    field.attempts = [Attempt("primary_ocr", "stub", value, 0.95)]
    return field


def _cms1500_tiff(*, monochrome: bool) -> bytes:
    page, _ = render(generate_claim(90211))
    stream = io.BytesIO()
    if monochrome:
        page = page.convert("L").convert("1")
    page.save(stream, format="TIFF")
    return stream.getvalue()


def test_empty_extraction_is_not_reported_completed():
    """Zero extracted fields is a failed extraction, never a success."""
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(item, page_processor=lambda *args: _receipt_with({}))
    assert result["processing_status"] == "FAILED_EXTRACTION"
    assert result["warnings"], "an empty extraction must explain itself"


def test_unresolved_required_field_yields_partial():
    """Useful extraction with an unresolved field is PARTIAL, not COMPLETED."""
    fields = {
        "patient_name": _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT),
        "patient_dob": _field("patient_dob", None, FieldState.HUMAN_REVIEW),
    }
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(item, page_processor=lambda *args: _receipt_with(fields))
    assert result["processing_status"] == "PARTIAL"
    assert result["unresolved_fields"] == 1


def test_fully_resolved_document_still_reports_completed():
    """The happy path must not regress."""
    fields = {"patient_name": _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT)}
    item = inspect_content("synthetic.png", _image_bytes())
    result = workspace.process_item(item, page_processor=lambda *args: _receipt_with(fields))
    assert result["processing_status"] == "COMPLETED"
    assert result["unresolved_fields"] == 0


def test_batch_with_partial_document_reports_completed_with_review():
    """A batch containing an unresolved document must not claim clean success."""
    partial = {
        "patient_name": _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT),
        "patient_dob": _field("patient_dob", None, FieldState.HUMAN_REVIEW),
    }
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda i, mode: workspace.process_item(
            i, page_processor=lambda *args: _receipt_with(partial)))
    assert batch["processing_status"] == "COMPLETED_WITH_REVIEW"


def test_partial_document_still_counted_in_batch_summary():
    """PARTIAL documents produced output; their metrics must not vanish."""
    partial = {
        "patient_name": _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT),
        "patient_dob": _field("patient_dob", None, FieldState.HUMAN_REVIEW),
    }
    item = inspect_content("synthetic.png", _image_bytes())
    batch = workspace.run_batch(
        [item], processor=lambda i, mode: workspace.process_item(
            i, page_processor=lambda *args: _receipt_with(partial)))
    assert batch["summary"]["pages"] == 1
    assert batch["summary"]["unresolved_fields"] == 1


def test_monochrome_claim_scan_is_not_silently_reported_empty_and_completed():
    """The reported defect: a monochrome CMS-1500 outside a Group folder.

    The red-ink router abstains on a 1-bit scan, so routing must fall back to
    content, and a zero-field outcome must never be dressed up as COMPLETED.
    """
    item = inspect_content("claim_dev.tif", _cms1500_tiff(monochrome=True))
    result = workspace.process_item(item)
    assert result["processing_status"] != "COMPLETED"
    assert not (result["document_type"] == "unstructured"
                and result["processing_status"] == "COMPLETED")
    assert result["escalation_summary"]["external_provider_calls"] == 0


def test_monochrome_claim_scan_routes_by_content_not_folder_name(monkeypatch):
    """The same monochrome bytes route identically under arbitrary folders."""
    tiff = _cms1500_tiff(monochrome=True)
    monkeypatch.setattr(
        workspace, "local_ocr",
        lambda _page: ([], "HEALTH INSURANCE CLAIM FORM CMS-1500 PATIENT INSURED", 1.0),
    )

    def structured(_image, _words, _form, doc_id, **_kwargs):
        page = PageResult(doc_id, "p1", "cms1500", quality_score=0.9)
        field = _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT)
        page.fields = {"patient_name": field}
        page.decisions = {"patient_name": [("ACCEPT", "test")]}
        return page

    monkeypatch.setattr(workspace, "structured_page", structured)
    results = [workspace.process_item(inspect_content(
        "claim_dev.tif", tiff, group_key=folder))
        for folder in (".", "Group A", "inbox/scans")]

    assert {result["document_type"] for result in results} == {"cms1500"}


def test_color_cms1500_in_group_c_still_routes_as_cms1500(monkeypatch):
    tiff = _cms1500_tiff(monochrome=False)

    def processor(image, doc_id, _mode):
        document_type = route(image)["document_type"]
        page = PageResult(doc_id, "p1", document_type, quality_score=0.9)
        field = _field("patient_name", "SYNTHETIC PERSON", FieldState.ACCEPT)
        page.fields = {"patient_name": field}
        page.decisions = {"patient_name": [("ACCEPT", "test")]}
        return service.build_receipt(
            page, [], "balanced", 10.0, source_kind="local_workspace")

    monkeypatch.setattr(workspace, "_default_page_processor", processor)
    result = workspace.process_item(
        inspect_content("claim_color.tif", tiff, group_key="group c"))

    assert result["document_type"] == "cms1500"
