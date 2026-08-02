"""Judge-facing dashboard data contracts.

Every card, row, and badge on the dashboard has to come from a real counter in
the batch receipt, a real runtime probe, or an explicitly labelled projection.
These tests exist to make fabricated dashboard values fail loudly.
"""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import dashboard


def _summary(**overrides) -> dict:
    summary = {
        "files": 3,
        "pages": 5,
        "success": 2,
        "partial": 1,
        "failed": 0,
        "failed_extraction": 0,
        "applicable_fields": 120,
        "fields_produced": 114,
        "validated_fields": 110,
        "primary_resolved": 96,
        "retry_attempted": 12,
        "retry_resolved": 8,
        "pending_multimodal": 4,
        "multimodal_attempted": 2,
        "multimodal_failed": 1,
        "human_review_required": 6,
        "human_review_completed": 1,
        "unresolved_fields": 10,
        "external_calls": 0,
        "measured_cost_usd": 0.00012,
        "projected_cost_usd": 0.00031,
        "mean_latency_ms": 6521.0,
        "throughput_pages_per_minute": 9.2,
        "unresolved_items": [],
    }
    summary.update(overrides)
    return summary


def _cost_dashboard(**overrides) -> dict:
    dashboard_metrics = {
        "components": {
            "primary_ocr": {"basis": "MEASURED", "value_usd": 0.00007},
            "retry_ocr": {"basis": "MEASURED", "value_usd": 0.00002},
            "local_compute_other": {"basis": "MEASURED", "value_usd": 0.00003},
            "local_compute": {"basis": "MEASURED", "value_usd": 0.00012},
            "multimodal_input_tokens": {"basis": "MEASURED", "value_usd": 0.0},
            "multimodal_output_tokens": {"basis": "MEASURED", "value_usd": 0.0},
            "projected_api": {"basis": "OFFLINE_ORACLE", "value_usd": 0.00019},
            "total_automated": {"basis": "MEASURED", "value_usd": 0.00012},
            "projected_total_automated": {"basis": "PROJECTED", "value_usd": 0.00031},
        },
        "human_review_estimate": {
            "field_count": 6,
            "assumed_cost_per_field_usd": 0.05,
            "total": {"basis": "ASSUMED", "value_usd": 0.30},
        },
        "enterprise_projection": {
            "one_million_pages": {"basis": "PROJECTED", "value_usd": 62.0},
            "ten_million_pages": {"basis": "PROJECTED", "value_usd": 620.0},
            "hundred_million_pages": {"basis": "PROJECTED", "value_usd": 6200.0},
        },
        "human_review_projection": {
            "one_million_pages": {"basis": "ASSUMED", "value_usd": 60000.0},
            "ten_million_pages": {"basis": "ASSUMED", "value_usd": 600000.0},
            "hundred_million_pages": {"basis": "ASSUMED", "value_usd": 6000000.0},
        },
        "total_projection": {
            "one_million_pages": {"basis": "PROJECTED + ASSUMED", "value_usd": 60062.0},
            "ten_million_pages": {"basis": "PROJECTED + ASSUMED", "value_usd": 600620.0},
            "hundred_million_pages": {
                "basis": "PROJECTED + ASSUMED", "value_usd": 6006200.0},
        },
        "counters": {"external_calls": 0, "input_tokens": 0, "output_tokens": 0,
                     "multimodal_eligible_fields": 4},
    }
    dashboard_metrics.update(overrides)
    return dashboard_metrics


def _provider_state(**overrides) -> dict:
    state = {
        "provider_enabled": False,
        "provider_name": "openrouter",
        "configured_model": "synthetic/vision-model",
        "credential_available": False,
        "external_call_attempted": False,
        "external_call_count": 0,
        "reason_not_attempted": "disabled by policy",
        "final_workflow_state": "HUMAN_REVIEW_REQUIRED",
        "no_data_sent": True,
    }
    state.update(overrides)
    return state


# --------------------------------------------------------------- summary cards

