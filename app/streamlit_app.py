"""ClaimRoute Day 10 Streamlit demo."""
from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import service, workspace
from app.intake import FileRole, IntakeError, decode_pages, inspect_content, scan_folder


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


def _render_local_document(st, result, items):
    st.subheader("Document result")
    processed = [row for row in result.get("documents", [])
                 if row["processing_status"] in workspace.PRODUCED_OUTPUT]
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
    with evidence_tabs[2]:
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


def _render_local_summary(st, batch):
    st.subheader("Batch and evaluation summary")
    if not batch:
        st.info("Run the selected inventory to create a batch summary.")
        return
    summary = batch["summary"]
    columns = st.columns(6)
    for column, (label, value) in zip(columns, (
        ("Files", summary["files"]), ("Pages", summary["pages"]),
        ("Succeeded", summary["success"]), ("Partial", summary.get("partial", 0)),
        ("Failed", summary["failed"] + summary.get("failed_extraction", 0)),
        ("Unresolved", summary["unresolved_fields"]
         if summary["unresolved_fields"] is not None else "Unknown"),
    )):
        column.metric(label, value)
    st.write({
        "document_types": summary["document_types"],
        "measured_cost_usd": summary["measured_cost_usd"],
        "projected_cost_usd": summary["projected_cost_usd"],
        "throughput_pages_per_minute": summary["throughput_pages_per_minute"],
    })
    if batch.get("evaluation"):
        evaluation = batch["evaluation"]
        left, right = st.columns(2)
        left.metric("Field accuracy", _fmt_pct(evaluation["accuracy"] or 0))
        right.metric("Critical accuracy", _fmt_pct(evaluation["critical_accuracy"] or 0))
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
        if st.button("Scan folder", type="primary", disabled=running):
            try:
                st.session_state["workspace_inventory"] = scan_folder(
                    folder, max_pages=max_pages)
            except IntakeError as exc:
                st.error(str(exc))
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
    st.caption("Processing is synchronous. Optional stop is honored between documents.")
    stop_after_first = st.checkbox(
        "Stop after the first document in this run", disabled=running)
    queue_slot = st.empty()
    progress_bar = st.progress(0)
    fingerprint = workspace._job_id(
        selected, f"{service.DEFAULT_MODE}:{workflow}") if selected else ""
    clicked = st.button(
        "Processing selected files…" if running else "Process selected files",
        type="primary", disabled=running or not selected,
    )
    if clicked and _queue_workspace_job(st.session_state, fingerprint):
        st.rerun()
    if running and st.session_state.get("workspace_pending_job") == fingerprint:
        processed = {"count": 0}

        def on_progress(index, total, result):
            processed["count"] = index
            progress_bar.progress(index / total)
            queue_slot.dataframe([{
                "Document": result["source_file"],
                "Status": result["processing_status"],
                "Warning": "; ".join(result["warnings"]),
            }], hide_index=True, width="stretch")

        st.info(f"Processing {len(selected)} selected document(s). Please wait.")
        _run_workspace_job(
            st.session_state,
            fingerprint,
            lambda: workspace.run_batch(
                selected,
                evaluate=workflow == "Evaluate Dataset",
                progress=on_progress,
                stop_requested=lambda: stop_after_first and processed["count"] >= 1,
            ),
        )
        st.rerun()
    if st.session_state.get("workspace_job_error"):
        st.error(st.session_state["workspace_job_error"])
    batch = st.session_state.get("workspace_batch")
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
