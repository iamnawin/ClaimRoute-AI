"""Day 10 application contract: thin pipeline adapter, safe uploads, honest costs."""
import io
import json

import pytest
from PIL import Image

from engine.schemas import Attempt, FieldResult, FieldState, PageResult, ValidationStamp, Verdict
from app import service


def _image_bytes(fmt="PNG", *, frames=1):
    images = [Image.new("RGB", (120, 80), "white") for _ in range(frames)]
    out = io.BytesIO()
    images[0].save(out, format=fmt, save_all=frames > 1,
                   append_images=images[1:])
    return out.getvalue()


def _page():
    page = PageResult("demo", "p1", "cms1500", quality_score=0.91)
    accepted = FieldResult("demo", "p1", "patient_name", "Parker, Lori",
                           FieldState.ACCEPT, 0.96, (5, 5, 80, 25))
    accepted.stamps = [ValidationStamp("name_format", Verdict.PASS)]
    accepted.attempts = [Attempt("primary_ocr", "paddle", "Parker, Lori", 0.96)]
    reviewed = FieldResult("demo", "p1", "insured_id", "A123",
                           FieldState.HUMAN_REVIEW, 0.40, (5, 30, 80, 50))
    reviewed.stamps = [ValidationStamp("id_format", Verdict.FAIL)]
    reviewed.attempts = [
        Attempt("primary_ocr", "paddle", "A12B", 0.30),
        Attempt("retry_ocr", "tesseract", "A123", 0.40, 0.000001, 12.0),
        Attempt("multimodal", "offline-oracle", "A123", 0.92, 0.00003, 5.0),
    ]
    page.fields = {"patient_name": accepted, "insured_id": reviewed}
    page.decisions = {
        "patient_name": [("ACCEPT", "validators clean")],
        "insured_id": [("RETRY", "low confidence"), ("ESCALATE", "retry exhausted"),
                       ("HUMAN_REVIEW", "attempt budget exhausted")],
    }
    page.escalations = {"insured_id": {"escalated": True, "decision": "both_fail_validators"}}
    return page


def test_application_imports_without_running_ui():
    from app import streamlit_app
    assert callable(streamlit_app.main)


def test_public_mode_denies_folder_access_and_local_mode_enables_it():
    from app import streamlit_app

    assert streamlit_app.app_mode({}) == "public_synthetic"
    assert streamlit_app.local_folder_enabled({}) is False
    local = {"CLAIMROUTE_APP_MODE": "local_workspace"}
    assert streamlit_app.app_mode(local) == "local_workspace"
    assert streamlit_app.local_folder_enabled(local) is True


def test_modes_load_and_balanced_is_default():
    modes = service.load_operating_modes()
    assert service.DEFAULT_MODE == "balanced"
    assert set(modes) == {"economy", "balanced", "accuracy"}
    assert modes["balanced"]["local_accept_confidence"] == 0.80


def test_upload_accepts_synthetic_png_and_detects_metadata():
    document = service.inspect_upload(
        "claim.png", _image_bytes(), synthetic_confirmed=True)
    assert document.file_format == "PNG"
    assert document.page_count == 1
    assert document.size_bytes > 0


def test_upload_rejects_extension_and_oversize():
    with pytest.raises(service.UploadValidationError, match="file type"):
        service.inspect_upload(
            "claim.exe", b"not an image", synthetic_confirmed=True)
    with pytest.raises(service.UploadValidationError, match="size"):
        service.inspect_upload(
            "claim.png", b"x" * 11, max_bytes=10, synthetic_confirmed=True)


def test_upload_rejects_too_many_pages():
    data = _image_bytes("TIFF", frames=2)
    with pytest.raises(service.UploadValidationError, match="page limit"):
        service.inspect_upload(
            "claim.tiff", data, max_pages=1, synthetic_confirmed=True)