def test_summary_cards_report_real_counters_with_labelled_denominators():
    cards = {card["label"]: card for card in dashboard.summary_cards(_summary())}

    assert cards["Documents processed"]["value"] == 3
    assert cards["Pages processed"]["value"] == 5
    assert cards["Fields produced"]["value"] == 114
    assert cards["Fields produced"]["detail"] == "of 120 applicable fields"
    assert cards["Validated coverage"]["value"] == pytest.approx(110 / 120)
    assert cards["Validated coverage"]["detail"] == "110 of 120 applicable fields"
    assert cards["Measured automated cost"]["value"] == pytest.approx(0.00012)
    assert cards["Measured automated cost"]["basis"] == "MEASURED"
    assert cards["Human review required"]["value"] == 6


def test_validated_coverage_is_unavailable_rather_than_zero_without_a_schema():
    cards = {card["label"]: card
             for card in dashboard.summary_cards(_summary(
                 applicable_fields=0, validated_fields=0, fields_produced=0))}

    assert cards["Validated coverage"]["value"] is None
    assert cards["Validated coverage"]["detail"] == "No applicable fields yet"


def test_summary_cards_never_report_accuracy_without_ground_truth():
    labels = [card["label"] for card in dashboard.summary_cards(_summary())]

    assert not any("accuracy" in label.lower() for label in labels)


# ---------------------------------------------------------------------- funnel

def test_funnel_covers_the_real_route_and_never_mixes_documents_with_fields():
    stages = dashboard.funnel_stages(_summary(), _cost_dashboard())
    by_stage = {stage["stage"]: stage for stage in stages}

    assert [stage["stage"] for stage in stages] == [
        "Uploaded", "Primary OCR", "Validated", "Local retry",
        "Multimodal eligible", "Multimodal attempted", "Human review", "Completed",
    ]
    assert by_stage["Uploaded"]["unit"] == "documents"
    assert by_stage["Completed"]["unit"] == "documents"
    assert by_stage["Uploaded"]["value"] == 3
    assert by_stage["Completed"]["value"] == 2
    assert by_stage["Primary OCR"]["unit"] == "fields"
    assert by_stage["Primary OCR"]["value"] == 96
    assert by_stage["Local retry"]["value"] == 8
    assert by_stage["Local retry"]["denominator"] == 12
    assert by_stage["Multimodal eligible"]["value"] == 4
    assert by_stage["Human review"]["value"] == 6
    assert all(stage["unit"] in {"documents", "fields"} for stage in stages)
    field_stages = [stage for stage in stages if stage["unit"] == "fields"]
    assert all(stage["denominator"] is not None for stage in field_stages)


def test_funnel_progress_states_its_own_denominator():
    progress = dashboard.coverage_progress(_summary())

    assert progress["value"] == pytest.approx(110 / 120)
    assert progress["label"] == "Validated coverage"
    assert progress["caption"] == "110 of 120 applicable fields validated"


def test_funnel_progress_is_unavailable_without_applicable_fields():
    progress = dashboard.coverage_progress(_summary(applicable_fields=0,
                                                    validated_fields=0))

    assert progress["value"] is None
    assert "Unavailable" in progress["caption"]


# --------------------------------------------------------------- cost breakdown

def test_cost_breakdown_separates_measured_projected_and_assumed():
    rows = dashboard.cost_breakdown_rows(_cost_dashboard())
    groups = {row["label"]: row["group"] for row in rows}

    assert groups["Primary OCR"] == "measured"
    assert groups["Retry processing"] == "measured"
    assert groups["Other local compute"] == "measured"
    assert groups["Multimodal input (external)"] == "measured"
    assert groups["Multimodal output (external)"] == "measured"
    assert groups["Selective AI cost"] == "projected"
    assert groups["Human review"] == "assumed"
    assert {row["group"] for row in rows} == {"measured", "projected", "assumed"}


def test_measured_rows_partition_the_measured_total_without_double_counting():
    rows = dashboard.cost_breakdown_rows(_cost_dashboard())
    measured = [row for row in rows if row["group"] == "measured"]

    assert sum(row["value_usd"] for row in measured) == pytest.approx(
        dashboard.measured_total(_cost_dashboard()))


def test_projected_cost_is_never_presented_as_measured_spend():
    rows = {row["label"]: row for row in dashboard.cost_breakdown_rows(_cost_dashboard())}

    assert rows["Selective AI cost"]["basis"] == "OFFLINE_ORACLE"
    assert rows["Human review"]["basis"] == "ASSUMED"
    measured = [row for row in dashboard.cost_breakdown_rows(_cost_dashboard())
                if row["group"] == "measured"]
    assert all(row["basis"] == "MEASURED" for row in measured)
    assert dashboard.measured_total(_cost_dashboard()) == pytest.approx(0.00012)


