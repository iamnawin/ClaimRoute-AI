"""ClaimRoute Day 10 Streamlit demo."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import service, workspace
from app.intake import (FileRole, IntakeError, ScanState, decode_pages,
                        inspect_content, scan_folder)


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


def _queue_workspace_job(state, fingerprint: str) -> bool:
    if state.get("workspace_job_running"):
        return False
    state["workspace_job_running"] = True
    state["workspace_pending_job"] = fingerprint
    state.pop("workspace_job_error", None)
    return True


def _run_workspace_job(state, fingerprint: str, runner):
    if (not state.get("workspace_job_running")
            or state.get("workspace_pending_job") != fingerprint
            or state.get("workspace_active_job")):
        return None
    state["workspace_active_job"] = fingerprint
    try:
        result = runner()
        state["workspace_batch"] = result
        return result
    except Exception:
        state["workspace_job_error"] = (
            "Processing failed safely. Review the local terminal log and retry."
        )
        return None
    finally:
        state["workspace_job_running"] = False
        state.pop("workspace_pending_job", None)
        state.pop("workspace_active_job", None)


def _style(st) -> None:
    st.markdown(
        """
        <style>
        :root {
          --cr-bg: oklch(0.985 0 0);
          --cr-surface: oklch(0.955 0.008 188);
          --cr-ink: oklch(0.225 0.025 200);
          --cr-muted: oklch(0.400 0.022 200);
          --cr-primary: oklch(0.455 0.105 188);
          --cr-primary-soft: oklch(0.925 0.035 188);
        }
        .stApp { background: var(--cr-bg); color: var(--cr-ink); }
        [data-testid="stSidebar"] { background: var(--cr-surface); }
        h1, h2, h3 { color: var(--cr-ink); letter-spacing: -0.02em; text-wrap: balance; }
        p, label, [data-testid="stCaptionContainer"] { color: var(--cr-muted); }
        .cr-header { max-width: 68ch; margin-bottom: 1.2rem; }
        .cr-header h1 { font-size: 2.45rem; line-height: 1.05; margin: 0 0 .7rem; }
        .cr-header p { font-size: 1rem; line-height: 1.55; margin: 0; }
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
        div[data-testid="stMetric"] { padding: .35rem 0; }
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
    st.markdown("#### Extraction coverage")
    if not coverage.get("available"):
        st.info(coverage.get("message") or
                "Coverage unavailable â€” document schema not established")
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
    extraction = coverage.get("extraction_coverage")
    validated = coverage.get("validated_coverage")
    st.caption(
        "Extraction coverage = produced/applicable; validated coverage = validated "
        "resolved/applicable. These are not accuracy metrics."
    )
    left, right = st.columns(2)
    left.metric("Extraction coverage", _fmt_pct(extraction) if extraction is not None else "N/A")
    right.metric("Validated coverage", _fmt_pct(validated) if validated is not None else "N/A")
    st.write({"confidence_distribution": coverage["confidence_distribution"]})


def _render_dashboard(st, batch: dict) -> None:
    summary = batch["summary"]
    st.subheader("Processing dashboard")
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