def test_public_upload_requires_synthetic_attestation_and_deletes_temp_file(tmp_path):
    with pytest.raises(service.UploadValidationError, match="synthetic"):
        service.inspect_upload("claim.png", _image_bytes())

    document = service.inspect_upload(
        "claim.png", _image_bytes(), synthetic_confirmed=True, temp_root=tmp_path)

    assert document.file_format == "PNG"
    assert list(tmp_path.iterdir()) == []


def test_uploaded_document_invokes_real_pipeline_locally_only(tmp_path):
    calls = []

    def runner(image, doc_id, ledger, **kwargs):
        calls.append(kwargs)
        ledger.log(doc_id=doc_id, page_id="p1", operation="preprocess",
                   cost_usd=0.0001, latency_ms=10)
        return _page()

    receipt = service.process_document(
        Image.new("RGB", (120, 80), "white"), "upload-1", "balanced",
        source_kind="upload", runner=runner, ledger_dir=tmp_path)
    assert calls == [{"preset_name": "balanced", "run_escalate": False,
                      "escalate_model": None, "tier": "clean"}]
    assert receipt["document"]["document_type"] == "cms1500"


def test_bundled_synthetic_uses_offline_oracle_only(tmp_path):
    calls = []

    def runner(image, doc_id, ledger, **kwargs):
        calls.append(kwargs)
        return _page()

    service.process_document(
        Image.new("RGB", (120, 80), "white"), "demo", "economy",
        source_kind="bundled_synthetic", runner=runner, ledger_dir=tmp_path)
    assert calls[0]["run_escalate"] is True
    assert calls[0]["escalate_model"] == "offline-oracle"


def test_summary_calculations_and_cost_labels():
    entries = [
        {"operation": "preprocess", "cost_usd": 0.0001, "latency_ms": 10, "meta": {}},
        {"operation": "escalate_offline-oracle", "cost_usd": 0.00003,
         "latency_ms": 5, "meta": {"input_tokens": 100, "output_tokens": 10}},
    ]
    receipt = service.build_receipt(_page(), entries, "balanced", 20.0,
                                    source_kind="bundled_synthetic")
    assert receipt["funnel"] == {
        "fields_detected": 2, "accepted_locally": 1, "accepted_with_flag": 0,
        "locally_retried": 1, "escalated": 1, "human_review": 1,
        "api_calls_avoided": 1,
    }
    assert receipt["costs"]["local_compute"]["basis"] == "MEASURED"
    assert receipt["costs"]["api"]["basis"] == "PROJECTED"
    assert receipt["costs"]["measured_api"]["value_usd"] == 0.0
    assert receipt["usage"] == {"input_tokens": 100, "output_tokens": 10}


def test_json_exports_are_valid_and_separate():
    receipt = service.build_receipt(_page(), [], "balanced", 20.0,
                                    source_kind="upload")
    final_doc = json.loads(service.export_json(receipt, audit=False))
    audit_doc = json.loads(service.export_json(receipt, audit=True))
    assert final_doc["fields"]["patient_name"]["value"] == "Parker, Lori"
    assert "funnel" not in final_doc
    assert audit_doc["funnel"]["human_review"] == 1
    assert audit_doc["fields"][1]["processing_path"]


def test_pipeline_errors_are_wrapped_without_values(tmp_path):
    def runner(*args, **kwargs):
        raise RuntimeError("patient value: secret")

    with pytest.raises(service.AppProcessingError, match="Extraction failed") as exc:
        service.process_document(
            Image.new("RGB", (120, 80), "white"), "upload-1", "balanced",
            source_kind="upload", runner=runner, ledger_dir=tmp_path)
    assert "secret" not in str(exc.value)


def test_unknown_mode_is_rejected_before_pipeline(tmp_path):
    with pytest.raises(ValueError, match="Unknown operating mode"):
        service.process_document(
            Image.new("RGB", (120, 80), "white"), "demo", "turbo",
            source_kind="bundled_synthetic", runner=lambda *a, **k: _page(),
            ledger_dir=tmp_path)