# ------------------------------------------------------------ recent documents

def test_recent_documents_expose_status_stage_and_real_per_document_values():
    rows = dashboard.recent_document_rows([{
        "safe_source_id": "doc-1",
        "source_file": "synthetic_cms1500.png",
        "document_type": "cms1500",
        "page_count": 2,
        "processing_status": "PARTIAL",
        "processing_stage": "HUMAN_REVIEW_REQUIRED",
        "unresolved_fields": 3,
        "coverage": {"validated_coverage": 0.9},
        "measured_cost": {"usd": 0.00004},
        "latency": {"milliseconds": 6100.0},
    }])

    assert rows[0]["Document"] == "synthetic_cms1500.png"
    assert rows[0]["Type"] == "cms1500"
    assert rows[0]["Pages"] == 2
    assert rows[0]["Status"] == "PARTIAL"
    assert rows[0]["Stage"] == "HUMAN_REVIEW_REQUIRED"
    assert rows[0]["Validated coverage"] == pytest.approx(0.9)
    assert rows[0]["Unresolved"] == 3
    assert rows[0]["Total cost"] == pytest.approx(0.00004)
    assert rows[0]["Processing time"] == pytest.approx(6.1)


def test_recent_documents_keep_queued_and_processing_documents_visible():
    rows = dashboard.recent_document_rows([
        {"safe_source_id": "a", "source_file": "a.png", "processing_status": "QUEUED",
         "processing_stage": "QUEUED"},
        {"safe_source_id": "b", "source_file": "b.png", "processing_status": "PROCESSING",
         "processing_stage": "PRIMARY_OCR"},
        {"safe_source_id": "c", "source_file": "c.png",
         "processing_status": "FAILED_EXTRACTION", "processing_stage": "FAILED_EXTRACTION"},
    ])

    assert [row["Status"] for row in rows] == [
        "QUEUED", "PROCESSING", "FAILED_EXTRACTION"]
    assert all(row["Validated coverage"] is None for row in rows)


def test_recent_documents_are_empty_without_a_batch():
    assert dashboard.recent_document_rows([]) == []


# ------------------------------------------------------- escalations by field

def test_escalations_by_field_come_from_actual_unresolved_items():
    rows = dashboard.escalations_by_field(_summary(unresolved_items=[
        {"field_name": "billing_provider_npi", "state": "ESCALATE"},
        {"field_name": "billing_provider_npi", "state": "HUMAN_REVIEW"},
        {"field_name": "billing_provider_npi", "state": "ESCALATE"},
        {"field_name": "patient_dob", "state": "HUMAN_REVIEW"},
    ]))

    assert rows[0]["field_name"] == "billing_provider_npi"
    assert rows[0]["count"] == 3
    assert rows[0]["share"] == pytest.approx(0.75)
    assert rows[1]["field_name"] == "patient_dob"
    assert rows[1]["count"] == 1
    assert rows[1]["share"] == pytest.approx(0.25)
    assert sum(row["count"] for row in rows) == 4


def test_escalations_by_field_is_empty_when_nothing_escalated():
    assert dashboard.escalations_by_field(_summary(unresolved_items=[])) == []
    assert dashboard.ESCALATIONS_EMPTY_STATE == (
        "No field escalations in the current run.")


# ------------------------------------------------------------- provider panel

def test_provider_panel_reports_only_the_configured_provider_and_model():
    rows = dashboard.provider_panel_rows(
        _provider_state(), session_report=None, calls_used=0)
    values = json.dumps(rows).lower()

    assert {"Configured provider", "Configured model", "Provider enabled",
            "Credential available", "Measured external calls"} <= {
                row["label"] for row in rows}
    for foreign in ("gpt-4", "gemini", "claude", "leaderboard"):
        assert foreign not in values


def test_provider_panel_omits_latency_and_tokens_until_something_is_measured():
    rows = {row["label"]: row["value"] for row in dashboard.provider_panel_rows(
        _provider_state(), session_report=None, calls_used=0)}

    assert rows["Measured external calls"] == 0
    assert rows["Average latency"] == "Not measured"
    assert rows["Measured external spend"] == "Not measured"