def _render_review_queue(st, selected: dict, source, batch: dict) -> None:
    queue = workspace.build_review_queue(selected)
    st.markdown("#### Human review queue")
    if not queue:
        st.info("No unresolved fields are waiting for local human review.")
        return
    st.warning("Corrections are stored in this browser session only. Durable review storage is roadmap work.")
    review = st.selectbox(
        "Review field", queue,
        format_func=lambda row: f"Page {row['page']} Â· {row['field_name']} Â· {row['provider_state']}",
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
        st.write({"criticality": review["criticality"],
                  "confidence": review["confidence"],
                  "reason": review["reason"]})
    with right:
        st.dataframe([
            {"Candidate": "Primary OCR", "Value": review.get("primary_candidate")},
            {"Candidate": "Local retry", "Value": review.get("retry_candidate")},
            {"Candidate": "Multimodal", "Value": review.get("multimodal_candidate")},
        ], hide_index=True, width="stretch")
        st.write({"validation_failures": review["validation_failures"]})
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
        if st.button("Save correction", type="primary",
                     key=f"review_save_{selected['safe_source_id']}"):
            try:
                corrected = workspace.apply_human_review(
                    selected, page=review["page"], field_name=review["field_name"],
                    action=action_labels[action_label], value=value, reason=reason)
            except ValueError as exc:
                st.error(str(exc))
            else:
                batch["documents"] = [corrected if row["safe_source_id"] ==
                                      corrected["safe_source_id"] else row
                                      for row in batch["documents"]]
                batch["processing_status"] = workspace._batch_status(batch["documents"])
                batch["summary"] = workspace.summarize_results(batch["documents"])
                batch["evaluation"] = None
                st.session_state["workspace_batch"] = batch
                st.rerun()


def _render_local_document(st, result, items):
    st.subheader("Document result")
    processed = [row for row in result.get("documents", [])
                 if row["processing_status"] not in {"SKIPPED", "DUPLICATE"}]
    if not processed:
        st.info("Process a supported document to inspect its result.")
        return
    selected = st.selectbox(
        "Document", processed,
        format_func=lambda row: f"{row['source_file']} · {row['processing_status']}",
        key="workspace_result_document",
    )
    source = next((item for item in items
                   if item.safe_source_id == selected["safe_source_id"]), None)
    left, right = st.columns([1, 1.4])
    with left:
        if source and source.role == FileRole.CLAIM_DOCUMENT:
            try:
                st.image(decode_pages(source.content, source.source_format)[0],
                         caption="First decoded page", width="stretch")
            except IntakeError:
                st.warning("Preview is unavailable; processing metadata remains visible.")
        st.metric("Pages", selected["page_count"])
        st.metric("Current/final stage", selected.get(
            "processing_stage", selected["processing_status"]))
        st.metric("Unresolved fields", selected["unresolved_fields"]
                  if selected["unresolved_fields"] is not None else "Unknown")
        st.metric("Latency", f"{selected['latency']['milliseconds'] / 1000:.2f} s")
        for warning in selected["warnings"]:
            st.warning(warning)
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
        st.dataframe(field_rows, hide_index=True, width="stretch")
    _render_coverage(st, selected)
    retryable = selected["processing_status"] in {
        "FAILED", "FAILED_EXTRACTION", "PARTIAL", "CANCELLED"}
    if retryable and source:
        label = ("Retry unresolved fields" if selected["processing_status"] == "PARTIAL"
                 else "Resume document" if selected["processing_status"] == "CANCELLED"
                 else "Retry document")
        st.caption("Prototype retry re-runs this local document and preserves the prior result "
                   "in session memory. It never triggers an external provider call.")
        if st.button(label, key=f"retry_{selected['safe_source_id']}"):
            with st.status("Retrying document locally", expanded=True):
                retried = workspace.retry_document(
                    result, source, mode=result.get("operating_mode"))
            st.session_state["workspace_batch"] = retried
            st.rerun()
    pending_multimodal = int(
        (selected.get("escalation_summary") or {}).get("pending_multimodal") or 0)
    if pending_multimodal:
        provider = selected.get("provider_state") or workspace._provider_policy_snapshot()
        st.button(
            "Run eligible multimodal fields",
            disabled=True,
            help=("Disabled for this implementation session. Provider policy and explicit "
                  "run permission must be verified separately. No data has been sent."),
            key=f"multimodal_{selected['safe_source_id']}",
        )
    evidence_tabs = st.tabs(["Validations", "Retries & governor", "Cost & latency"])
    with evidence_tabs[0]:
        validation_rows = _validation_rows(selected["validations"])
        if validation_rows:
            st.dataframe(validation_rows, hide_index=True, width="stretch")
        else:
            st.info("No validation results were produced for this document.")
    with evidence_tabs[1]:
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
        st.write({
            "measured_cost": selected["measured_cost"],
            "projected_cost": selected["projected_cost"],
            "latency": selected["latency"],
        })
    _render_review_queue(st, selected, source, result)
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


def _render_local_summary(st, batch):
    st.subheader("Batch and evaluation summary")
    if not batch:
        st.info("Run the selected inventory to create a batch summary.")
        return
    _render_dashboard(st, batch)
    summary = batch["summary"]
    st.dataframe(_batch_summary_rows(summary), hide_index=True, width="stretch")
    st.write({"document_types": summary["document_types"]})
    if batch.get("evaluation"):
        evaluation = batch["evaluation"]
        display = _evaluation_display(evaluation)
        if display["message"]:
            st.warning(display["message"])
        else:
            left, right = st.columns(2)
            left.metric("Field accuracy", display["field_accuracy"])
            right.metric("Critical accuracy", display["critical_accuracy"])
        st.dataframe([
            {"Metric": label, "Value": int(evaluation.get(key) or 0)}
            for key, label in EVALUATION_COUNTERS.items()
        ], hide_index=True, width="stretch")
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


def _local_workspace(st) -> None:
    st.markdown(
        '<div class="cr-header"><h1>ClaimRoute local workspace</h1>'
        '<p>Inspect, process, and evaluate local claim datasets without transmitting files. '
        'Raw values remain in this browser session; external escalation is disabled.</p></div>',
        unsafe_allow_html=True,
    )
    st.success("Local workspace mode · folder access enabled · external providers disabled")
    st.warning("Authorized local data only. Do not expose this workspace through a public URL.")

    running = bool(st.session_state.get("workspace_job_running"))
    st.subheader("Intake")
    workflow = st.radio(
        "Workflow", ["Process Documents", "Evaluate Dataset"], horizontal=True,
        help="Evaluation parses expected output only after document extraction finishes.",
        disabled=running,
    )
    mode = st.selectbox(
        "Operating mode", list(service.MODE_LABELS),
        index=list(service.MODE_LABELS).index(service.DEFAULT_MODE),
        format_func=service.MODE_LABELS.get, disabled=running,
        help="This selection changes the runtime governor thresholds; it never enables a provider.",
    )
    mode_help = {
        "economy": "Minimizes cost; only the most critical unresolved fields remain eligible.",
        "balanced": "Recommended default; local retry first with selective escalation eligibility.",
        "accuracy": "Higher local acceptance threshold and no accept-with-flag shortcut.",
    }
    selected_policy = workspace.mode_policy(mode)
    st.caption(f"{mode_help[mode]} Runtime accept threshold: "
               f"{selected_policy['accept_threshold']:.2f}; external calls enabled: No.")
    source = st.radio(
        "Input source", ["Single file", "Multiple files", "Local folder"], horizontal=True,
        disabled=running,
    )
    max_pages = int(os.environ.get("CLAIMROUTE_MAX_PAGES", "100"))
    items = []
    if source == "Single file":
        uploaded = st.file_uploader(
            "Choose one local file", type=None, key="workspace_single", disabled=running)
        items = _uploaded_items([uploaded] if uploaded else [], max_pages)
    elif source == "Multiple files":
        uploaded = st.file_uploader(
            "Choose local files", type=None, accept_multiple_files=True,
            key="workspace_multiple", disabled=running)
        items = _uploaded_items(uploaded, max_pages)
    else:
        folder = st.text_input(
            "Local dataset/folder path", key="workspace_folder_path", disabled=running)
        scan_columns = st.columns(3)
        scan_requested = scan_columns[0].button(
            "Scan folder", type="primary", disabled=running or not folder)
        retry_requested = scan_columns[1].button(
            "Retry Scan", disabled=running or not folder or
            (st.session_state.get("workspace_scan_state") or {}).get("state")
            != ScanState.SCAN_FAILED.value)
        if scan_columns[2].button("Clear", disabled=running):
            st.session_state.pop("workspace_inventory", None)
            st.session_state.pop("workspace_scan_state", None)
            st.rerun()
        scan_progress = st.progress(0)
        scan_status = st.empty()
        if scan_requested or retry_requested:
            scan_started = time.perf_counter()

            def on_scan(event):
                event["entered_path"] = folder
                st.session_state["workspace_scan_state"] = event
                discovered = int(event.get("files_discovered") or 0)
                scanned = int(event.get("files_scanned") or 0)
                scan_progress.progress(scanned / discovered if discovered else 0)
                scan_status.info(
                    f"Scanning is active Â· {event['state']} Â· "
                    f"{scanned}/{discovered} files Â· "
                    f"elapsed {time.perf_counter() - scan_started:.2f}s"
                )

            try:
                st.session_state["workspace_inventory"] = scan_folder(
                    folder, max_pages=max_pages, progress=on_scan)
            except IntakeError as exc:
                st.error(str(exc))
            except Exception:
                failure = {
                    "state": ScanState.SCAN_FAILED.value,
                    "entered_path": folder,
                    "elapsed_seconds": round(time.perf_counter() - scan_started, 3),
                    "error_reason": "Folder scan failed safely; review the local terminal log.",
                }
                st.session_state["workspace_scan_state"] = failure
                st.error(failure["error_reason"])
        _render_scan_state(st, st.session_state.get("workspace_scan_state"))
        items = st.session_state.get("workspace_inventory", [])
    if source != "Local folder":
        st.session_state["workspace_inventory"] = items

    st.subheader("File inventory")
    if not items:
        st.info("Add files or scan a folder to build the inventory.")
        _render_local_summary(st, st.session_state.get("workspace_batch"))
        return
    st.dataframe(_inventory_rows(items), hide_index=True, width="stretch")
    defaults = [item.safe_source_id for item in items
                if item.role == FileRole.CLAIM_DOCUMENT or (
                    workflow == "Evaluate Dataset" and item.role == FileRole.EXPECTED_OUTPUT)]
    selected_ids = st.multiselect(
        "Files included in this run", [item.safe_source_id for item in items],
        default=defaults,
        disabled=running,
        format_func=lambda source_id: next(
            item.filename for item in items if item.safe_source_id == source_id),
    )
    selected = [item for item in items if item.safe_source_id in selected_ids]

    st.subheader("Processing queue")
    st.caption("Processing is synchronous. Stop is honored between documents. Elapsed time "
               "updates at stage boundaries; the active spinner remains visible during OCR.")
    stop_after_first = st.checkbox(
        "Stop after the first document in this run", disabled=running)
    queue_slot = st.empty()
    progress_bar = st.progress(0)
    fingerprint = workspace._job_id(
        selected, f"{mode}:{workflow}") if selected else ""
    clicked = st.button(
        "Processing selected files…" if running else "Process selected files",
        type="primary", disabled=running or not selected,
    )
    if clicked and _queue_workspace_job(st.session_state, fingerprint):
        st.rerun()
    if running and st.session_state.get("workspace_pending_job") == fingerprint:
        processed = {"count": 0}
        processing_started = time.perf_counter()
        stage_slot = st.empty()

        def on_progress(index, total, result):
            processed["count"] = index
            progress_bar.progress(index / total)
            queue_slot.dataframe([{
                "Document": result["source_file"],
                "Status": result["processing_status"],
                "Warning": "; ".join(result["warnings"]),
            }], hide_index=True, width="stretch")

        def on_stage(event):
            st.session_state["workspace_stage"] = event
            elapsed = time.perf_counter() - processing_started
            page = (f" Â· page {event.get('current_page')}/{event.get('total_pages')}"
                    if event.get("current_page") else "")
            stage_slot.info(
                f"Processing is active Â· document {event['document_number']}/"
                f"{event['total_documents']} Â· current stage: "
                f"{event['stage'].replace('_', ' ').title()}{page} Â· "
                f"elapsed {elapsed:.2f}s Â· {event['message']}"
            )

        st.info(f"Processing {len(selected)} selected document(s). Please wait.")
        _run_workspace_job(
            st.session_state,
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
    if st.session_state.get("workspace_job_error"):
        st.error(st.session_state["workspace_job_error"])
    batch = st.session_state.get("workspace_batch")
    last_stage = st.session_state.get("workspace_stage")
    if last_stage and not running:
        st.caption(f"Last stage: {last_stage['stage']} Â· {last_stage['message']}")
    if batch:
        queue_slot.dataframe([{
            "Document": row["source_file"], "Status": row["processing_status"],
            "Warning": "; ".join(row["warnings"]),
        } for row in batch["documents"]], hide_index=True, width="stretch")
        _render_local_document(st, batch, items)
    else:
        st.info("Select supported claim documents, then start the queue.")
    _render_local_summary(st, batch)


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
