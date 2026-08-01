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


def _monochrome_cms1500_tiff() -> bytes:
    """A CMS-1500 rendered as a 1-bit scan: no red dropout ink survives."""
    page, _ = render(generate_claim(90211))
    stream = io.BytesIO()
    page.convert("L").convert("1").save(stream, format="TIFF")
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
    item = inspect_content("claim_dev.tif", _monochrome_cms1500_tiff())
    result = workspace.process_item(item)
    assert result["processing_status"] != "COMPLETED"
    assert not (result["document_type"] == "unstructured"
                and result["processing_status"] == "COMPLETED")
    assert result["escalation_summary"]["external_provider_calls"] == 0


def test_monochrome_claim_scan_routes_by_content_not_folder_name():
    """Routing must not depend on the parent directory being named 'Group A'."""
    tiff = _monochrome_cms1500_tiff()
    plain = workspace.process_item(inspect_content("claim_dev.tif", tiff, group_key="."))
    grouped = workspace.process_item(
        inspect_content("claim_dev.tif", tiff, group_key="Group A"))
    assert plain["document_type"] == grouped["document_type"], (
        "the same bytes must route the same way regardless of folder name")