def test_provider_panel_labels_one_measured_call_as_a_smoke_test():
    note = dashboard.provider_panel_note(calls_used=1)

    assert note == ("Measured synthetic smoke test - not a comparative model "
                    "benchmark.")
    assert dashboard.provider_panel_note(calls_used=0) == (
        "No external provider call has been made in this session.")


def test_provider_panel_shows_measured_usage_when_a_call_happened():
    rows = {row["label"]: row["value"] for row in dashboard.provider_panel_rows(
        _provider_state(provider_enabled=True, credential_available=True),
        session_report={
            "provider": "openrouter", "model": "synthetic/vision-model",
            "calls_made": 1, "measured_incremental_usd": 0.00001829,
            "session_spend_usd": 0.00001829,
            "limits": {"max_session_spend_usd": 0.02},
        },
        calls_used=1, usage={"input_tokens": 812, "output_tokens": 14},
        latency_ms=1180.0)}

    assert rows["Measured external calls"] == 1
    assert rows["Measured input tokens"] == 812
    assert rows["Measured output tokens"] == 14
    assert rows["Measured external spend"] == pytest.approx(0.00001829)
    assert rows["Average latency"] == pytest.approx(1.18)


# ---------------------------------------------------------------- projections

def test_projection_rows_cover_all_three_scales_and_split_the_assumption():
    rows = dashboard.projection_rows(_cost_dashboard())

    assert [row["scale"] for row in rows] == ["1M pages", "10M pages", "100M pages"]
    assert rows[2]["automated_usd"] == pytest.approx(6200.0)
    assert rows[2]["automated_basis"] == "PROJECTED"
    assert rows[2]["human_review_usd"] == pytest.approx(6000000.0)
    assert rows[2]["human_review_basis"] == "ASSUMED"
    assert rows[2]["total_usd"] == pytest.approx(6006200.0)
    assert rows[2]["total_basis"] == "PROJECTED + ASSUMED"


def test_projection_rows_survive_a_batch_with_no_measured_pages():
    empty = _cost_dashboard(
        enterprise_projection={"one_million_pages": {"basis": "PROJECTED",
                                                     "value_usd": None}},
        human_review_projection={"one_million_pages": {"basis": "ASSUMED",
                                                       "value_usd": None}},
        total_projection={"one_million_pages": {"basis": "PROJECTED + ASSUMED",
                                                "value_usd": None}})
    rows = dashboard.projection_rows(empty)

    assert rows[0]["automated_usd"] is None
    assert rows[0]["total_usd"] is None


# -------------------------------------------------------------- system health

def test_system_health_reports_only_components_that_actually_exist():
    rows = dashboard.system_health(
        ocr_binary=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        validator_fields=64, provider_state=_provider_state(),
        workspace_ready=True)
    components = [row["component"] for row in rows]
    states = {row["component"]: row["state"] for row in rows}

    assert "Database" not in components
    assert "Queue workers" not in components
    assert "Multimodal gateway" not in components
    assert states["Streamlit app"] == "Healthy"
    assert states["Local OCR engine"] == "Available"
    assert states["Validator configuration"] == "Available"
    assert states["Provider policy"] == "Available"
    assert states["External provider"] == "Disabled by policy"
    assert states["Provider credential"] == "Not configured"
    assert states["Workspace session"] == "Available"
    assert all(row["state"] in dashboard.HEALTH_STATES for row in rows)


def test_system_health_reports_a_missing_ocr_binary_instead_of_claiming_health():
    rows = {row["component"]: row for row in dashboard.system_health(
        ocr_binary=None, validator_fields=0, provider_state=_provider_state(),
        workspace_ready=False)}

    assert rows["Local OCR engine"]["state"] == "Unavailable"
    assert "tesseract" in rows["Local OCR engine"]["detail"].lower()
    assert rows["Validator configuration"]["state"] == "Warning"
    assert rows["Workspace session"]["state"] == "Warning"


def test_enabled_provider_with_credential_is_reported_as_available():
    rows = {row["component"]: row["state"] for row in dashboard.system_health(
        ocr_binary="/usr/bin/tesseract", validator_fields=64,
        provider_state=_provider_state(provider_enabled=True,
                                       credential_available=True),
        workspace_ready=True)}

    assert rows["External provider"] == "Available"
    assert rows["Provider credential"] == "Available"


