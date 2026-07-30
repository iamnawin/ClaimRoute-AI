"""ClaimRoute Day 10 Streamlit demo."""
from __future__ import annotations

from pathlib import Path

from app import service


def _fmt_pct(value) -> str:
    return f"{float(value):.2%}"


def _fmt_usd(value) -> str:
    return f"${float(value):,.6f}"


def _shown(value, screenshot_safe: bool):
    if screenshot_safe and value not in (None, ""):
        return "[hidden]"
    return value


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


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="ClaimRoute AI", page_icon="CR", layout="wide")
    _style(st)
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
