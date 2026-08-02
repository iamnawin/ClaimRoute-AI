"""ClaimRoute Day 10 Streamlit demo."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import dashboard, multimodal_permission, service, workspace
from app.intake import (FileRole, IntakeError, ScanState, decode_pages,
                        inspect_content, scan_folder)
from engine.escalation.client import load_config, request_from_page
from engine.escalation.errors import MultimodalError
from engine.escalation.live_policy import LiveCallGovernor, ModeError
from engine.escalation.model_router import ModelResolutionError

logger = logging.getLogger(__name__)


BATCH_COUNTERS = {
    "files": "Total files",
    "pages": "Total pages",
    "success": "Completed",
    "partial": "Partial",
    "failed_extraction": "Failed extraction",
    "failed": "Failed",
    "total_fields": "Total fields",
    "applicable_fields": "Applicable fields",
    "fields_produced": "Fields produced",
    "validated_fields": "Validated fields",
    "accepted": "Accepted",
    "accepted_with_flag": "Accepted with flag",
    "retry_attempted": "Retry attempted",
    "retry_resolved": "Retry resolved",
    "unresolved_fields": "Unresolved",
    "inapplicable": "Inapplicable",
    "pending_multimodal": "Pending multimodal",
    "multimodal_attempted": "Multimodal attempted",
    "multimodal_failed": "Multimodal failed",
    "human_review_required": "Human review required",
    "human_review_completed": "Human review completed",
    "external_calls": "External calls",
}

WORKSPACE_STATE_KEY = "claimroute_workspace"
WORKSPACE_TABS = ["Dashboard", "Intake & Run", "Results", "Human Review",
                  "Accuracy", "Cost"]

EVALUATION_COUNTERS = {
    "documents_found": "Documents found",
    "expected_records_found": "Expected records found",
    "deterministic_pairs": "Deterministic pairs",
    "ambiguous_pairs": "Ambiguous pairs",
    "unmatched_documents": "Unmatched documents",
    "unmatched_expected_records": "Unmatched expected records",
    "evaluated_fields": "Evaluated fields",
    "denominator": "Denominator",
}


def app_mode(environ=None) -> str:
    source = environ if environ is not None else os.environ
    value = source.get("CLAIMROUTE_APP_MODE", "public_synthetic")
    return "local_workspace" if value == "local_workspace" else "public_synthetic"


def local_folder_enabled(environ=None) -> bool:
    return app_mode(environ) == "local_workspace"


def _fmt_pct(value) -> str:
    return f"{float(value):.2%}"


def _fmt_usd(value) -> str:
    return f"${float(value):,.6f}"


def _fmt_pct_or_unavailable(value) -> str:
    return _fmt_pct(value) if value is not None else "Unavailable"


def _fmt_cost(cost: dict) -> str:
    value = cost.get("value_usd")
    return _fmt_usd(value) if value is not None else "Unavailable"


def _measured_cost_donut_rows(components: dict) -> list[dict]:
    labels = {
        "primary_ocr": "Primary OCR",
        "retry_ocr": "Retry OCR",
        "local_compute_other": "Other local compute",
        "multimodal_input_tokens": "Multimodal input tokens",
        "multimodal_output_tokens": "Multimodal output tokens",
    }
    return [{
        "Component": label,
        "Cost USD": float(components[key]["value_usd"] or 0),
    } for key, label in labels.items()]


def _shown(value, screenshot_safe: bool):
    if screenshot_safe and value not in (None, ""):
        return "[hidden]"
    return value


def _validation_rows(validations: list[dict]) -> list[dict]:
    """Flatten validation stamps into readable table rows."""
    rows = []
    for field in validations:
        for result in field.get("results", []):
            verdict = result.get("verdict", "NOT_APPLICABLE")
            rows.append({
                "Page": field.get("page"),
                "Field": field.get("field_name"),
                "Validation": result.get("validator", "Not applicable"),
                "Status": verdict,
                "Message": result.get("detail") or "—",
                "Severity": "ERROR" if verdict == "FAIL" else "INFO",
            })
    return rows


def _yes_no(value) -> str:
    return "Yes" if bool(value) else "No"


def _provider_label(value: str) -> str:
    return {"openrouter": "OpenRouter", "openai": "OpenAI"}.get(
        str(value).lower(), str(value).replace("_", " ").title())


def _status_label(value: str | None) -> str:
    return str(value or "Unknown").replace("_", " ").title()


def _batch_status_label(value: str | None) -> str:
    return {
        "COMPLETED": "Completed",
        "COMPLETED_WITH_REVIEW": "Completed with review",
        "COMPLETED_WITH_ERRORS": "Completed with errors",
        "PROCESSING": "Processing",
        "CANCELLED": "Cancelled",
    }.get(str(value or ""), _status_label(value))


def _field_filter_options(rows: list[dict]) -> dict[str, set[str] | None]:
    groups = {
        "Accepted": {"ACCEPT", "ACCEPT_WITH_OVERRIDE"},
        "Flagged": {"ACCEPT_WITH_FLAG"},
        "Needs review": {"ESCALATE", "RETRY", "HUMAN_REVIEW"},
        "Inapplicable": {"INAPPLICABLE"},
    }
    options = {f"All fields ({len(rows)})": None}
    for label, states in groups.items():
        count = sum(row.get("State") in states for row in rows)
        options[f"{label} ({count})"] = states
    return options


def _coverage_metric_rows(summary: dict) -> list[list[tuple[str, object]]]:
    applicable = int(summary.get("applicable_fields") or 0)
    return [[
        ("Extraction coverage", _fmt_pct_or_unavailable(
            _ratio_for_display(summary.get("fields_produced"), applicable))),
        ("Validated coverage", _fmt_pct_or_unavailable(
            _ratio_for_display(summary.get("validated_fields"), applicable))),
        ("Critical fields resolved",
         f"{int(summary.get('critical_fields_resolved') or 0)} / "
         f"{int(summary.get('critical_fields') or 0)}"),
        ("Human-review rate", _fmt_pct_or_unavailable(
            summary.get("human_review_rate"))),
    ], [
        ("Primary OCR resolved", int(summary.get("primary_resolved") or 0)),
        ("Retry resolved", int(summary.get("retry_resolved") or 0)),
        ("Multimodal resolved", max(
            0, int(summary.get("multimodal_attempted") or 0)
            - int(summary.get("multimodal_failed") or 0))),
        ("Remaining unresolved", int(summary.get("unresolved_fields") or 0)),
    ]]


def _ratio_for_display(numerator, denominator):
    return float(numerator or 0) / denominator if denominator else None


def _review_action_valid(action: str, value: str, reason: str) -> bool:
    return bool(reason.strip() and (action != "EDIT_VALUE" or value.strip()))


def _resolution_journey(summary: dict) -> list[dict]:
    return [{
        "Applicable": int(summary.get("applicable_fields") or 0),
        "Primary resolved": int(summary.get("primary_resolved") or 0),
        "Retry resolved": int(summary.get("retry_resolved") or 0),
        "Multimodal resolved": max(
            0, int(summary.get("multimodal_attempted") or 0)
            - int(summary.get("multimodal_failed") or 0)),
        "Human corrected": int(summary.get("human_review_completed") or 0),
        "Remaining unresolved": int(summary.get("unresolved_fields") or 0),
    }]


def _resolution_interpretation(summary: dict) -> str:
    journey = _resolution_journey(summary)[0]
    local = journey["Primary resolved"] + journey["Retry resolved"]
    applicable = journey["Applicable"]
    unresolved = journey["Remaining unresolved"]
    return (
        f"Local processing resolved {local} of {applicable} applicable fields. "
        f"{unresolved} remain for multimodal escalation or human review."
    )


def _unresolved_display_rows(batch: dict) -> tuple[list[dict], list[dict]]:
    documents = {row.get("safe_source_id"): row
                 for row in batch.get("documents", [])}
    display, advanced = [], []
    for item in (batch.get("summary") or {}).get("unresolved_items") or []:
        document = documents.get(item.get("safe_source_id"), {})
        evidence = next((row for row in document.get("_review_evidence", [])
                         if row.get("page") == item.get("page")
                         and row.get("field_name") == item.get("field_name")), {})
        state = str(item.get("state") or "")
        route = {
            "ESCALATE": "Multimodal or human review",
            "RETRY": "Local retry",
            "HUMAN_REVIEW": "Human review",
        }.get(state, "Review")
        display.append({
            "Field": str(item.get("field_name") or "").replace("_", " ").title(),
            "Criticality": str(item.get("criticality") or "med").title(),
            "Failure reason": evidence.get("reason") or "Field was not resolved",
            "Route": route,
            "Action": "Needs review",
        })
        advanced.append({
            "safe_source_id": item.get("safe_source_id"),
            "document": item.get("document"),
            "page": item.get("page"),
            "field_name": item.get("field_name"),
            "internal_state": state,
        })
    return display, advanced


def _provider_rows(result: dict) -> list[dict]:
    """Render-safe field escalation rows; credentials are booleans only."""
    return [{
        "Page": row["page"],
        "Field": row["field_name"],
        "Multimodal eligible": _yes_no(row["multimodal_eligible"]),
        "Provider": _provider_label(row["provider_name"]),
        "Enabled": _yes_no(row["provider_enabled"]),
        "Configured model": row["configured_model"] or "Not configured",
        "Credential available": _yes_no(row["credential_available"]),
        "External call attempted": _yes_no(row["external_call_attempted"]),
        "External calls": int(row["external_call_count"] or 0),
        "Reason not attempted": row["reason_not_attempted"] or "—",
        "Final workflow state": row["final_workflow_state"],
        "No data sent": _yes_no(row["no_data_sent"]),
    } for row in result.get("provider_escalations", [])]


def _batch_summary_rows(summary: dict) -> list[dict]:
    rows = [{"Metric": label, "Value": int(summary.get(key) or 0)}
            for key, label in BATCH_COUNTERS.items()]
    rows.extend([
        {"Metric": "Measured cost (USD)",
         "Value": float(summary.get("measured_cost_usd") or 0)},
        {"Metric": "Projected cost (USD)",
         "Value": float(summary.get("projected_cost_usd") or 0)},
        {"Metric": "Throughput (pages/minute)",
         "Value": float(summary.get("throughput_pages_per_minute") or 0)},
    ])
    return rows


def _evaluation_display(evaluation: dict) -> dict:
    denominator = int(evaluation.get("denominator") or 0)
    pairs = int(evaluation.get("deterministic_pairs") or 0)
    if not pairs or not denominator or evaluation.get("accuracy") is None:
        return {"message": "Accuracy unavailable — no valid evaluation pairs",
                "field_accuracy": None, "critical_accuracy": None}
    critical = evaluation.get("critical_accuracy")
    return {
        "message": None,
        "field_accuracy": _fmt_pct(evaluation["accuracy"]),
        "critical_accuracy": (_fmt_pct(critical) if critical is not None
                              else "Unavailable — no evaluated critical fields"),
    }


def _new_workspace_state(session_state) -> dict:
    """Create the single local-workspace state contract, preserving legacy values."""
    batch = session_state.get("workspace_batch")
    inventory = session_state.get("workspace_inventory", [])
    mode = (batch or {}).get("operating_mode") or session_state.get(
        "workspace_mode", service.DEFAULT_MODE)
    workflow = session_state.get("workspace_workflow") or (
        "Evaluate Dataset" if (batch or {}).get("evaluation") is not None
        else "Process Documents")
    return {
        "workflow": workflow,
        "operating_mode": mode,
        "inventory": inventory,
        "selected_document_ids": session_state.get("workspace_selected_ids", []),
        "scan_result": session_state.get("workspace_scan_state"),
        "batch_results": batch,
        "selected_result_id": None,
        "processing_state": {
            "running": bool(session_state.get("workspace_job_running")),
            "pending_job": session_state.get("workspace_pending_job"),
            "active_job": session_state.get("workspace_active_job"),
            "error": session_state.get("workspace_job_error"),
            "stage": session_state.get("workspace_stage"),
            "selection_signature": (),
            "active_retry_job": None,
            "completed_retry_jobs": [],
        },
        "retry_receipts": [],
        "multimodal": {
            "governor": None,
            "receipts": {},
            "active_fingerprint": None,
        },
        "review_queue": [],
        "review_corrections": [],
        "evaluation_summary": (batch or {}).get("evaluation"),
        "cost_summary": ((batch or {}).get("summary") or {}).get("cost_dashboard"),
        "input_source": session_state.get("workspace_source", "Single file"),
        "active_tab": WORKSPACE_TABS[0],
    }


def _workspace_state(session_state) -> dict:
    if WORKSPACE_STATE_KEY not in session_state:
        session_state[WORKSPACE_STATE_KEY] = _new_workspace_state(session_state)
        for key in [
            "workspace_workflow", "workspace_mode", "workspace_source",
            "workspace_inventory", "workspace_selected_ids", "workspace_scan_state",
            "workspace_batch", "workspace_job_running", "workspace_pending_job",
            "workspace_active_job", "workspace_job_error", "workspace_stage",
            "workspace_section",
        ]:
            session_state.pop(key, None)
    return session_state[WORKSPACE_STATE_KEY]


def _review_queue(batch: dict | None) -> list[dict]:
    return [
        {"safe_source_id": result["safe_source_id"], **row}
        for result in (batch or {}).get("documents", [])
        for row in workspace.build_review_queue(result)
    ]


def _store_workspace_batch(state: dict, batch: dict) -> None:
    state["batch_results"] = batch
    state["evaluation_summary"] = batch.get("evaluation")
    state["cost_summary"] = (batch.get("summary") or {}).get("cost_dashboard")
    state["review_queue"] = _review_queue(batch)
    produced = [row for row in batch.get("documents", [])
                if row.get("processing_status") not in {"SKIPPED", "DUPLICATE"}]
    available = {row["safe_source_id"] for row in produced}
    if state.get("selected_result_id") not in available:
        state["selected_result_id"] = produced[0]["safe_source_id"] if produced else None


def _refresh_workspace_batch(state: dict) -> None:
    batch = state.get("batch_results")
    if not batch:
        return
    batch["processing_status"] = workspace._batch_status(batch["documents"])
    batch["summary"] = workspace.summarize_results(batch["documents"])
    if state["workflow"] == "Evaluate Dataset":
        workspace.evaluate_dataset(batch, state["inventory"])
    else:
        batch["evaluation"] = None
    _store_workspace_batch(state, batch)


def _sync_workspace_controls(session_state, state: dict) -> None:
    for widget_key, state_key in {
        "cr_workflow": "workflow",
        "cr_operating_mode": "operating_mode",
        "cr_input_source": "input_source",
        "cr_selected_documents": "selected_document_ids",
        "cr_result_document": "selected_result_id",
        "cr_workspace_tabs": "active_tab",
    }.items():
        if widget_key in session_state:
            state[state_key] = session_state[widget_key]
    batch = state.get("batch_results")
    if batch:
        state["operating_mode"] = batch.get("operating_mode", state["operating_mode"])
        session_state["cr_operating_mode"] = state["operating_mode"]
        if batch.get("evaluation") is not None:
            state["workflow"] = "Evaluate Dataset"
            session_state["cr_workflow"] = state["workflow"]


def _activate_workspace_tab(session_state, tab: str) -> None:
    state = _workspace_state(session_state)
    state["active_tab"] = tab
    session_state["cr_workspace_tabs"] = tab


def _reset_workspace_session(session_state) -> None:
    session_state.clear()


def _queue_workspace_job(state, fingerprint: str) -> bool:
    processing = state["processing_state"]
    if processing.get("running"):
        return False
    processing["running"] = True
    processing["pending_job"] = fingerprint
    processing["error"] = None
    return True


def _run_workspace_job(state, fingerprint: str, runner):
    processing = state["processing_state"]
    if (not processing.get("running")
            or processing.get("pending_job") != fingerprint
            or processing.get("active_job")):
        return None
    processing["active_job"] = fingerprint
    try:
        result = runner()
        _store_workspace_batch(state, result)
        return result
    except Exception:
        processing["error"] = (
            "Processing failed safely. Review the local terminal log and retry."
        )
        return None
    finally:
        processing["running"] = False
        processing["pending_job"] = None
        processing["active_job"] = None


def _retry_fingerprint(document: dict) -> str:
    return f"{document['safe_source_id']}:{int(document.get('retry_count') or 0)}"


def _queue_retry_job(state: dict, fingerprint: str) -> bool:
    processing = state["processing_state"]
    if (processing.get("active_retry_job")
            or fingerprint in processing.get("completed_retry_jobs", [])):
        return False
    processing["active_retry_job"] = fingerprint
    return True


def _run_retry_job(state: dict, fingerprint: str, source, *, runner=None):
    processing = state["processing_state"]
    if processing.get("active_retry_job") != fingerprint:
        return None
    runner = runner or workspace.retry_document
    try:
        retried = runner(
            state["batch_results"], source, mode=state["operating_mode"])
        _store_workspace_batch(state, retried)
        document = next(row for row in retried["documents"]
                        if row["safe_source_id"] == source.safe_source_id)
        receipt = document["retry_history"][-1]
        state["retry_receipts"].append({
            "safe_source_id": source.safe_source_id,
            **receipt,
        })
        processing.setdefault("completed_retry_jobs", []).append(fingerprint)
        return retried
    finally:
        processing["active_retry_job"] = None


def _multimodal_session(state: dict) -> tuple[dict, LiveCallGovernor, dict]:
    session = state.setdefault("multimodal", {
        "governor": None, "receipts": {}, "active_fingerprint": None, "mode": None,
    })
    config = load_config()
    mode = state.get("operating_mode") or service.DEFAULT_MODE
    # Rebuilding on a mode change is intentional: the governor holds the session
    # spend counters AND the resolved model, and carrying counters from one
    # model's spend across to another would misreport both.
    if session.get("governor") is None or session.get("mode") != mode:
        session["governor"] = LiveCallGovernor(config, mode=mode)
        session["mode"] = mode
    return session, session["governor"], config


def _multimodal_session_or_error(state: dict):
    """(session, governor, config, "") or (None, None, None, reason).

    The multimodal panel is one optional block on a page whose real work -
    extraction, validation, review, exports - is already finished and local. A
    provider-configuration defect used to raise through _render_local_document
    and blank the entire results page, so a feature that makes no calls at all
    could destroy the output of the run.

    Only the initialization boundary is contained, and only into a named reason.
    This is not a general except-and-continue: the governor's own refusals stay
    typed outcomes, and a programmer defect still reaches the log below with its
    full traceback rather than being smoothed into "unavailable".
    """
    try:
        session, governor, config = _multimodal_session(state)
        return session, governor, config, ""
    except (MultimodalError, ModeError, ModelResolutionError,
            OSError, yaml.YAMLError) as exc:
        # exc carries config paths, mode names, and model ids - never crop
        # bytes, extracted values, or credentials. Logged with the traceback so
        # the defect stays diagnosable instead of being hidden by the fallback.
        logger.exception("multimodal permission panel unavailable")
        return None, None, None, f"{type(exc).__name__}: {exc}"


def _eligible_multimodal_fields(document: dict) -> list[dict]:
    eligible = {
        (row["page"], row["field_name"])
        for row in document.get("provider_escalations", [])
        if row.get("multimodal_eligible")
        and row.get("final_workflow_state") == "HUMAN_REVIEW_REQUIRED"
    }
    return [row for row in workspace.build_review_queue(document)
            if (row["page"], row["field_name"]) in eligible]


def _multimodal_request(source, document: dict, candidate: dict | None, *,
                        synthetic: bool):
    if (source is None or source.role != FileRole.CLAIM_DOCUMENT
            or candidate is None or not candidate.get("bbox")):
        return None
    try:
        pages = decode_pages(source.content, source.source_format)
        page_number = int(candidate["page"])
        page = pages[page_number - 1]
        return request_from_page(
            page, candidate["bbox"], candidate["field_name"],
            doc_id=document["safe_source_id"], page_id=f"p{page_number}",
            synthetic=synthetic)
    except (IndexError, IntakeError, TypeError, ValueError):
        return None


def _replace_multimodal_document(state: dict, document: dict) -> None:
    batch = state["batch_results"]
    batch["documents"] = [
        document if row["safe_source_id"] == document["safe_source_id"] else row
        for row in batch["documents"]
    ]
    _refresh_workspace_batch(state)


def _render_multimodal_permission(st, state: dict, document: dict, source) -> None:
    candidates = _eligible_multimodal_fields(document)
    session, governor, config, init_error = _multimodal_session_or_error(state)
    if init_error:
        st.warning(
            "**Multimodal provider unavailable.**  \n"
            "Reason: configuration initialization failed.  \n"
            "Local OCR, validation, retry, review and exports remain available. "
            "No external call was attempted."
        )
        st.caption(f"Diagnostic: {init_error}")
        return
    receipts = session.setdefault("receipts", {})
    if not candidates and not receipts:
        return
    calls_used = sum(int(row.get("external_calls_made") or 0)
                     for row in receipts.values())
    key_base = document["safe_source_id"]
    enabled = st.toggle(
        "Enable paid multimodal AI calls", value=False,
        key=f"cr_multimodal_enabled_{key_base}")

    if not enabled:
        st.button(
            "Run one eligible synthetic field", disabled=True,
            key=f"cr_multimodal_run_{key_base}")
        st.info("AI calls disabled. No data will leave this machine.")
        _render_multimodal_receipt(st, receipts, calls_used)
        return

    limits = governor.limits
    resolved = governor.resolved
    st.warning("⚠ Paid multimodal AI calls enabled")
    st.markdown(
        f"**Operating mode:** {service.MODE_LABELS.get(resolved.mode, resolved.mode.title())} · "
        f"**Provider:** {governor.provider_name}  \n"
        f"**Model alias:** `{resolved.alias or '—'}` → **Exact runtime model:** "
        f"`{resolved.model_id or 'not configured'}`  \n"
        f"**Image input supported:** {'yes' if resolved.supports_images else 'no'} · "
        f"**Allowlisted:** {'yes' if resolved.allowlisted else 'no'} · "
        f"**Eligible fields:** {len(candidates)} · **Calls:** {calls_used}/"
        f"{multimodal_permission.UI_MAX_CALLS}  \n"
        f"**Session spend:** {_fmt_usd(governor.session_spend_usd)} / "
        f"{_fmt_usd(limits.max_session_spend_usd)} · **Document spend limit:** "
        f"{_fmt_usd(limits.max_document_spend_usd)}  \n"
        f"**Fallback models:** {'allowed' if resolved.fallback_allowed else 'disabled'} · "
        "**Automatic retries:** disabled · **Full-page requests:** blocked  \n"
        "**Organiser/PHI inputs:** blocked · **Input boundary:** synthetic crop only"
    )
    # Surfaced before the consent checkboxes: an operator should learn the model
    # is unusable without first attesting to anything.
    if resolved.blocked_reason:
        st.error(f"Model not usable: {resolved.blocked_reason}")
    synthetic_attested = st.checkbox(
        "I confirm this selected input is synthetic and contains no PHI or organiser data.",
        key=f"cr_multimodal_synthetic_{key_base}")
    confirmed = st.checkbox(
        "I understand that this may make a paid external API call.",
        key=f"cr_multimodal_confirmed_{key_base}")

    candidate = candidates[0] if candidates else None
    request = _multimodal_request(
        source, document, candidate, synthetic=synthetic_attested)
    status = multimodal_permission.permission_status(
        enabled=enabled, confirmed=confirmed,
        synthetic_attested=synthetic_attested, request=request,
        governor=governor, calls_used=calls_used)
    if calls_used >= multimodal_permission.UI_MAX_CALLS:
        st.error("Paid-call limit reached")
    elif not status.can_run:
        st.caption(f"Blocked: {status.reason}")

    run = st.button(
        "Run one eligible synthetic field", type="primary",
        disabled=not status.can_run,
        key=f"cr_multimodal_run_{key_base}")
    if run and request is not None:
        fingerprint = status.policy.fingerprint if status.policy else request.request_id
        if session.get("active_fingerprint") or fingerprint in receipts:
            st.info("This request already has a session receipt. No call was repeated.")
        else:
            session["active_fingerprint"] = fingerprint
            try:
                page_row = next(row for row in document["fields"]
                                if row["page"] == candidate["page"])
                context = {name: field.get("value")
                           for name, field in page_row["fields"].items()}
                receipt, accepted_value = multimodal_permission.run_one_candidate(
                    request, enabled=enabled, confirmed=confirmed,
                    synthetic_attested=synthetic_attested, governor=governor,
                    config=config, calls_used=calls_used, context=context)
                receipts[fingerprint] = receipt
                if receipt.get("called_provider"):
                    updated = workspace.apply_multimodal_candidate(
                        document, page=candidate["page"],
                        field_name=candidate["field_name"], value=accepted_value,
                        receipt=receipt)
                    _replace_multimodal_document(state, updated)
            finally:
                session["active_fingerprint"] = None
            st.rerun()

    _render_multimodal_receipt(st, receipts, calls_used)


def _render_multimodal_receipt(st, receipts: dict, calls_used: int) -> None:
    if not receipts:
        return
    receipt = list(receipts.values())[-1]
    st.markdown("#### Paid multimodal receipt")
    st.dataframe([{
        "Calls used": calls_used,
        "Measured cost": _fmt_usd(receipt.get("measured_cost_usd") or 0),
        "Latency": f"{float(receipt.get('latency_ms') or 0) / 1000:.2f} s",
        "Final field outcome": receipt.get("final_field_outcome"),
    }], hide_index=True, width="stretch")


def _style(st) -> None:
    st.markdown(
        """
        <style>
        :root {
          --cr-bg: oklch(0.975 0.004 250);
          --cr-surface: oklch(1 0 0);
          --cr-surface-strong: oklch(0.955 0.010 250);
          --cr-line: oklch(0.905 0.012 250);
          --cr-ink: oklch(0.245 0.030 258);
          --cr-muted: oklch(0.520 0.025 258);
          --cr-primary: oklch(0.455 0.105 188);
          --cr-primary-soft: oklch(0.940 0.030 188);
          --cr-navy: oklch(0.235 0.055 264);
          --cr-navy-deep: oklch(0.195 0.055 264);
          --cr-navy-ink: oklch(0.965 0.010 250);
          --cr-navy-muted: oklch(0.760 0.030 255);
          --cr-ok: oklch(0.560 0.130 155);
          --cr-warn: oklch(0.660 0.140 75);
          --cr-err: oklch(0.560 0.170 25);
          --cr-info: oklch(0.545 0.135 255);
          --cr-radius: 14px;
          --cr-shadow: 0 1px 2px oklch(0.245 0.030 258 / .06),
                       0 8px 24px oklch(0.245 0.030 258 / .05);
        }
        .stApp { background: var(--cr-bg); color: var(--cr-ink); }
        .block-container { padding-top: 2.2rem; }

        /* Dark navy rail. Every control on it is a real control. */
        [data-testid="stSidebar"] {
          background: var(--cr-navy);
          border-right: 1px solid var(--cr-navy-deep);
        }
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
          padding-top: 1.35rem;
        }
        [data-testid="stSidebar"] * { color: var(--cr-navy-ink); }
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] label { color: var(--cr-navy-muted); }
        [data-testid="stSidebar"] hr { border-color: oklch(1 0 0 / .12); }
        [data-testid="stSidebar"] [data-testid="stMetricValue"] {
          font-size: 1.35rem; color: var(--cr-navy-ink);
        }
        [data-testid="stSidebar"] .stButton button {
          background: oklch(1 0 0 / .10); border: 1px solid oklch(1 0 0 / .22);
        }
        [data-testid="stSidebar"] .stButton button:hover:not(:disabled) {
          background: oklch(1 0 0 / .18);
        }
        .cr-rail-status {
          display: flex; align-items: center; gap: .5rem; padding: .5rem .65rem;
          border-radius: 10px; background: oklch(1 0 0 / .08);
          border: 1px solid oklch(1 0 0 / .14);
          font-size: .82rem; font-weight: 650; margin-bottom: .35rem;
        }
        .cr-rail-status i {
          width: .55rem; height: .55rem; border-radius: 50%; flex: 0 0 auto;
        }
        .cr-rail-status.ok i { background: var(--cr-ok); }
        .cr-rail-status.warn i { background: var(--cr-warn); }
        .cr-rail-status.info i { background: var(--cr-info); }
        h1, h2, h3 { color: var(--cr-ink); letter-spacing: -0.02em; text-wrap: balance; }
        p, label, [data-testid="stCaptionContainer"] { color: var(--cr-muted); }
        .cr-header { max-width: 68ch; margin-bottom: 1.2rem; }
        .cr-header h1 { font-size: 2.45rem; line-height: 1.05; margin: 0 0 .7rem; }
        .cr-header p { font-size: 1rem; line-height: 1.55; margin: 0; }
        .cr-app-header {
          display: flex; align-items: center; justify-content: space-between;
          gap: 1.5rem; padding: .25rem 0 1.15rem; margin-bottom: 1.4rem;
          border-bottom: 1px solid var(--cr-line);
        }
        .cr-app-header h1 { font-size: 2rem; line-height: 1.1; margin: 0 0 .3rem; }
        .cr-app-header p { font-size: .95rem; line-height: 1.4; margin: 0; }
        .cr-mode {
          flex: 0 0 auto; padding: .5rem .75rem; border-radius: 8px;
          background: var(--cr-primary-soft); color: var(--cr-ink);
          font-size: .82rem; font-weight: 750;
        }
        .cr-section-intro { max-width: 68ch; margin: -.35rem 0 1.2rem; }
        .cr-sidebar-brand { margin-bottom: 1rem; }
        .cr-sidebar-brand strong { color: var(--cr-ink); font-size: 1.08rem; }
        .cr-sidebar-brand span { color: var(--cr-muted); font-size: .78rem; }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
          gap: .35rem; border-bottom: 1px solid var(--cr-line);
        }
        [data-testid="stTabs"] [data-baseweb="tab"] {
          min-height: 2.8rem; padding: .55rem .8rem; border-radius: 8px 8px 0 0;
          font-weight: 700;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
          background: var(--cr-primary-soft); color: var(--cr-ink);
        }
        .cr-pipeline {
          padding: .9rem 1rem; border-radius: 12px; background: var(--cr-primary-soft);
          color: var(--cr-ink); font-weight: 650; line-height: 1.8;
        }
        .cr-basis {
          display: inline-block; padding: .14rem .48rem; border-radius: 999px;
          background: var(--cr-primary); color: oklch(0.99 0 0);
          font-size: .72rem; font-weight: 750; letter-spacing: .03em;
        }
        .stButton button, .stDownloadButton button { border-radius: 8px; font-weight: 700; }
        .stButton button[kind="primary"] {
          background: var(--cr-primary) !important;
          border-color: var(--cr-primary) !important;
        }
        .stButton button[kind="primary"] p { color: oklch(0.99 0 0) !important; }
        label[data-baseweb="radio"]:has(input:checked) > div:first-child,
        label[data-baseweb="checkbox"]:has(input:checked) > div:first-child {
          background-color: var(--cr-primary) !important;
          border-color: var(--cr-primary) !important;
        }
        div[data-testid="stMetric"] {
          padding: .8rem .9rem; background: var(--cr-surface);
          border: 1px solid var(--cr-line); border-radius: var(--cr-radius);
          box-shadow: var(--cr-shadow);
        }
        [data-testid="stSidebar"] div[data-testid="stMetric"] {
          background: oklch(1 0 0 / .08); border-color: oklch(1 0 0 / .14);
          box-shadow: none;
        }
        [data-testid="stDataFrame"] {
          border: 1px solid var(--cr-line); border-radius: var(--cr-radius);
          overflow: hidden; box-shadow: var(--cr-shadow);
        }
        [data-testid="stExpander"] details {
          border: 1px solid var(--cr-line); border-radius: var(--cr-radius);
          background: var(--cr-surface);
        }

        /* ---- dashboard ---- */
        .cr-dash-head {
          display: flex; flex-wrap: wrap; align-items: flex-start;
          justify-content: space-between; gap: 1rem; margin: .2rem 0 1.1rem;
        }
        .cr-dash-head h2 { font-size: 1.55rem; margin: 0 0 .25rem; }
        .cr-dash-head p { margin: 0; font-size: .92rem; }
        .cr-chips { display: flex; flex-wrap: wrap; gap: .4rem; }
        .cr-chip {
          display: inline-flex; align-items: baseline; gap: .35rem;
          padding: .34rem .62rem; border-radius: 999px;
          background: var(--cr-surface); border: 1px solid var(--cr-line);
          font-size: .78rem; font-weight: 700; color: var(--cr-ink);
          box-shadow: var(--cr-shadow);
        }
        .cr-chip em {
          font-style: normal; font-weight: 600; color: var(--cr-muted);
          font-size: .72rem; text-transform: uppercase; letter-spacing: .04em;
        }
        .cr-chip-ok { border-color: oklch(0.560 0.130 155 / .45); }
        .cr-chip-warn { border-color: oklch(0.660 0.140 75 / .5); }
        .cr-grid { display: grid; gap: .7rem; margin-bottom: 1.1rem; }
        .cr-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .cr-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        .cr-card {
          background: var(--cr-surface); border: 1px solid var(--cr-line);
          border-radius: var(--cr-radius); box-shadow: var(--cr-shadow);
          padding: .85rem .95rem;
        }
        .cr-kpi { display: flex; flex-direction: column; gap: .18rem; }
        .cr-kpi-label {
          font-size: .78rem; font-weight: 700; color: var(--cr-muted);
          text-transform: uppercase; letter-spacing: .04em;
        }
        .cr-kpi-value {
          font-size: 1.75rem; line-height: 1.1; font-weight: 780;
          letter-spacing: -0.02em; color: var(--cr-ink);
        }
        .cr-kpi-detail { font-size: .8rem; color: var(--cr-muted); line-height: 1.35; }
        .cr-kpi .cr-basis { align-self: flex-start; margin-top: .35rem; }
        .cr-funnel {
          display: flex; flex-wrap: wrap; align-items: stretch; gap: .4rem;
          margin-bottom: .8rem;
        }
        .cr-step {
          flex: 1 1 140px; background: var(--cr-surface);
          border: 1px solid var(--cr-line); border-radius: var(--cr-radius);
          padding: .7rem .75rem; box-shadow: var(--cr-shadow);
        }
        .cr-step-name {
          display: block; font-size: .74rem; font-weight: 700;
          text-transform: uppercase; letter-spacing: .04em; color: var(--cr-muted);
        }
        .cr-step-value {
          display: block; font-size: 1.35rem; font-weight: 760; color: var(--cr-ink);
          line-height: 1.2;
        }
        .cr-step-unit { display: block; font-size: .76rem; color: var(--cr-muted); }
        .cr-step-doc { background: var(--cr-primary-soft); }
        .cr-bar-row {
          display: grid; grid-template-columns: minmax(0, 12rem) 1fr auto;
          align-items: center; gap: .7rem; padding: .3rem 0;
          font-size: .85rem; color: var(--cr-ink);
        }
        .cr-bar-track {
          height: .55rem; border-radius: 999px; background: var(--cr-surface-strong);
          overflow: hidden;
        }
        .cr-bar-fill { display: block; height: 100%; background: var(--cr-primary); }
        .cr-bar-value { font-variant-numeric: tabular-nums; color: var(--cr-muted); }
        .cr-health { display: flex; flex-direction: column; gap: .3rem; }
        .cr-health-row {
          display: flex; align-items: center; gap: .6rem; padding: .5rem .7rem;
          background: var(--cr-surface); border: 1px solid var(--cr-line);
          border-radius: 10px; font-size: .85rem;
        }
        .cr-health-row i {
          width: .55rem; height: .55rem; border-radius: 50%; flex: 0 0 auto;
        }
        .cr-health-row .cr-state { margin-left: auto; font-weight: 700; }
        .cr-health-row .cr-detail {
          color: var(--cr-muted); font-size: .78rem;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .cr-state-ok i, .cr-state-ok .cr-state { color: var(--cr-ok); }
        .cr-state-ok i { background: var(--cr-ok); }
        .cr-state-info i { background: var(--cr-info); }
        .cr-state-info .cr-state { color: var(--cr-info); }
        .cr-state-warn i { background: var(--cr-warn); }
        .cr-state-warn .cr-state { color: var(--cr-warn); }
        .cr-state-err i { background: var(--cr-err); }
        .cr-state-err .cr-state { color: var(--cr-err); }
        .cr-empty {
          padding: 1.1rem; border: 1px dashed var(--cr-line);
          border-radius: var(--cr-radius); color: var(--cr-muted);
          background: var(--cr-surface); font-size: .88rem;
        }
        .cr-note { font-size: .8rem; color: var(--cr-muted); line-height: 1.5; }

        @media (max-width: 1100px) {
          .cr-grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 900px) {
          .cr-grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 767px) {
          .cr-app-header { align-items: flex-start; flex-direction: column; gap: .75rem; }
          .cr-app-header h1 { font-size: 1.7rem; }
          .cr-grid-3, .cr-grid-4 { grid-template-columns: minmax(0, 1fr); }
          .cr-bar-row { grid-template-columns: minmax(0, 1fr) auto; }
          .cr-bar-track { grid-column: 1 / -1; }
        }
        @media (prefers-reduced-motion: reduce) {
          * { scroll-behavior: auto !important; transition: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _document_controls(st):
    st.sidebar.header("Run a claim")
    source_label = st.sidebar.radio(
        "Document source", ["Bundled synthetic example", "Upload local document"],
        help="Bundled examples contain no PHI. Uploads never use an external provider.")
    mode = st.sidebar.selectbox(
        "Operating mode", list(service.MODE_LABELS),
        index=list(service.MODE_LABELS).index(service.DEFAULT_MODE),
        format_func=service.MODE_LABELS.get,
    )
    st.sidebar.caption("Balanced is the calibrated hackathon default.")

    if source_label == "Bundled synthetic example":
        examples = service.list_synthetic_examples()
        if not examples:
            st.error("No generated synthetic examples are available. Generate the dataset first.")
            return None
        selected = st.sidebar.selectbox(
            "Safe demo file", examples,
            format_func=lambda item: item["label"])
        document = service.load_synthetic(selected)
        return document, selected["doc_id"], selected["tier"], mode, "bundled_synthetic"

    st.sidebar.warning("Synthetic files only. Do not upload real claims or PHI.")
    synthetic_confirmed = st.sidebar.checkbox(
        "I confirm this is synthetic and contains no PHI")
    uploaded = st.sidebar.file_uploader(
        "Synthetic claim image", type=["png", "jpg", "jpeg", "tif", "tiff"],
        help="Synthetic PNG, JPEG, or single-page TIFF. Maximum 10 MB and 1 page.",
        disabled=not synthetic_confirmed)
    if uploaded is None:
        return None
    try:
        document = service.inspect_upload(
            uploaded.name, uploaded.getvalue(), synthetic_confirmed=synthetic_confirmed)
    except service.UploadValidationError as exc:
        st.error(str(exc))
        return None
    return document, f"upload-{document.sha256[:12]}", "clean", mode, "upload"


def _render_document_summary(st, document, receipt, source_kind, mode):
    values = [
        ("File type", document.file_format),
        ("File size", f"{document.size_bytes / 1024:,.1f} KB"),
        ("Pages", document.page_count),
        ("Document type", receipt["document"]["document_type"] if receipt else "Detected on run"),
        ("Mode", service.MODE_LABELS[mode]),
        ("Processing", "Local only" if source_kind == "upload" else "Local offline oracle"),
    ]
    for start in (0, 3):
        for column, (label, value) in zip(st.columns(3), values[start:start + 3]):
            column.metric(label, value)


def _render_funnel(st, receipt):
    st.subheader("Resolution funnel")
    columns = st.columns(len(receipt["funnel"]))
    labels = {
        "fields_detected": "Detected", "accepted_locally": "Local accept",
        "accepted_with_flag": "Flagged", "locally_retried": "Retried",
        "escalated": "Escalated", "human_review": "Human review",
        "api_calls_avoided": "API calls avoided",
    }
    for column, (key, value) in zip(columns, receipt["funnel"].items()):
        column.metric(labels[key], value)


def _render_results(st, receipt, image, screenshot_safe):
    _render_funnel(st, receipt)
    rows = []
    for field in receipt["fields"]:
        rows.append({
            "Field": field["field_name"],
            "Final value": _shown(field["final_value"], screenshot_safe),
            "Confidence": field["confidence"],
            "Criticality": field["criticality"],
            "Source": field["source_engine"],
            "Status": field["status"],
            "Validation": field["validation_status"],
            "Retries": field["retry_count"],
            "Escalated": field["escalated"],
            "Latency ms": field["latency_ms"],
            "Measured cost": field["measured_cost_usd"],
            "Projected cost": field["projected_cost_usd"],
        })
    st.dataframe(rows, hide_index=True, width="stretch")
    if screenshot_safe:
        st.info("Screenshot-safe mode hides field values and the document image.")
    else:
        st.image(service.draw_overlay(image, receipt["fields"]),
                 caption="Field routing overlay", width="stretch")
    left, right = st.columns(2)
    left.download_button(
        "Download final JSON", service.export_json(receipt, audit=False),
        file_name=f"{receipt['document']['document_id']}-final.json",
        mime="application/json", width="stretch")
    right.download_button(
        "Download audit JSON", service.export_json(receipt, audit=True),
        file_name=f"{receipt['document']['document_id']}-audit.json",
        mime="application/json", width="stretch")


def _render_evidence(st, receipt, image, screenshot_safe):
    field_names = [field["field_name"] for field in receipt["fields"]]
    selected_name = st.selectbox("Inspect field evidence", field_names)
    field = next(row for row in receipt["fields"] if row["field_name"] == selected_name)
    left, right = st.columns([1, 1.35])
    with left:
        crop = service.crop_field(image, field["bbox"])
        if screenshot_safe:
            st.info("Crop hidden in screenshot-safe mode.")
        elif crop:
            st.image(crop, caption=f"Original crop: {selected_name}", width="stretch")
        st.metric("Final confidence", f"{field['confidence']:.2%}")
        st.write(f"**Status:** {field['status']}")
        st.write(f"**Final value:** {_shown(field['final_value'], screenshot_safe)}")
    with right:
        st.subheader("Candidates")
        st.dataframe([
            {"Rung": "Primary OCR", "Value": _shown(field["primary_candidate"], screenshot_safe)},
            {"Rung": "Local retry", "Value": _shown(field["retry_candidate"], screenshot_safe)},
            {"Rung": "Selective escalation", "Value": _shown(field["escalation_candidate"], screenshot_safe)},
        ], hide_index=True, width="stretch")
        st.subheader("Validator verdicts")
        st.dataframe(field["validation"], hide_index=True, width="stretch")
        st.subheader("Processing path")
        path = [{**item, "value": _shown(item["value"], screenshot_safe)}
                for item in field["processing_path"]]
        st.dataframe(path, hide_index=True, width="stretch")
        st.subheader("Governor decisions")
        st.dataframe(field["governor_decisions"], hide_index=True, width="stretch")


def _render_costs(st, receipt):
    st.subheader("Cost and performance")
    costs = receipt["costs"]
    columns = st.columns(5)
    metrics = [
        ("Local compute", costs["local_compute"]),
        ("Projected API", costs["api"]),
        ("Measured API", costs["measured_api"]),
        ("Measured automated", costs["measured_total_automated"]),
        ("Projected automated", costs["projected_total_automated"]),
    ]
    for column, (label, cost) in zip(columns, metrics):
        column.metric(label, _fmt_usd(cost["value_usd"]), help=cost["basis"])
        column.markdown(f'<span class="cr-basis">{cost["basis"]}</span>', unsafe_allow_html=True)
    st.metric("Processing latency", f"{receipt['latency_ms'] / 1000:.2f} s")
    usage = receipt["usage"]
    if usage["input_tokens"] or usage["output_tokens"]:
        st.caption(f"Recorded usage: {usage['input_tokens']:,} input tokens, "
                   f"{usage['output_tokens']:,} output tokens")
    else:
        st.caption("No real provider token usage was recorded.")
    st.subheader("Projected automated cost at scale")
    st.dataframe([
        {"Pages": f"{int(pages):,}", "Projected cost": f"${cost:,.4f}", "Basis": "PROJECTED"}
        for pages, cost in receipt["projections"].items()
    ], hide_index=True, width="stretch")


def _render_modes(st):
    summary = service.load_calibration_summary()
    rows = []
    for key in ("economy", "balanced", "accuracy"):
        metrics = summary["modes"][key]["metrics"]
        rows.append({
            "Mode": service.MODE_LABELS[key],
            "Accuracy": _fmt_pct(metrics["field_accuracy"]),
            "Critical accuracy": _fmt_pct(metrics["critical_field_accuracy"]),
            "Escalation": _fmt_pct(metrics["escalation_rate"]),
            "Human review": _fmt_pct(metrics["human_review_rate"]),
            "Projected cost/page": _fmt_usd(metrics["projected_total_automated_cost_per_page_usd"]),
            "Basis": "PROJECTED",
        })
    st.subheader("Day 9 operating modes")
    st.dataframe(rows, hide_index=True, width="stretch")
    st.success("Balanced is the recommended hackathon default.")
    st.info("Strict Accuracy prioritizes verified correctness and permits fewer flagged "
            "acceptances. This can increase human review.")
    st.caption("Thresholds are CONFIGURED ASSUMPTIONS from replay calibration. Runtime "
               "governor presets remain architecture v1.2.")


def _render_benchmark(st):
    benchmark = service.load_benchmark_summary()
    calibration = service.load_calibration_summary()
    st.warning("Final frozen synthetic benchmark with offline-oracle projection. "
               "Not evidence on official or real claims.")
    rows = []
    for tier in ("clean", "noisy", "ugly", "blended"):
        metrics = benchmark["blended"] if tier == "blended" else benchmark["per_tier"][tier]
        rows.append({
            "Tier": tier.title(),
            "Accuracy": _fmt_pct(metrics["field_accuracy"]),
            "Critical accuracy": _fmt_pct(metrics["critical_field_accuracy"]),
            "Escalation": _fmt_pct(metrics["escalation_rate"]),
            "Human review": _fmt_pct(metrics["human_review_rate"]),
            "Projected cost/page": _fmt_usd(metrics["projected_total_automated_cost_per_page_usd"]),
        })
    st.dataframe(rows, hide_index=True, width="stretch")
    st.subheader("Accuracy-cost frontier")
    frontier = calibration["accuracy_cost_frontier"]
    st.scatter_chart(frontier, x="projected_total_automated_cost_per_page_usd",
                     y="field_accuracy", size="escalation_rate")
    st.caption(calibration["evidence_boundary"])


def _inventory_rows(items):
    return [{
        "Filename": item.filename,
        "Role": item.role.value,
        "Format": item.source_format,
        "Pages": item.page_count,
        "Status": item.status,
        "Group": item.group_key,
        "Warning": item.warning,
    } for item in items]


def _uploaded_items(uploaded_files, max_pages):
    return [inspect_content(
        uploaded.name, uploaded.getvalue(), max_pages=max_pages,
    ) for uploaded in (uploaded_files or [])]


def _scan_summary_rows(scan: dict) -> list[dict]:
    labels = {
        "files_discovered": "Files discovered",
        "files_scanned": "Files inspected",
        "supported_files": "Supported files",
        "unsupported_files": "Unsupported files",
        "claim_documents": "Claim documents",
        "expected_output_files": "Expected-output files",
        "specifications": "Specifications",
        "duplicate_files": "Duplicate files",
    }
    return [{"Metric": label, "Value": int(scan.get(key) or 0)}
            for key, label in labels.items()]


def _render_scan_state(st, scan: dict | None) -> None:
    if not scan:
        st.caption(f"Scan state: {ScanState.IDLE.value}")
        return
    state = scan.get("state", ScanState.IDLE.value)
    message = f"Scan state: {state} Â· elapsed {float(scan.get('elapsed_seconds') or 0):.2f}s"
    if state == ScanState.SCAN_FAILED.value:
        st.error(f"{message} Â· {scan.get('error_reason') or 'Unknown scan error'}")
    elif state == ScanState.READY.value:
        st.success(message)
    else:
        st.info(message)
    if scan.get("current_file"):
        st.caption(f"Current file: {scan['current_file']}")
    st.dataframe(_scan_summary_rows(scan), hide_index=True, width="stretch")


def _render_coverage(st, result: dict) -> None:
    coverage = result.get("coverage") or workspace.coverage_metrics(result)
    st.markdown("#### Accuracy dashboard")
    if not coverage.get("available"):
        st.info(coverage.get("message") or
                "Coverage unavailable — document schema not established")
        return
    values = [
        ("Schema fields", coverage["schema_fields"]),
        ("Applicable", coverage["applicable_fields"]),
        ("Inapplicable", coverage["inapplicable_fields"]),
        ("Fields produced", coverage["fields_produced"]),
        ("Validated", coverage["validated_fields"]),
        ("Unresolved", coverage["unresolved_fields"]),
    ]
    for column, (label, value) in zip(st.columns(6), values):
        column.metric(label, value)
    st.info(coverage["message"])
    extraction = coverage.get("extraction_coverage")
    validated = coverage.get("validated_coverage")
    st.caption(
        "Extraction coverage = produced/applicable; validated coverage = validated "
        "resolved/applicable. These are not accuracy metrics."
    )
    left, right = st.columns(2)
    left.metric("Extraction coverage", _fmt_pct(extraction) if extraction is not None else "N/A")
    right.metric("Validated coverage", _fmt_pct(validated) if validated is not None else "N/A")
    st.dataframe([{
        "Critical fields": coverage.get("critical_fields", 0),
        "Critical resolved": coverage.get("critical_fields_resolved", 0),
        "Critical resolution": _fmt_pct_or_unavailable(
            coverage.get("critical_fields_resolution_rate")),
        "Primary OCR resolution": _fmt_pct_or_unavailable(
            coverage.get("primary_ocr_resolution_rate")),
        "Retry resolution": _fmt_pct_or_unavailable(coverage.get("retry_resolution_rate")),
        "Multimodal resolution": _fmt_pct_or_unavailable(
            coverage.get("multimodal_resolution_rate")),
        "Human-review rate": _fmt_pct_or_unavailable(coverage.get("human_review_rate")),
    }], hide_index=True, width="stretch")
    st.markdown("##### Confidence distribution")
    st.bar_chart([{"Band": band.title(), "Fields": count}
                  for band, count in coverage["confidence_distribution"].items()],
                 x="Band", y="Fields")


_HEALTH_TONES = {
    "Healthy": "ok", "Available": "ok", "Disabled by policy": "info",
    "Not configured": "info", "Warning": "warn", "Unavailable": "err",
}

DASHBOARD_EMPTY_STATE = "No documents have been processed in this session yet."


def _card_value(card: dict) -> str:
    if card["kind"] == "percent":
        return _fmt_pct_or_unavailable(card["value"])
    if card["kind"] == "usd":
        return _fmt_usd(card["value"])
    return f"{int(card['value'] or 0):,}"


def _provider_value(row: dict) -> str:
    value = row["value"]
    if row["kind"] == "bool":
        return _yes_no(value)
    if isinstance(value, str):
        return value
    if row["kind"] == "usd":
        return _fmt_usd(value)
    if row["kind"] == "seconds":
        return f"{float(value):.3f} s"
    return f"{int(value):,}"


def _chip(label: str, value: str, tone: str = "neutral") -> str:
    return f'<span class="cr-chip cr-chip-{tone}"><em>{label}</em>{value}</span>'


def _open_document_in_results(session_state, state: dict, source_id: str) -> None:
    """Dashboard rows stay selectable by handing the id to the Results tab."""
    state["selected_result_id"] = source_id
    session_state["cr_result_document"] = source_id
    _activate_workspace_tab(session_state, "Results")


def _render_dashboard_header(st, state: dict, provider_state: dict,
                             batch: dict | None) -> None:
    mode = state["operating_mode"]
    provider_tone = "warn" if provider_state.get("provider_enabled") else "ok"
    provider_value = ("Enabled - governed" if provider_state.get("provider_enabled")
                      else "Disabled by policy")
    chips = [
        _chip("Operating mode", service.MODE_LABELS.get(mode, mode.title())),
        _chip("Environment", dashboard.environment_label(app_mode())),
        _chip("External provider", provider_value, provider_tone),
        _chip("Session", batch["batch_job_id"] if batch else "No batch yet"),
    ]
    st.markdown(
        '<div class="cr-dash-head"><div><h2>Dashboard</h2>'
        '<p>Real-time overview of document processing, accuracy, and cost</p></div>'
        f'<div class="cr-chips">{"".join(chips)}</div></div>',
        unsafe_allow_html=True)


def _render_dashboard_summary(st, summary: dict) -> None:
    cards = "".join(
        '<div class="cr-card cr-kpi">'
        f'<span class="cr-kpi-label">{card["label"]}</span>'
        f'<strong class="cr-kpi-value">{_card_value(card)}</strong>'
        f'<span class="cr-kpi-detail">{card["detail"]}</span>'
        f'<span class="cr-basis">{card["basis"]}</span></div>'
        for card in dashboard.summary_cards(summary))
    st.markdown(f'<div class="cr-grid cr-grid-3">{cards}</div>',
                unsafe_allow_html=True)


def _render_dashboard_funnel(st, summary: dict, cost_dashboard: dict) -> None:
    st.markdown("#### Processing overview")
    steps = "".join(
        f'<div class="cr-step{" cr-step-doc" if step["unit"] == "documents" else ""}">'
        f'<span class="cr-step-name">{step["stage"]}</span>'
        f'<span class="cr-step-value">{step["value"]:,}'
        + (f' <small>/ {step["denominator"]:,}</small>'
           if step["denominator"] else "")
        + f'</span><span class="cr-step-unit">{step["unit"]} - {step["detail"]}'
        '</span></div>'
        for step in dashboard.funnel_stages(summary, cost_dashboard))
    st.markdown(f'<div class="cr-funnel">{steps}</div>', unsafe_allow_html=True)
    st.caption("Document counts and field counts are separate units and never "
               "share a denominator.")
    progress = dashboard.coverage_progress(summary)
    if progress["value"] is None:
        st.caption(progress["caption"])
    else:
        st.progress(progress["value"],
                    text=f'{progress["label"]}: {_fmt_pct(progress["value"])} - '
                         f'{progress["caption"]}')


def _render_dashboard_cost(st, cost_dashboard: dict) -> None:
    st.markdown("#### Cost breakdown")
    rows = dashboard.cost_breakdown_rows(cost_dashboard)
    st.dataframe([{
        "Component": row["label"],
        "Cost USD": _fmt_usd(row["value_usd"]),
        "Evidence": row["basis"],
        "Type": row["group"].upper(),
    } for row in rows], hide_index=True, width="stretch")
    st.caption(
        f'Measured automated total {_fmt_usd(dashboard.measured_total(cost_dashboard))}. '
        "The five MEASURED rows sum to that total. PROJECTED and ASSUMED rows are "
        "not spend and are never added to it.")


def _render_dashboard_documents(st, state: dict, documents: list[dict]) -> None:
    st.markdown("#### Documents in this session")
    rows = dashboard.recent_document_rows(documents)
    if not rows:
        st.markdown(f'<div class="cr-empty">{DASHBOARD_EMPTY_STATE}</div>',
                    unsafe_allow_html=True)
        return
    st.dataframe([{
        "Document": row["Document"],
        "Type": row["Type"],
        "Pages": row["Pages"],
        "Status": row["Status"],
        "Stage": row["Stage"],
        "Validated coverage": _fmt_pct_or_unavailable(row["Validated coverage"]),
        "Unresolved": row["Unresolved"],
        "Total cost": _fmt_usd(row["Total cost"]),
        "Processing time": f'{row["Processing time"]:.2f} s',
    } for row in rows], hide_index=True, width="stretch")
    labels = {row["safe_source_id"]: row["Document"] for row in rows}
    selected = st.selectbox(
        "Open a document", list(labels), format_func=labels.get,
        key="cr_dashboard_document")
    st.button("Open selected document in Results", width="stretch",
              on_click=_open_document_in_results,
              args=(st.session_state, state, selected))


def _render_dashboard_escalations(st, summary: dict) -> None:
    st.markdown("#### Escalations by field")
    rows = dashboard.escalations_by_field(summary)
    if not rows:
        st.markdown(f'<div class="cr-empty">{dashboard.ESCALATIONS_EMPTY_STATE}</div>',
                    unsafe_allow_html=True)
        return
    bars = "".join(
        f'<div class="cr-bar-row"><span>{row["field_name"].replace("_", " ").title()}'
        f'</span><span class="cr-bar-track"><span class="cr-bar-fill" '
        f'style="width:{row["share"] * 100:.1f}%"></span></span>'
        f'<span class="cr-bar-value">{row["count"]} - {row["share"]:.1%}</span></div>'
        for row in rows)
    st.markdown(bars, unsafe_allow_html=True)
    st.caption(f"Share is of the {sum(row['count'] for row in rows)} unresolved "
               "fields this run recorded.")


def _render_dashboard_provider(st, state: dict, provider_state: dict) -> None:
    st.markdown("#### Provider and model")
    session = state.get("multimodal") or {}
    receipts = list((session.get("receipts") or {}).values())
    calls_used = sum(int(row.get("external_calls_made") or 0) for row in receipts)
    called = [row for row in receipts if row.get("called_provider")]
    usage = called[-1].get("usage") if called else None
    latency = called[-1].get("latency_ms") if called else None
    governor = session.get("governor")
    rows = dashboard.provider_panel_rows(
        provider_state,
        session_report=governor.session_report() if governor is not None else None,
        calls_used=calls_used, usage=usage, latency_ms=latency)
    st.dataframe([{"Property": row["label"], "Value": _provider_value(row)}
                  for row in rows], hide_index=True, width="stretch")
    st.caption(dashboard.provider_panel_note(calls_used=calls_used))


def _render_dashboard_projection(st, cost_dashboard: dict) -> None:
    st.markdown("#### Cost projection")
    rows = dashboard.projection_rows(cost_dashboard)
    st.dataframe([{
        "Volume": row["scale"],
        "Automated": _fmt_cost({"value_usd": row["automated_usd"]}),
        "Automated basis": row["automated_basis"],
        "Human review": _fmt_cost({"value_usd": row["human_review_usd"]}),
        "Human review basis": row["human_review_basis"],
        "Total estimate": _fmt_cost({"value_usd": row["total_usd"]}),
        "Total basis": row["total_basis"],
    } for row in rows], hide_index=True, width="stretch")
    st.caption(dashboard.PROJECTION_ASSUMPTION)


def _render_dashboard_health(st, provider_state: dict, workspace_ready: bool) -> None:
    st.markdown("#### System health")
    probe = dashboard.probe_runtime()
    rows = dashboard.system_health(
        ocr_binary=probe["ocr_binary"], validator_fields=probe["validator_fields"],
        provider_state=provider_state, workspace_ready=workspace_ready)
    st.markdown(
        '<div class="cr-health">' + "".join(
            f'<div class="cr-health-row cr-state-{_HEALTH_TONES[row["state"]]}"><i></i>'
            f'<span>{row["component"]}</span>'
            f'<span class="cr-detail">{row["detail"]}</span>'
            f'<span class="cr-state">{row["state"]}</span></div>'
            for row in rows) + "</div>",
        unsafe_allow_html=True)
    st.caption("Only components this process can verify are listed. Hosted "
               "databases, queue workers, and a managed provider gateway are "
               "roadmap infrastructure and are not claimed here.")


def _render_judge_dashboard(st, state: dict) -> None:
    """The judge-facing landing view. Every value comes from this session."""
    batch = state.get("batch_results")
    provider_state = workspace._provider_policy_snapshot()
    _render_dashboard_header(st, state, provider_state, batch)
    if not batch:
        st.markdown(f'<div class="cr-empty">{DASHBOARD_EMPTY_STATE} Add authorized '
                    'local files in Intake &amp; Run; every card below fills from '
                    'the batch receipt.</div>', unsafe_allow_html=True)
        _render_dashboard_escalations(st, {})
        _render_dashboard_provider(st, state, provider_state)
        _render_dashboard_health(st, provider_state, workspace_ready=bool(state))
        return
    summary = batch["summary"]
    cost_dashboard = summary["cost_dashboard"]
    _render_dashboard_summary(st, summary)
    _render_dashboard_funnel(st, summary, cost_dashboard)
    left, right = st.columns([1.45, 1])
    with left:
        _render_dashboard_cost(st, cost_dashboard)
        _render_dashboard_documents(st, state, batch["documents"])
    with right:
        _render_dashboard_escalations(st, summary)
        _render_dashboard_provider(st, state, provider_state)
    _render_dashboard_projection(st, cost_dashboard)
    _render_dashboard_health(st, provider_state, workspace_ready=True)


def _render_dashboard(st, batch: dict) -> None:
    summary = batch["summary"]
    st.subheader("Batch overview")
    current_stage = next((row.get("processing_stage") for row in batch["documents"]
                          if row.get("processing_stage") not in {"COMPLETED"}), "COMPLETED")
    cards = [
        ("Documents", summary.get("files", 0)), ("Pages", summary.get("pages", 0)),
        ("Current stage", current_stage), ("Completed", summary.get("success", 0)),
        ("Partial", summary.get("partial", 0)),
        ("Failed", int(summary.get("failed", 0)) + int(summary.get("failed_extraction", 0))),
        ("Applicable fields", summary.get("applicable_fields", 0)),
        ("Fields produced", summary.get("fields_produced", 0)),
        ("Validated fields", summary.get("validated_fields", 0)),
        ("Unresolved", summary.get("unresolved_fields", 0)),
        ("Retry attempted", summary.get("retry_attempted", 0)),
        ("Retry resolved", summary.get("retry_resolved", 0)),
        ("Multimodal pending", summary.get("pending_multimodal", 0)),
        ("Multimodal attempted", summary.get("multimodal_attempted", 0)),
        ("Multimodal resolved", max(0, int(summary.get("multimodal_attempted") or 0)
                                     - int(summary.get("multimodal_failed") or 0))),
        ("Human review required", summary.get("human_review_required", 0)),
        ("Human review completed", summary.get("human_review_completed", 0)),
        ("External calls", summary.get("external_calls", 0)),
        ("Measured cost", _fmt_usd(summary.get("measured_cost_usd") or 0)),
        ("Projected cost", _fmt_usd(summary.get("projected_cost_usd") or 0)),
        ("Mean latency", f"{float(summary.get('mean_latency_ms') or 0) / 1000:.2f}s"),
        ("Throughput", f"{float(summary.get('throughput_pages_per_minute') or 0):.2f} pages/min"),
    ]
    for start in range(0, len(cards), 6):
        for column, (label, value) in zip(st.columns(6), cards[start:start + 6]):
            column.metric(label, value)
    st.markdown("#### Routing funnel")
    st.dataframe([{
        "Applicable fields": int(summary.get("applicable_fields") or 0),
        "Primary OCR resolved": int(summary.get("primary_resolved") or 0),
        "Retry resolved": int(summary.get("retry_resolved") or 0),
        "Multimodal resolved": max(0, int(summary.get("multimodal_attempted") or 0)
                                    - int(summary.get("multimodal_failed") or 0)),
        "Human corrected": int(summary.get("human_review_completed") or 0),
        "Remaining unresolved": int(summary.get("unresolved_fields") or 0),
    }], hide_index=True, width="stretch")
    st.markdown("#### Document status")
    st.dataframe([{
        "Document": row["source_file"],
        "Detected type": row["document_type"],
        "Stage": row.get("processing_stage", row["processing_status"]),
        "Coverage": (_fmt_pct((row.get("coverage") or {}).get("extraction_coverage"))
                     if (row.get("coverage") or {}).get("extraction_coverage") is not None
                     else "Unavailable"),
        "Unresolved": int(row.get("unresolved_fields") or 0),
        "Multimodal": int((row.get("escalation_summary") or {}).get("pending_multimodal") or 0),
        "Review": int((row.get("human_review_summary") or {}).get("required") or 0),
        "Latency s": round(float((row.get("latency") or {}).get("milliseconds") or 0) / 1000, 2),
        "Status": row["processing_status"],
        "Action": ("Retry" if row["processing_status"] in {
            "FAILED", "FAILED_EXTRACTION", "PARTIAL", "CANCELLED"} else "Inspect"),
    } for row in batch["documents"]], hide_index=True, width="stretch")


def _render_accuracy_dashboard(st, batch: dict) -> None:
    summary = batch["summary"]
    evaluation = batch.get("evaluation")
    st.subheader("Accuracy dashboard")
    if evaluation is None:
        schema_known = any((row.get("coverage") or {}).get("available")
                           for row in batch.get("documents", []))
        if not schema_known:
            st.info("Coverage unavailable — document schema not established")
            return
        st.info("Coverage estimate — no ground truth provided")
        st.caption("Extraction coverage = fields produced / applicable fields. Validated coverage = validated resolved fields / applicable fields. INAPPLICABLE fields are excluded from both denominators.")
        for metric_row in _coverage_metric_rows(summary):
            for column, (label, value) in zip(st.columns(4), metric_row):
                column.metric(label, value)
        with st.expander("Coverage counts"):
            st.dataframe([{
                "Applicable fields": int(summary.get("applicable_fields") or 0),
                "Fields produced": int(summary.get("fields_produced") or 0),
                "Validated fields": int(summary.get("validated_fields") or 0),
                "Inapplicable fields": int(summary.get("inapplicable") or 0),
            }], hide_index=True, width="stretch")
        st.markdown("#### Resolution journey")
        st.dataframe(_resolution_journey(summary), hide_index=True, width="stretch")
        st.caption(_resolution_interpretation(summary))

        st.markdown("#### Unresolved fields")
        unresolved, advanced = _unresolved_display_rows(batch)
        if unresolved:
            st.dataframe(unresolved, hide_index=True, width="stretch")
            with st.expander("Advanced unresolved-field details"):
                st.dataframe(advanced, hide_index=True, width="stretch")
        else:
            st.info("No unresolved applicable fields.")

        coverage_rows = [{
            "Document": row["document"],
            "Type": row["document_type"],
            "Applicable": row["applicable_fields"],
            "Extraction coverage": row["extraction_coverage"],
            "Validated coverage": row["validated_coverage"],
        } for row in summary.get("coverage_by_document", [])]
        st.markdown("#### Coverage")
        if len(coverage_rows) == 1:
            row = coverage_rows[0]
            extraction = float(row.get("Extraction coverage") or 0)
            validated = float(row.get("Validated coverage") or 0)
            st.progress(extraction, text=f"Extraction coverage: {_fmt_pct(extraction)}")
            st.progress(validated, text=f"Validated coverage: {_fmt_pct(validated)}")
        elif coverage_rows:
            st.dataframe(coverage_rows, hide_index=True, width="stretch")
        else:
            st.info("Coverage unavailable â€” document schema not established")

        st.markdown("#### Confidence distribution")
        confidence = summary.get("confidence_distribution") or {}
        for column, band in zip(st.columns(3), ("high", "medium", "low")):
            column.metric(band.title(), int(confidence.get(band) or 0))
        confidence_total = sum(int(confidence.get(band) or 0)
                               for band in ("high", "medium", "low"))
        if confidence_total and int(confidence.get("high") or 0) * 2 < confidence_total:
            st.caption(
                "Fewer than half of applicable fields are high confidence; review the "
                "unresolved and flagged fields before using this result."
            )
    else:
        display = _evaluation_display(evaluation)
        if display["message"]:
            st.warning(display["message"])
        else:
            cards = [
                ("Documents evaluated", evaluation.get("documents_evaluated", 0)),
                ("Fields evaluated", evaluation.get("evaluated_fields", 0)),
                ("Correct", evaluation.get("correct_fields", 0)),
                ("Incorrect", evaluation.get("incorrect_fields", 0)),
                ("Missing", evaluation.get("missing_fields", 0)),
                ("False positives", evaluation.get("false_positive_fields", 0)),
                ("Exact field accuracy", _fmt_pct_or_unavailable(evaluation.get("accuracy"))),
                ("Critical-field accuracy",
                 _fmt_pct_or_unavailable(evaluation.get("critical_accuracy"))),
                ("Precision", _fmt_pct_or_unavailable(evaluation.get("precision"))),
                ("Recall", _fmt_pct_or_unavailable(evaluation.get("recall"))),
            ]
            for start in range(0, len(cards), 4):
                for column, (label, value) in zip(st.columns(4), cards[start:start + 4]):
                    column.metric(label, value)
        st.dataframe([{
            "Unmatched documents": int(evaluation.get("unmatched_documents") or 0),
            "Ambiguous pairs": int(evaluation.get("ambiguous_pairs") or 0),
            "Unmatched expected records": int(
                evaluation.get("unmatched_expected_records") or 0),
        }], hide_index=True, width="stretch")
        if evaluation.get("accuracy_by_document_type"):
            st.markdown("#### Accuracy by document type")
            st.dataframe(evaluation["accuracy_by_document_type"],
                         hide_index=True, width="stretch")
        if evaluation.get("accuracy_by_field"):
            st.markdown("#### Accuracy by field")
            st.dataframe(evaluation["accuracy_by_field"], hide_index=True, width="stretch")
            st.bar_chart(evaluation["accuracy_by_field"], x="field_name", y="accuracy")
    if evaluation is not None:
        st.markdown("#### Unresolved fields")
        unresolved, advanced = _unresolved_display_rows(batch)
        if unresolved:
            st.dataframe(unresolved, hide_index=True, width="stretch")
            with st.expander("Advanced unresolved-field details"):
                st.dataframe(advanced, hide_index=True, width="stretch")
        else:
            st.info("No unresolved applicable fields.")


def _render_cost_dashboard(st, batch: dict) -> None:
    dashboard = batch["summary"]["cost_dashboard"]
    st.subheader("Cost dashboard")
    components = dashboard["components"]
    component_labels = {
        "primary_ocr": "Primary OCR cost",
        "retry_ocr": "Retry OCR cost",
        "local_compute_other": "Other local compute",
        "local_compute": "Total local compute",
        "multimodal_input_tokens": "Multimodal input-token cost",
        "multimodal_output_tokens": "Multimodal output-token cost",
        "projected_multimodal_input_tokens": "Projected multimodal input-token cost",
        "projected_multimodal_output_tokens": "Projected multimodal output-token cost",
        "measured_external_api": "Measured external API cost",
        "projected_api": "Projected API cost",
        "total_automated": "Total automated cost",
        "projected_total_automated": "Projected total automated cost",
    }
    component_rows = [{
        "Component": component_labels[key],
        "Cost USD": cost["value_usd"],
        "Basis": cost["basis"],
    } for key, cost in components.items()]
    for column, (key, cost) in zip(st.columns(5), list(components.items())[:5]):
        column.metric(component_labels[key], _fmt_cost(cost), help=cost["basis"])
    st.markdown("#### Current-run measured cost")
    st.dataframe([row for row in component_rows if row["Basis"] == "MEASURED"],
                 hide_index=True, width="stretch")
    st.markdown("#### Measured automated cost breakdown")
    donut_rows = _measured_cost_donut_rows(components)
    measured_total = components["total_automated"]
    if float(measured_total["value_usd"] or 0) > 0:
        st.vega_lite_chart(spec={
            "height": 300,
            "layer": [{
                "data": {"values": donut_rows},
                "mark": {
                    "type": "arc",
                    "innerRadius": 78,
                    "outerRadius": 120,
                    "cornerRadius": 3,
                },
                "encoding": {
                    "theta": {"field": "Cost USD", "type": "quantitative"},
                    "color": {
                        "field": "Component",
                        "type": "nominal",
                        "legend": {"title": None, "orient": "bottom"},
                        "scale": {"range": [
                            "#0f766e", "#0d9488", "#5eead4", "#2563eb", "#60a5fa"]},
                    },
                    "tooltip": [
                        {"field": "Component", "type": "nominal"},
                        {"field": "Cost USD", "type": "quantitative", "format": "$,.6f"},
                    ],
                },
            }, {
                "data": {"values": [{"label": _fmt_cost(measured_total)}]},
                "mark": {"type": "text", "fontSize": 22, "fontWeight": 650, "dy": -5},
                "encoding": {"text": {"field": "label"}},
            }, {
                "data": {"values": [{"label": "Total measured"}]},
                "mark": {"type": "text", "fontSize": 12, "color": "#52606d", "dy": 19},
                "encoding": {"text": {"field": "label"}},
            }],
            "config": {"view": {"stroke": None}},
        }, width="stretch")
    else:
        st.info("No measured automated cost is available to plot for this batch.")
    if int(dashboard["counters"].get("external_calls") or 0) == 0:
        st.caption("Multimodal cost is $0.000000 because external providers were disabled and no data was sent.")
    st.markdown("#### Current-run projected API cost")
    st.dataframe([row for row in component_rows if row["Basis"] in {
        "PROJECTED", "OFFLINE_ORACLE"}], hide_index=True, width="stretch")
    st.caption("Measured spend and projected API cost remain separate. Human review is excluded from automated cost.")
    unit_labels = {
        "cost_per_page": "Measured cost per page",
        "cost_per_document": "Measured cost per document",
        "measured_cost_per_validated_field": "Measured cost per validated field",
    }
    unit_rows = [{"Metric": unit_labels[name],
                  "Cost": _fmt_cost(cost), "Basis": cost["basis"]}
                 for name, cost in dashboard["unit_costs"].items()]
    st.markdown("#### Unit economics")
    for column, (name, cost) in zip(st.columns(3), dashboard["unit_costs"].items()):
        column.metric(unit_labels[name], _fmt_cost(cost),
                      help=cost["basis"])
    st.dataframe(unit_rows, hide_index=True, width="stretch")
    human = dashboard["human_review_estimate"]
    st.markdown("#### Assumed human-review estimate")
    st.metric(
        "Human-review estimate",
        _fmt_cost(human["total"]),
        help="ASSUMED",
    )
    st.caption(
        f"{human['field_count']} fields x {_fmt_usd(human['assumed_cost_per_field_usd'])} "
        f"= {_fmt_cost(human['total'])} - ASSUMED")
    st.warning("Current-run projections are based on this processed document or batch and are not the frozen benchmark average.")
    st.markdown("#### Current-run extrapolation")
    projection_rows = [{
        "Scale": name.replace("_", " ").title(),
        "Projected cost": _fmt_cost(cost),
        "Cost USD": cost["value_usd"],
        "Basis": cost["basis"],
    } for name, cost in dashboard["enterprise_projection"].items()]
    st.dataframe(projection_rows, hide_index=True, width="stretch")
    st.bar_chart(projection_rows, x="Scale", y="Cost USD")
    st.markdown("#### Routing and usage counters")
    st.dataframe([{"Metric": key.replace("_", " ").title(), "Value": value}
                  for key, value in dashboard["counters"].items()],
                 hide_index=True, width="stretch")
    st.markdown("#### Frozen benchmark projection")
    st.markdown("##### Economy versus Balanced versus Accuracy")
    st.dataframe(dashboard["mode_comparison"], hide_index=True, width="stretch")
    st.caption("Mode comparison is PROJECTED from recorded replay calibration; it is not current-batch measured accuracy or spend.")


def _render_review_queue(st, selected: dict, source, state: dict) -> None:
    queue = workspace.build_review_queue(selected)
    if not queue:
        st.info("No unresolved fields are waiting for local human review.")
        return
    st.warning("Corrections are stored in this browser session only. Durable review storage is roadmap work.")
    review = st.selectbox(
        "Review field", queue,
        format_func=lambda row: (
            f"Page {row['page']} - "
            f"{row['field_name'].replace('_', ' ').title()} - Needs review"),
        key=f"review_item_{selected['safe_source_id']}",
    )
    left, right = st.columns([1, 1.4])
    with left:
        if source and review.get("bbox"):
            try:
                page_image = decode_pages(source.content, source.source_format)[review["page"] - 1]
                crop = service.crop_field(page_image, review["bbox"])
                if crop:
                    st.image(crop, caption="Local field crop", width="stretch")
            except (IntakeError, IndexError):
                st.info("Crop preview is unavailable.")
        st.dataframe([{
            "Criticality": _status_label(review["criticality"]),
            "Confidence": review["confidence"],
            "Reason": review["reason"],
        }], hide_index=True, width="stretch")
    with right:
        st.dataframe([
            {"Candidate": "Primary OCR", "Value": review.get("primary_candidate")},
            {"Candidate": "Local retry", "Value": review.get("retry_candidate")},
            {"Candidate": "Multimodal", "Value": review.get("multimodal_candidate")},
        ], hide_index=True, width="stretch")
        if review["validation_failures"]:
            st.dataframe(review["validation_failures"], hide_index=True, width="stretch")
        else:
            st.info("No validation failure details were recorded.")
        action_labels = {
            "Accept/edit value": "EDIT_VALUE",
            "Mark blank": "MARK_BLANK",
            "Mark not applicable": "MARK_NOT_APPLICABLE",
            "Leave unresolved": "LEAVE_UNRESOLVED",
            "Reject document": "REJECT_DOCUMENT",
        }
        action_label = st.selectbox("Review action", list(action_labels),
                                    key=f"review_action_{selected['safe_source_id']}")
        value = st.text_input("Final value", value=str(
            review.get("retry_candidate") or review.get("primary_candidate") or ""),
            key=f"review_value_{selected['safe_source_id']}")
        reason = st.text_input("Correction reason", key=f"review_reason_{selected['safe_source_id']}")
        action = action_labels[action_label]
        if st.button("Save and next", type="primary",
                     key=f"review_save_{selected['safe_source_id']}",
                     disabled=not _review_action_valid(action, value, reason)):
            try:
                corrected = workspace.apply_human_review(
                    selected, page=review["page"], field_name=review["field_name"],
                    action=action, value=value, reason=reason)
            except ValueError as exc:
                st.error(str(exc))
            else:
                batch = state["batch_results"]
                batch["documents"] = [corrected if row["safe_source_id"] ==
                                      corrected["safe_source_id"] else row
                                      for row in batch["documents"]]
                state["review_corrections"] = [
                    {"safe_source_id": row["safe_source_id"], **audit}
                    for row in batch["documents"]
                    for audit in row.get("review_audit", [])
                ]
                _refresh_workspace_batch(state)
                st.rerun()


def _render_local_document(st, result, items, state: dict | None = None):
    processed = [row for row in result.get("documents", [])
                 if row["processing_status"] not in {"SKIPPED", "DUPLICATE"}]
    if not processed:
        st.info("Process a supported document to inspect its result.")
        return
    if state is None:
        selected = st.selectbox(
            "Document", processed,
            format_func=lambda row: f"{row['source_file']} - {row['processing_status']}")
    else:
        by_id = {row["safe_source_id"]: row for row in processed}
        selected_id = state.get("selected_result_id")
        if selected_id not in by_id:
            selected_id = processed[0]["safe_source_id"]
        state["selected_result_id"] = selected_id
        st.session_state.setdefault("cr_result_document", selected_id)
        if st.session_state["cr_result_document"] not in by_id:
            st.session_state["cr_result_document"] = selected_id
        selected_id = st.selectbox(
            "Document", list(by_id),
            format_func=lambda source_id: (
                f"{by_id[source_id]['source_file']} - "
                f"{by_id[source_id]['processing_status'].replace('_', ' ').title()}"),
            key="cr_result_document",
        )
        selected = by_id[selected_id]
        state["selected_result_id"] = selected_id
    source = next((item for item in items
                   if item.safe_source_id == selected["safe_source_id"]), None)
    for column, (label, value) in zip(st.columns(4), [
        ("Pages", int(selected.get("page_count") or 0)),
        ("Status", _status_label(selected.get("processing_status"))),
        ("Unresolved", int(selected.get("unresolved_fields") or 0)),
        ("Latency", f"{float((selected.get('latency') or {}).get('milliseconds') or 0) / 1000:.2f} s"),
    ]):
        column.metric(label, value)
    for warning in selected.get("warnings", []):
        st.warning(warning)
    left, right = st.columns([1, 1.4])
    with left:
        if source and source.role == FileRole.CLAIM_DOCUMENT:
            try:
                st.image(decode_pages(source.content, source.source_format)[0],
                         caption="First decoded page", width="stretch")
            except IntakeError:
                st.warning("Preview is unavailable; processing metadata remains visible.")
    with right:
        field_rows = []
        for page in selected["fields"]:
            for name, field in page["fields"].items():
                field_rows.append({
                    "Page": page["page"], "Field": name,
                    "Value": field.get("value"), "State": field.get("state"),
                    "Confidence": field.get("confidence"),
                    "Provenance": ", ".join(
                        entry.get("engine", "") for entry in field.get("provenance", [])),
                })
        filters = _field_filter_options(field_rows)
        selected_filter = st.selectbox(
            "Filter fields", list(filters),
            key=f"cr_field_filter_{selected['safe_source_id']}")
        selected_states = filters[selected_filter]
        visible_rows = (field_rows if selected_states is None else [
            row for row in field_rows if row.get("State") in selected_states])
        st.dataframe(visible_rows, hide_index=True, width="stretch")
    latency = selected.get("latency") or {}
    stages = latency.get("stages_ms") or {}
    with st.expander("Latency details"):
        st.dataframe([{
            "Primary OCR latency": f"{float(stages.get('primary_ocr') or 0) / 1000:.2f} s",
            "Retry OCR latency": f"{float(stages.get('retry_ocr') or 0) / 1000:.2f} s",
            "Total latency": f"{float(latency.get('milliseconds') or 0) / 1000:.2f} s",
            "Retry fields": int((selected.get("retry_summary") or {}).get(
                "fields_retried") or 0),
        }], hide_index=True, width="stretch")
    retryable = selected["processing_status"] in {
        "FAILED", "FAILED_EXTRACTION", "PARTIAL", "CANCELLED"}
    if retryable and source:
        label = "Retry document locally"
        st.caption("Prototype retry re-runs this local document and preserves the prior result "
                   "in session memory. It never triggers an external provider call.")
        fingerprint = _retry_fingerprint(selected)
        if st.button(label, key=f"retry_{selected['safe_source_id']}") and (
                state is None or _queue_retry_job(state, fingerprint)):
            with st.status("Retrying document locally", expanded=True):
                retried = (_run_retry_job(state, fingerprint, source)
                           if state is not None else workspace.retry_document(
                               result, source, mode=result.get("operating_mode")))
            if state is not None:
                _refresh_workspace_batch(state)
            else:
                st.session_state["workspace_batch"] = retried
            st.rerun()
    receipts = [row for row in (state or {}).get("retry_receipts", [])
                if row["safe_source_id"] == selected["safe_source_id"]]
    if receipts:
        receipt = receipts[-1]
        st.markdown("#### Local retry receipt")
        st.dataframe([{
            "Unresolved before": receipt["unresolved_before"],
            "Fields attempted": receipt["fields_attempted"],
            "Fields resolved": receipt["fields_resolved"],
            "Unresolved after": receipt["unresolved_after"],
            "Retry latency": f"{receipt['retry_latency_ms'] / 1000:.2f} s",
            "Total latency": f"{receipt['total_latency_ms'] / 1000:.2f} s",
            "External calls": receipt["external_calls"],
            "Improved": _yes_no(receipt["improved"]),
        }], hide_index=True, width="stretch")
        if not receipt["improved"]:
            st.info("No additional fields were resolved.")
    if state is not None:
        _render_multimodal_permission(st, state, selected, source)
    evidence_tabs = st.tabs(["Validations", "Retries & governor", "Cost & latency"])
    with evidence_tabs[0]:
        validation_rows = _validation_rows(selected["validations"])
        if validation_rows:
            st.dataframe(validation_rows, hide_index=True, width="stretch")
        else:
            st.info("No validation results were produced for this document.")
    with evidence_tabs[1]:
        with st.expander("Technical routing receipt"):
            st.write({
                "governor": selected["governor_summary"],
                "retry": selected["retry_summary"],
                "resolution": selected.get("resolution_summary", {}),
                "escalation": selected["escalation_summary"],
            })
        st.markdown("#### Provider and escalation state")
        provider = selected.get("provider_state") or workspace._provider_policy_snapshot()
        st.write({
            "Provider": _provider_label(provider["provider_name"]),
            "Enabled": _yes_no(provider["provider_enabled"]),
            "Configured model": provider["configured_model"] or "Not configured",
            "Credential available": _yes_no(provider["credential_available"]),
            "External call attempted": _yes_no(provider["external_call_attempted"]),
            "External calls": int(provider["external_call_count"] or 0),
            "Reason": provider["reason_not_attempted"],
            "No data sent": _yes_no(provider["no_data_sent"]),
        })
        provider_rows = _provider_rows(selected)
        if provider_rows:
            st.dataframe(provider_rows, hide_index=True, width="stretch")
        else:
            st.info("No unresolved or escalated fields require provider routing.")
    with evidence_tabs[2]:
        with st.expander("Technical cost and latency receipt"):
            st.write({
                "measured_cost": selected["measured_cost"],
                "projected_cost": selected["projected_cost"],
                "latency": selected["latency"],
            })
    json_column, csv_column = st.columns(2)
    json_column.download_button(
        "Download document JSON", workspace.export_document_json(selected),
        file_name=f"{selected['safe_source_id']}-document.json",
        mime="application/json", width="stretch",
    )
    csv_column.download_button(
        "Download document CSV", workspace.export_document_csv(selected),
        file_name=f"{selected['safe_source_id']}-fields.csv",
        mime="text/csv", width="stretch",
    )


def _render_local_review(st, batch: dict, items: list, state: dict | None = None) -> None:
    processed = [row for row in batch.get("documents", [])
                 if row["processing_status"] not in {"SKIPPED", "DUPLICATE"}]
    if not processed:
        st.info("Process a supported document before opening the review queue.")
        return
    selected = st.selectbox(
        "Document", processed,
        format_func=lambda row: f"{row['source_file']} - {row['processing_status']}",
        key="workspace_review_document",
    )
    source = next((item for item in items
                   if item.safe_source_id == selected["safe_source_id"]), None)
    review_summary = selected.get("human_review_summary") or {}
    for column, (label, value) in zip(st.columns(3), [
        ("Unresolved fields", int(selected.get("unresolved_fields") or 0)),
        ("Review required", int(review_summary.get("required") or 0)),
        ("Review completed", int(review_summary.get("completed") or 0)),
    ]):
        column.metric(label, value)
    _render_review_queue(st, selected, source, state or {
        "batch_results": batch,
        "workflow": "Process Documents",
        "inventory": items,
        "review_corrections": [],
    })


def _render_local_summary(st, batch):
    st.subheader("Batch and evaluation summary")
    if not batch:
        st.info("Run the selected inventory to create a batch summary.")
        return
    _render_dashboard(st, batch)
    summary = batch["summary"]
    st.dataframe(_batch_summary_rows(summary), hide_index=True, width="stretch")
    st.write({"document_types": summary["document_types"]})
    _render_accuracy_dashboard(st, batch)
    _render_cost_dashboard(st, batch)
    if batch.get("evaluation"):
        st.caption("Expected output was parsed and compared only after extraction completed.")
    json_column, csv_column = st.columns(2)
    json_column.download_button(
        "Download batch JSON", workspace.export_batch_json(batch),
        file_name=f"{batch['batch_job_id']}.json", mime="application/json", width="stretch",
    )
    csv_column.download_button(
        "Download batch CSV", workspace.export_batch_csv(batch),
        file_name=f"{batch['batch_job_id']}.csv", mime="text/csv", width="stretch",
    )


def _workspace_header(st, mode: str) -> None:
    mode_label = service.MODE_LABELS.get(mode, mode.title())
    st.markdown(
        '<div class="cr-app-header"><div><h1>ClaimRoute AI</h1>'
        '<p>Every field takes the cheapest reliable path.</p></div>'
        f'<div class="cr-mode">Mode: {mode_label}</div></div>',
        unsafe_allow_html=True,
    )


def _workspace_sidebar(st, state: dict) -> None:
    st.sidebar.markdown(
        '<div class="cr-sidebar-brand"><strong>ClaimRoute AI</strong><br>'
        '<span>Local claims workspace</span></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        f'<div class="cr-mode">Mode: '
        f'{service.MODE_LABELS.get(state["operating_mode"], state["operating_mode"].title())}'
        '</div>', unsafe_allow_html=True)
    # Derived, never asserted: an enabled provider must not be reported as
    # disabled just because the usual demo runs with it switched off.
    provider_state = workspace._provider_policy_snapshot()
    enabled = bool(provider_state.get("provider_enabled"))
    st.sidebar.markdown(
        f'<div class="cr-rail-status {"warn" if enabled else "ok"}"><i></i>'
        f'{"External provider enabled - governed" if enabled else "External providers disabled"}'
        '</div>', unsafe_allow_html=True)
    st.sidebar.caption(
        f'{dashboard.environment_label(app_mode())} - '
        f'{provider_state.get("reason_not_attempted") or "no external call"}. '
        "Authorized local data only. Keep this workspace on localhost.")
    batch = state.get("batch_results")
    if batch:
        st.sidebar.divider()
        st.sidebar.markdown(
            f"**Batch status:** {_batch_status_label(batch.get('processing_status'))}")
        st.sidebar.metric("Documents", int(
            (batch.get("summary") or {}).get("files") or 0))
        st.sidebar.metric("External calls", int(
            (batch.get("summary") or {}).get("external_calls") or 0))
    st.sidebar.divider()
    confirm_reset = st.sidebar.checkbox(
        "Confirm reset", key="cr_confirm_reset",
        help="Required because reset clears all current session data.")
    st.sidebar.button(
        "Reset session", on_click=_reset_workspace_session,
        args=(st.session_state,), width="stretch", disabled=not confirm_reset,
        help="Clears uploads, inventory, results, corrections, and dashboard values.")


def _render_workspace_intake(st, state: dict, running: bool) -> None:
    st.subheader("Intake")
    st.markdown(
        '<p class="cr-section-intro">Choose a workflow, add authorized local files, '
        'and confirm exactly what enters the run.</p>', unsafe_allow_html=True)
    st.session_state.setdefault("cr_workflow", state["workflow"])
    workflow = st.radio(
        "Workflow", ["Process Documents", "Evaluate Dataset"], horizontal=True,
        help="Evaluation parses expected output only after document extraction finishes.",
        disabled=running or bool(state.get("batch_results")), key="cr_workflow",
    )
    state["workflow"] = workflow
    st.session_state.setdefault("cr_operating_mode", state["operating_mode"])
    mode = st.selectbox(
        "Operating mode", list(service.MODE_LABELS),
        format_func=service.MODE_LABELS.get,
        disabled=running or bool(state.get("batch_results")),
        help="This selection changes runtime governor thresholds; it never enables a provider.",
        key="cr_operating_mode",
    )
    state["operating_mode"] = mode
    mode_help = {
        "economy": "Minimizes cost; only the most critical unresolved fields remain eligible.",
        "balanced": "Recommended default; local retry first with selective escalation eligibility.",
        "accuracy": "Higher local acceptance threshold and no accept-with-flag shortcut.",
    }
    selected_policy = workspace.mode_policy(mode)
    st.caption(f"{mode_help[mode]} Runtime accept threshold: "
               f"{selected_policy['accept_threshold']:.2f}. External calls enabled: No.")
    if state.get("batch_results"):
        st.caption("Reset the session to change workflow or operating mode after processing.")
    st.session_state.setdefault("cr_input_source", state["input_source"])
    source = st.radio(
        "Input source", ["Single file", "Multiple files", "Local folder"], horizontal=True,
        disabled=running, key="cr_input_source",
    )
    state["input_source"] = source
    max_pages = int(os.environ.get("CLAIMROUTE_MAX_PAGES", "100"))
    items = state["inventory"]
    if source == "Single file":
        uploaded = st.file_uploader(
            "Choose one local file", type=None, key="workspace_single", disabled=running)
        uploaded_items = _uploaded_items([uploaded] if uploaded else [], max_pages)
        if uploaded_items:
            items = uploaded_items
            state["inventory"] = items
    elif source == "Multiple files":
        uploaded = st.file_uploader(
            "Choose local files", type=None, accept_multiple_files=True,
            key="workspace_multiple", disabled=running)
        uploaded_items = _uploaded_items(uploaded, max_pages)
        if uploaded_items:
            items = uploaded_items
            state["inventory"] = items
    else:
        folder = st.text_input(
            "Local dataset/folder path", key="workspace_folder_path", disabled=running)
        scan_columns = st.columns(2)
        scan_requested = scan_columns[0].button(
            "Scan folder", type="primary", disabled=running or not folder)
        retry_requested = scan_columns[1].button(
            "Retry scan", disabled=running or not folder or
            (state.get("scan_result") or {}).get("state")
            != ScanState.SCAN_FAILED.value)
        scan_progress = st.progress(0)
        scan_status = st.empty()
        if scan_requested or retry_requested:
            scan_started = time.perf_counter()

            def on_scan(event):
                event["entered_path"] = folder
                state["scan_result"] = event
                discovered = int(event.get("files_discovered") or 0)
                scanned = int(event.get("files_scanned") or 0)
                scan_progress.progress(scanned / discovered if discovered else 0)
                scan_status.info(
                    f"Scanning: {event['state']} - {scanned}/{discovered} files - "
                    f"elapsed {time.perf_counter() - scan_started:.2f}s")

            try:
                items = scan_folder(folder, max_pages=max_pages, progress=on_scan)
                state["inventory"] = items
            except IntakeError as exc:
                st.error(str(exc))
            except Exception:
                failure = {
                    "state": ScanState.SCAN_FAILED.value,
                    "entered_path": folder,
                    "elapsed_seconds": round(time.perf_counter() - scan_started, 3),
                    "error_reason": "Folder scan failed safely; review the local terminal log.",
                }
                state["scan_result"] = failure
                st.error(failure["error_reason"])
        _render_scan_state(st, state.get("scan_result"))

    st.markdown("#### File inventory")
    if not items:
        st.info("Add files or scan a folder to build the inventory.")
        return
    st.dataframe(_inventory_rows(items), hide_index=True, width="stretch")
    defaults = [item.safe_source_id for item in items
                if item.role == FileRole.CLAIM_DOCUMENT or (
                    workflow == "Evaluate Dataset" and item.role == FileRole.EXPECTED_OUTPUT)]
    options = [item.safe_source_id for item in items]
    signature = tuple(options)
    processing = state["processing_state"]
    if processing.get("selection_signature") != signature:
        existing = [source_id for source_id in state["selected_document_ids"]
                    if source_id in options]
        state["selected_document_ids"] = existing or defaults
        processing["selection_signature"] = signature
        st.session_state["cr_selected_documents"] = state["selected_document_ids"]
    st.session_state.setdefault(
        "cr_selected_documents", state["selected_document_ids"])
    state["selected_document_ids"] = st.multiselect(
        "Files included in this run", options, disabled=running,
        format_func=lambda source_id: next(
            item.filename for item in items if item.safe_source_id == source_id),
        key="cr_selected_documents",
    )
    st.caption("Selected files remain in this run until the session is reset.")


def _render_workspace_processing(st, state: dict, running: bool) -> None:
    st.subheader("Processing")
    st.markdown(
        '<p class="cr-section-intro">Run the selected inventory and watch each document '
        'move through local OCR, retry, validation, and governed routing.</p>',
        unsafe_allow_html=True,
    )
    items = state["inventory"]
    selected_ids = state["selected_document_ids"]
    selected = [item for item in items if item.safe_source_id in selected_ids]
    workflow = state["workflow"]
    mode = state["operating_mode"]
    if not selected:
        st.info("Build an inventory in Intake and select at least one claim document.")
        return
    st.dataframe(_inventory_rows(selected), hide_index=True, width="stretch")
    st.caption("Processing is synchronous. Stop is honored between documents. "
               "The active stage remains visible during OCR.")
    stop_after_first = st.checkbox(
        "Stop after the current document", disabled=running,
        key="cr_stop_after_current")
    queue_slot = st.empty()
    progress_bar = st.progress(0)
    fingerprint = workspace._job_id(selected, f"{mode}:{workflow}")
    existing_batch = state.get("batch_results")
    confirm_reprocess = False
    if existing_batch:
        confirm_reprocess = st.checkbox(
            "Confirm reprocessing selected files",
            help="Reprocessing replaces the current batch receipt for these selections.",
            key="cr_confirm_reprocess")
    clicked = st.button(
        "Processing selected files..." if running else (
            "Reprocess selected files" if existing_batch else "Process selected files"),
        type="primary", disabled=running or (bool(existing_batch) and not confirm_reprocess),
    )
    if clicked and _queue_workspace_job(state, fingerprint):
        st.rerun()
    processing = state["processing_state"]
    if running and processing.get("pending_job") == fingerprint:
        processed = {"count": 0}
        processing_started = time.perf_counter()
        stage_slot = st.empty()

        def on_progress(index, total, result):
            processed["count"] = index
            progress_bar.progress(index / total)
            queue_slot.dataframe([{
                "Document": result["source_file"],
                "Status": _status_label(result["processing_status"]),
                "Warning": "; ".join(result["warnings"]),
            }], hide_index=True, width="stretch")

        def on_stage(event):
            processing["stage"] = event
            elapsed = time.perf_counter() - processing_started
            page = (f" - page {event.get('current_page')}/{event.get('total_pages')}"
                    if event.get("current_page") else "")
            stage_slot.info(
                f"Document {event['document_number']}/{event['total_documents']} - "
                f"{event['stage'].replace('_', ' ').title()}{page} - "
                f"elapsed {elapsed:.2f}s - {event['message']}")

        st.info(f"Processing {len(selected)} selected document(s). Please wait.")
        _run_workspace_job(
            state,
            fingerprint,
            lambda: workspace.run_batch(
                selected,
                mode=mode,
                evaluate=workflow == "Evaluate Dataset",
                progress=on_progress,
                stage_progress=on_stage,
                stop_requested=lambda: stop_after_first and processed["count"] >= 1,
            ),
        )
        st.rerun()
    if processing.get("error"):
        st.error(processing["error"])
    batch = state.get("batch_results")
    last_stage = processing.get("stage")
    if last_stage and not running:
        st.caption(f"Last stage: {_status_label(last_stage['stage'])} - "
                   f"{last_stage['message']}")
    if batch:
        queue_slot.dataframe([{
            "Document": row["source_file"], "Status": _status_label(row["processing_status"]),
            "Warning": "; ".join(row["warnings"]),
        } for row in batch["documents"]], hide_index=True, width="stretch")
        summary = batch.get("summary") or {}
        for column, (label, value) in zip(st.columns(4), [
            ("Completed", int(summary.get("success") or 0)),
            ("Partial", int(summary.get("partial") or 0)),
            ("Failed", int(summary.get("failed") or 0) +
             int(summary.get("failed_extraction") or 0)),
            ("Unresolved", int(summary.get("unresolved_fields") or 0)),
        ]):
            column.metric(label, value)
        actions = st.columns(2)
        actions[0].button(
            "Open Results", type="primary", width="stretch",
            on_click=_activate_workspace_tab,
            args=(st.session_state, "Results"))
        failed_ids = [
            row["safe_source_id"] for row in batch["documents"]
            if row["processing_status"] in {"FAILED", "FAILED_EXTRACTION", "CANCELLED"}
        ]
        retry_failed = actions[1].button(
            "Retry failed batch items", width="stretch", disabled=not failed_ids)
        if retry_failed:
            retried = batch
            with st.status("Retrying failed documents locally", expanded=True):
                for source_id in failed_ids:
                    source_item = next((item for item in items
                                        if item.safe_source_id == source_id), None)
                    if source_item is None:
                        continue
                    retried = workspace.retry_document(retried, source_item, mode=mode)
                    result = next(row for row in retried["documents"]
                                  if row["safe_source_id"] == source_id)
                    state["retry_receipts"].append({
                        "safe_source_id": source_id,
                        **result["retry_history"][-1],
                    })
            _store_workspace_batch(state, retried)
            _refresh_workspace_batch(state)
            st.rerun()
        st.caption("Results, review, accuracy, and cost all use this same batch receipt.")
    else:
        st.info("The selected documents are ready to process.")


def _local_workspace(st) -> None:
    state = _workspace_state(st.session_state)
    _sync_workspace_controls(st.session_state, state)
    if state.get("batch_results") and state.get("cost_summary") is None:
        _store_workspace_batch(state, state["batch_results"])
    _workspace_sidebar(st, state)
    _workspace_header(st, state["operating_mode"])
    running = bool(state["processing_state"].get("running"))
    tabs = st.tabs(
        WORKSPACE_TABS, default=state.get("active_tab", WORKSPACE_TABS[0]),
        key="cr_workspace_tabs", on_change="rerun")
    state["active_tab"] = st.session_state.get("cr_workspace_tabs", WORKSPACE_TABS[0])

    with tabs[0]:
        _render_judge_dashboard(st, state)

    with tabs[1]:
        _render_workspace_intake(st, state, running)
        st.divider()
        _render_workspace_processing(st, state, running)

    batch = state.get("batch_results")
    items = state["inventory"]
    with tabs[2]:
        st.subheader("Results")
        st.markdown('<p class="cr-section-intro">Inspect extracted fields, evidence, routing '
                    'state, and document exports.</p>', unsafe_allow_html=True)
        if batch:
            _render_local_document(st, batch, items, state)
            with st.expander("Batch exports"):
                json_column, csv_column = st.columns(2)
                json_column.download_button(
                    "Download batch JSON", workspace.export_batch_json(batch),
                    file_name=f"{batch['batch_job_id']}.json", mime="application/json",
                    width="stretch")
                csv_column.download_button(
                    "Download batch CSV", workspace.export_batch_csv(batch),
                    file_name=f"{batch['batch_job_id']}.csv", mime="text/csv",
                    width="stretch")
        else:
            st.info("Process at least one document in Intake & Run.")

    with tabs[3]:
        st.subheader("Human Review")
        st.markdown('<p class="cr-section-intro">Resolve fields that could not be accepted '
                    'automatically. Corrections remain in this browser session.</p>',
                    unsafe_allow_html=True)
        if batch:
            _render_local_review(st, batch, items, state)
        else:
            st.info("Process at least one document in Intake & Run.")

    with tabs[4]:
        if batch:
            _render_accuracy_dashboard(st, batch)
        else:
            st.subheader("Accuracy")
            st.info("Process at least one document in Intake & Run.")

    with tabs[5]:
        if batch:
            _render_cost_dashboard(st, batch)
        else:
            st.subheader("Cost")
            st.info("Process at least one document in Intake & Run.")


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="ClaimRoute AI", page_icon="CR", layout="wide")
    _style(st)
    if app_mode() == "local_workspace":
        _local_workspace(st)
        return
    st.markdown(
        '<div class="cr-header"><h1>ClaimRoute AI</h1>'
        '<p><strong>Interactive synthetic-claim demo.</strong> Inspect how each field earns '
        'its route through local OCR, validation, governed retry, and selective escalation. '
        'Real claims and PHI are not permitted.</p></div>',
        unsafe_allow_html=True)
    st.markdown(
        '<div class="cr-pipeline">Document → Preprocess → Route → Primary OCR → Validate → '
        'Cost Governor → Local Retry → Selective Escalation → Final Validation → Structured Output</div>',
        unsafe_allow_html=True)

    controls = _document_controls(st)
    if controls is None:
        st.info("Choose a bundled synthetic example or upload a local claim image to begin.")
        return
    document, doc_id, tier, mode, source_kind = controls
    if source_kind == "upload":
        st.success("Synthetic upload confirmed. Temporary upload storage is deleted after "
                   "decoding, and no external provider is used.")
    else:
        st.success("Safe synthetic example. Zero PHI by construction and no external API call.")

    receipt = st.session_state.get("receipt")
    run_key = f"{document.sha256}:{mode}:{source_kind}:{tier}"
    _render_document_summary(st, document, receipt if st.session_state.get("run_key") == run_key else None,
                             source_kind, mode)
    screenshot_safe = st.toggle("Screenshot-safe mode", value=True,
                                help="Hides document pixels, crops, and extracted values.")

    if st.button("Run extraction", type="primary", width="stretch"):
        if st.session_state.get("run_key") == run_key and receipt:
            st.info("Duplicate run prevented. Showing the existing receipt.")
        else:
            try:
                with st.status("Running the cost-governed pipeline", expanded=True) as status:
                    st.write("Local preprocessing and document routing")
                    st.write("Primary OCR, validation, and governed resolution")
                    receipt = service.process_document(
                        document.image, doc_id, mode, source_kind=source_kind, tier=tier)
                    status.update(label="Extraction complete", state="complete", expanded=False)
                st.session_state["receipt"] = receipt
                st.session_state["run_key"] = run_key
            except service.AppProcessingError as exc:
                st.error(str(exc))
                return

    receipt = st.session_state.get("receipt")
    if not receipt or st.session_state.get("run_key") != run_key:
        st.info("Ready. Run extraction to generate a fresh audit receipt.")
        return

    tabs = st.tabs(["Results", "Field evidence", "Cost & performance", "Operating modes", "Benchmark"])
    with tabs[0]:
        _render_results(st, receipt, document.image, screenshot_safe)
    with tabs[1]:
        _render_evidence(st, receipt, document.image, screenshot_safe)
    with tabs[2]:
        _render_costs(st, receipt)
    with tabs[3]:
        _render_modes(st)
    with tabs[4]:
        _render_benchmark(st)


if __name__ == "__main__":
    main()