def test_runtime_probe_reads_the_real_environment():
    probe = dashboard.probe_runtime()

    assert set(probe) == {"ocr_binary", "validator_fields", "provider_state"}
    assert probe["validator_fields"] > 0
    assert probe["provider_state"]["provider_name"]


# ----------------------------------------------------------------- environment

def test_environment_label_names_the_running_mode():
    assert dashboard.environment_label("local_workspace") == "Local Workspace"
    assert dashboard.environment_label("public_synthetic") == "Synthetic Demo"


# ----------------------------------------- projection maths stay in the engine

def _priced_result(measured: float, projected: float, pages: int,
                   review_required: int) -> dict:
    return {
        "processing_status": "COMPLETED",
        "page_count": pages,
        "fields": [],
        "cost_breakdown": {},
        "measured_cost": {"usd": measured},
        "projected_cost": {"usd": projected},
        "coverage": {"validated_fields": 4},
        "human_review_summary": {"required": review_required},
        "resolution_summary": {},
        "escalation_summary": {},
        "retry_summary": {},
        "usage": {},
    }


def test_workspace_projects_one_hundred_million_pages_from_the_measured_rate():
    from app import workspace

    metrics = workspace.cost_dashboard_metrics(
        [_priced_result(0.0002, 0.0004, pages=4, review_required=2)])
    projection = metrics["enterprise_projection"]

    assert set(projection) == {"one_million_pages", "ten_million_pages",
                               "hundred_million_pages"}
    assert projection["one_million_pages"]["value_usd"] == pytest.approx(100.0)
    assert projection["hundred_million_pages"]["value_usd"] == pytest.approx(10000.0)
    assert projection["hundred_million_pages"]["basis"] == "PROJECTED"


def test_workspace_keeps_the_human_review_assumption_out_of_the_automated_total():
    from app import workspace

    metrics = workspace.cost_dashboard_metrics(
        [_priced_result(0.0002, 0.0004, pages=4, review_required=2)])
    automated = metrics["enterprise_projection"]["one_million_pages"]["value_usd"]
    review = metrics["human_review_projection"]["one_million_pages"]
    total = metrics["total_projection"]["one_million_pages"]
    per_field = metrics["human_review_estimate"]["assumed_cost_per_field_usd"]

    assert review["basis"] == "ASSUMED"
    assert review["value_usd"] == pytest.approx(2 * per_field / 4 * 1_000_000)
    assert total["basis"] == "PROJECTED + ASSUMED"
    assert total["value_usd"] == pytest.approx(automated + review["value_usd"])


def test_workspace_projection_is_unavailable_without_processed_pages():
    from app import workspace

    metrics = workspace.cost_dashboard_metrics([])

    assert metrics["enterprise_projection"]["hundred_million_pages"][
        "value_usd"] is None
    assert metrics["human_review_projection"]["hundred_million_pages"][
        "value_usd"] is None
    assert metrics["total_projection"]["hundred_million_pages"]["value_usd"] is None


# ------------------------------------------------- the rendered dashboard view

def _synthetic_batch():
    from app import service, workspace
    from app.intake import inspect_content
    from engine.schemas import Attempt, FieldResult, FieldState, PageResult

    stream = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    item = inspect_content("synthetic.png", stream.getvalue())

    def receipt(*_args):
        page = PageResult(item.safe_source_id, "p1", "cms1500", quality_score=0.9)
        field = FieldResult(item.safe_source_id, "p1", "patient_name",
                            "SYNTHETIC PERSON", FieldState.ACCEPT, 0.95)
        field.attempts = [Attempt("primary_ocr", "stub", field.value, 0.95)]
        page.fields = {"patient_name": field}
        page.decisions = {"patient_name": [("ACCEPT", "test")]}
        return service.build_receipt(page, [], "balanced", 10.0,
                                     source_kind="local_workspace")

    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=receipt))
    return item, batch


def _dashboard_app(monkeypatch, state=None):
    from app import streamlit_app

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
    if state is not None:
        app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.session_state["cr_workspace_tabs"] = "Dashboard"
    app.run(timeout=60)
    return app


def _text(app) -> str:
    return "\n".join(
        [row.value for row in app.markdown]
        + [row.value for row in app.info]
        + [row.value for row in app.caption])


def test_dashboard_is_the_first_workspace_destination():
    from app import streamlit_app

    assert streamlit_app.WORKSPACE_TABS[0] == "Dashboard"
    assert streamlit_app.WORKSPACE_TABS[1:] == [
        "Intake & Run", "Results", "Human Review", "Accuracy", "Cost"]


def test_dashboard_renders_an_honest_empty_state_before_any_run(monkeypatch):
    app = _dashboard_app(monkeypatch)

    assert not app.exception
    assert dashboard.ESCALATIONS_EMPTY_STATE in _text(app)
    assert "No documents have been processed in this session yet." in _text(app)


def test_dashboard_never_claims_services_that_are_not_deployed(monkeypatch):
    app = _dashboard_app(monkeypatch)
    health = next(row.value for row in app.markdown
                  if 'class="cr-health"' in row.value).lower()

    assert "database" not in health
    assert "queue" not in health
    assert "gateway" not in health
    assert "streamlit app" in health
    assert "admin@" not in _text(app).lower()


def test_dashboard_reports_the_real_session_counters(monkeypatch):
    from app import streamlit_app

    item, batch = _synthetic_batch()
    state = streamlit_app._new_workspace_state({})
    state["inventory"] = [item]
    state["selected_document_ids"] = [item.safe_source_id]
    streamlit_app._store_workspace_batch(state, batch)

    app = _dashboard_app(monkeypatch, state)
    text = _text(app)

    opener = next(row for row in app.selectbox if row.label == "Open a document")

    assert not app.exception
    assert "Local Workspace" in text
    assert "Documents processed" in text
    assert "Validated coverage" in text
    assert str(batch["summary"]["pages"]) in text
    assert opener.options == ["synthetic.png"]
    assert opener.value == item.safe_source_id
    assert any(row.label == "Open selected document in Results"
               for row in app.button)


def test_dashboard_escalations_follow_a_human_correction(monkeypatch):
    """One batch receipt feeds every surface: correcting a field must move the
    dashboard, not just the review queue."""
    from app import service, streamlit_app, workspace
    from app.intake import inspect_content
    from engine.schemas import Attempt, FieldResult, FieldState, PageResult

    stream = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(stream, format="PNG")
    item = inspect_content("synthetic.png", stream.getvalue())

    def receipt(*_args):
        page = PageResult(item.safe_source_id, "p1", "cms1500", quality_score=0.9)
        field = FieldResult(item.safe_source_id, "p1", "patient_dob", None,
                            FieldState.ESCALATE, 0.2)
        field.attempts = [Attempt("primary_ocr", "stub", None, 0.2),
                          Attempt("retry_ocr", "stub", None, 0.2)]
        page.fields = {"patient_dob": field}
        page.decisions = {"patient_dob": [("RETRY", "test"),
                                          ("ESCALATE", "retry exhausted")]}
        return service.build_receipt(page, [], "balanced", 10.0,
                                     source_kind="local_workspace")

    batch = workspace.run_batch(
        [item], processor=lambda item, mode: workspace.process_item(
            item, page_processor=receipt))
    state = streamlit_app._new_workspace_state({})
    state["inventory"] = [item]
    state["selected_document_ids"] = [item.safe_source_id]
    streamlit_app._store_workspace_batch(state, batch)

    app = _dashboard_app(monkeypatch, state)
    assert "Patient Dob" in _text(app)
    assert dashboard.ESCALATIONS_EMPTY_STATE not in _text(app)

    next(row for row in app.selectbox
         if row.label == "Review action").set_value(
             "Mark not applicable").run(timeout=60)
    next(row for row in app.text_input
         if row.label == "Correction reason").set_value(
             "Synthetic field is not applicable").run(timeout=60)
    next(row for row in app.button
         if row.label == "Save and next").click().run(timeout=60)

    corrected = app.session_state[streamlit_app.WORKSPACE_STATE_KEY]
    assert corrected["batch_results"]["summary"]["unresolved_fields"] == 0
    assert dashboard.ESCALATIONS_EMPTY_STATE in _text(app)


def test_dashboard_does_not_add_a_third_operating_mode_badge(monkeypatch):
    item, batch = _synthetic_batch()
    from app import streamlit_app

    state = streamlit_app._new_workspace_state({})
    state["inventory"] = [item]
    streamlit_app._store_workspace_batch(state, batch)
    app = _dashboard_app(monkeypatch, state)

    visible_html = "\n".join(row.value for row in app.markdown)
    assert visible_html.count("Mode: Balanced") == 2
