"""Judge-facing dashboard data contracts.

Presentation shaping only. Every value returned here is read from a batch
receipt that ``app.workspace`` already produced, from ``LiveCallGovernor``
session reporting, or from a live runtime probe. Nothing in this module invents
a counter, and no money arithmetic happens here - projections are computed in
``workspace.cost_dashboard_metrics`` and only re-labelled for display.

Streamlit is deliberately not imported, so the whole dashboard contract is
testable without a browser session.
"""
from __future__ import annotations

from collections import Counter


ENVIRONMENT_LABELS = {
    "local_workspace": "Local Workspace",
    "public_synthetic": "Synthetic Demo",
}

ESCALATIONS_EMPTY_STATE = "No field escalations in the current run."

HEALTH_STATES = (
    "Healthy", "Available", "Disabled by policy", "Not configured",
    "Warning", "Unavailable",
)

# Display order maps onto the real route a field takes, not the reference
# picture's generic funnel.
_PROJECTION_SCALES = (
    ("one_million_pages", "1M pages"),
    ("ten_million_pages", "10M pages"),
    ("hundred_million_pages", "100M pages"),
)


def environment_label(app_mode: str) -> str:
    return ENVIRONMENT_LABELS.get(app_mode, "Local Workspace")


# What the screen says when a number was never measured. A LABEL, produced at
# render time. It is deliberately not stored in any numeric contract: a display
# string living in a token field is what took this page down in the first place.
NOT_MEASURED = "Not measured"

# Values a provider, a stored session, or a legacy receipt might use to mean
# "no number here". Matched case-insensitively after stripping. They are read,
# never written.
_UNAVAILABLE_TEXT = frozenset({
    "", "-", "--", "n/a", "na", "none", "null", "nil",
    "unknown", "not measured", "not available", "not configured",
})


def safe_optional_int(value) -> int | None:
    """-> an int, or None when the value is unavailable or not a count.

    `int()` is not a parser and must not be used as one on provider metadata.
    It raises on any non-numeric string, which is how "unknown" in a token field
    became a ValueError that took down the whole Cost tab. It also accepts
    booleans silently — `int(True)` is 1 — so a flag that arrived in the wrong
    field would become a token count nobody could trace back.

    This returns None for anything it cannot read as a whole number, and never
    guesses. 0 is preserved as the measurement it is: "measured zero" and "never
    measured" are different facts, and `value or 0` erased the difference.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # A non-integral or non-finite token count is malformed, not roundable.
        # Rounding would invent a precision the provider never reported.
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _UNAVAILABLE_TEXT:
            return None
        try:
            return int(text)
        except ValueError:
            pass
        parsed = safe_optional_float(text)
        return int(parsed) if parsed is not None and parsed.is_integer() else None
    return None


def safe_optional_float(value) -> float | None:
    """-> a finite float, or None when the value is unavailable or not a number.

    Same contract as :func:`safe_optional_int`. NaN and infinity are refused:
    both propagate silently through arithmetic and comparisons, so a single
    malformed cost figure would poison every total derived from it.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.lower() in _UNAVAILABLE_TEXT:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def measured_or_label(value, label: str = NOT_MEASURED):
    """The rendering rule, in one place: a number, or the honest label."""
    return label if value is None else value


def _int(value) -> int:
    """A counter that defaults to zero.

    For values the application itself produced and which are genuinely a count
    of things that happened — documents processed, calls made. Unreadable input
    counts as none-of-them rather than raising, because a malformed field in one
    row must not take down a page summarising every other row. Provider-reported
    numbers use ``safe_optional_int`` instead, where absent must stay absent.
    """
    parsed = safe_optional_int(value)
    return parsed if parsed is not None else 0


def _ratio(numerator, denominator):
    denominator = _int(denominator)
    return _int(numerator) / denominator if denominator else None


def _usd(cost: dict | None):
    return (cost or {}).get("value_usd")


def _usd_float(cost: dict | None) -> float:
    """A cost component as a float, treating unreadable as zero for a total.

    Zero is correct HERE and only here: these rows partition a measured total
    that was computed elsewhere, so a component nobody could read contributes
    nothing to the sum rather than aborting the table. The basis column still
    carries what kind of number it is.
    """
    return safe_optional_float(_usd(cost)) or 0.0


# --------------------------------------------------------------- summary cards

def summary_cards(summary: dict) -> list[dict]:
    """The six headline numbers, each carrying the denominator it belongs to.

    Accuracy is deliberately absent: without ground truth the honest headline is
    validated coverage, and Evaluate Dataset owns the accuracy surface.
    """
    applicable = _int(summary.get("applicable_fields"))
    validated = _int(summary.get("validated_fields"))
    coverage = _ratio(validated, applicable)
    return [
        {"label": "Documents processed", "value": _int(summary.get("files")),
         "kind": "count", "basis": "MEASURED",
         "detail": f"{_int(summary.get('success'))} completed, "
                   f"{_int(summary.get('partial'))} partial"},
        {"label": "Pages processed", "value": _int(summary.get("pages")),
         "kind": "count", "basis": "MEASURED",
         "detail": f"{float(summary.get('throughput_pages_per_minute') or 0):.2f}"
                   " pages/min measured"},
        {"label": "Fields produced", "value": _int(summary.get("fields_produced")),
         "kind": "count", "basis": "MEASURED",
         "detail": f"of {applicable} applicable fields" if applicable
                   else "No applicable fields yet"},
        {"label": "Validated coverage", "value": coverage,
         "kind": "percent", "basis": "MEASURED",
         "detail": f"{validated} of {applicable} applicable fields" if applicable
                   else "No applicable fields yet"},
        {"label": "Measured automated cost",
         "value": float(summary.get("measured_cost_usd") or 0),
         "kind": "usd", "basis": "MEASURED",
         "detail": "External spend is included only when a call was made"},
        {"label": "Human review required",
         "value": _int(summary.get("human_review_required")),
         "kind": "count", "basis": "MEASURED",
         "detail": f"{_int(summary.get('human_review_completed'))} corrected in "
                   "this session"},
    ]


# ---------------------------------------------------------------------- funnel

def funnel_stages(summary: dict, cost_dashboard: dict | None = None) -> list[dict]:
    """The actual route, with documents and fields kept in separate units.

    Mixing them is the specific dishonesty this shape prevents: uploaded
    documents and extracted fields never share a denominator.
    """
    counters = (cost_dashboard or {}).get("counters") or {}
    files = _int(summary.get("files"))
    applicable = _int(summary.get("applicable_fields"))
    retried = _int(summary.get("retry_attempted"))
    eligible = _int(counters.get("multimodal_eligible_fields"))
    return [
        {"stage": "Uploaded", "unit": "documents", "value": files,
         "denominator": files, "detail": "documents in this run"},
        {"stage": "Primary OCR", "unit": "fields",
         "value": _int(summary.get("primary_resolved")), "denominator": applicable,
         "detail": "resolved at the primary local rung"},
        {"stage": "Validated", "unit": "fields",
         "value": _int(summary.get("validated_fields")), "denominator": applicable,
         "detail": "resolved and validated"},
        {"stage": "Local retry", "unit": "fields",
         "value": _int(summary.get("retry_resolved")), "denominator": retried,
         "detail": "resolved of the fields sent to local retry"},
        {"stage": "Multimodal eligible", "unit": "fields", "value": eligible,
         "denominator": applicable, "detail": "eligible under field policy"},
        {"stage": "Multimodal attempted", "unit": "fields",
         "value": _int(summary.get("multimodal_attempted")), "denominator": eligible,
         "detail": "attempted of the eligible fields"},
        {"stage": "Human review", "unit": "fields",
         "value": _int(summary.get("human_review_required")), "denominator": applicable,
         "detail": "routed to a human"},
        {"stage": "Completed", "unit": "documents",
         "value": _int(summary.get("success")), "denominator": files,
         "detail": "documents with no unresolved field"},
    ]


def coverage_progress(summary: dict) -> dict:
    applicable = _int(summary.get("applicable_fields"))
    validated = _int(summary.get("validated_fields"))
    value = _ratio(validated, applicable)
    if value is None:
        return {"label": "Validated coverage", "value": None,
                "caption": "Unavailable - no applicable fields have been established"}
    return {
        "label": "Validated coverage",
        "value": value,
        "caption": f"{validated} of {applicable} applicable fields validated",
    }


# -------------------------------------------------------------- cost breakdown

_MEASURED_COMPONENTS = (
    ("primary_ocr", "Primary OCR"),
    ("retry_ocr", "Retry processing"),
    ("local_compute_other", "Other local compute"),
    ("multimodal_input_tokens", "Multimodal input (external)"),
    ("multimodal_output_tokens", "Multimodal output (external)"),
)


def cost_breakdown_rows(cost_dashboard: dict) -> list[dict]:
    """Measured components first, then the projection, then the assumption.

    The measured rows partition the measured total exactly, so the table can be
    summed without double counting ``local_compute`` (which is itself a total).
    """
    components = cost_dashboard.get("components") or {}
    rows = [{
        "label": label,
        "value_usd": _usd_float(components.get(key)),
        "basis": (components.get(key) or {}).get("basis", "MEASURED"),
        "group": "measured",
    } for key, label in _MEASURED_COMPONENTS]
    projected = components.get("projected_api") or {}
    rows.append({
        "label": "Selective AI cost",
        "value_usd": _usd_float(projected),
        "basis": projected.get("basis", "PROJECTED"),
        "group": "projected",
    })
    review = (cost_dashboard.get("human_review_estimate") or {}).get("total") or {}
    rows.append({
        "label": "Human review",
        "value_usd": _usd_float(review),
        "basis": review.get("basis", "ASSUMED"),
        "group": "assumed",
    })
    return rows


def measured_total(cost_dashboard: dict) -> float:
    components = cost_dashboard.get("components") or {}
    return _usd_float(components.get("total_automated"))


# ------------------------------------------------------------ recent documents

def recent_document_rows(documents: list[dict]) -> list[dict]:
    """One row per document actually present in the workspace session."""
    return [{
        "safe_source_id": row.get("safe_source_id"),
        "Document": row.get("source_file"),
        "Type": row.get("document_type") or "Unknown",
        "Pages": _int(row.get("page_count")),
        "Status": row.get("processing_status") or "QUEUED",
        "Stage": row.get("processing_stage") or row.get("processing_status") or "QUEUED",
        "Validated coverage": (row.get("coverage") or {}).get("validated_coverage"),
        "Unresolved": _int(row.get("unresolved_fields")),
        "Total cost": safe_optional_float(
            (row.get("measured_cost") or {}).get("usd")) or 0.0,
        "Processing time": round(
            (safe_optional_float(
                (row.get("latency") or {}).get("milliseconds")) or 0.0) / 1000, 2),
    } for row in documents]


# ------------------------------------------------------- escalations by field

def escalations_by_field(summary: dict) -> list[dict]:
    """Counted from the unresolved items the batch actually recorded."""
    items = summary.get("unresolved_items") or []
    counts = Counter(str(item.get("field_name") or "") for item in items)
    total = sum(counts.values())
    if not total:
        return []
    return [{
        "field_name": name,
        "count": count,
        "share": count / total,
    } for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


# ------------------------------------------------------------- provider panel

def provider_panel_rows(provider_state: dict, *, session_report: dict | None = None,
                        calls_used: int = 0, usage: dict | None = None,
                        latency_ms: float | None = None) -> list[dict]:
    """Configured provider facts and measured usage. Never a model leaderboard.

    Anything not measured says so rather than showing a zero that reads like a
    result.

    Every provider-reported number is read through ``safe_optional_int`` /
    ``safe_optional_float``. Providers report different subsets, a stored
    session can carry a receipt written by an older contract, and neither is
    something this panel gets to assume. One unreadable field renders as
    "Not measured"; it does not take down the tab, and it does not become a 0
    that would read as a measurement nobody made.
    """
    report = session_report or {}
    usage = usage if isinstance(usage, dict) else {}
    measured_calls = _int(report.get("calls_made")) or _int(calls_used)
    spend = safe_optional_float(report.get("measured_incremental_usd"))
    limits = report.get("limits")
    limit = safe_optional_float(
        (limits or {}).get("max_session_spend_usd")
        if isinstance(limits, dict) else None)
    latency_s = safe_optional_float(latency_ms)
    input_tokens = safe_optional_int(usage.get("input_tokens"))
    output_tokens = safe_optional_int(usage.get("output_tokens"))
    return [
        {"label": "Configured provider", "kind": "text",
         "value": provider_state.get("provider_name") or "Not configured"},
        {"label": "Configured model", "kind": "text",
         "value": provider_state.get("configured_model") or "Not configured"},
        {"label": "Provider enabled", "kind": "bool",
         "value": bool(provider_state.get("provider_enabled"))},
        {"label": "Credential available", "kind": "bool",
         "value": bool(provider_state.get("credential_available"))},
        {"label": "Calls used", "kind": "text",
         "value": f"{_int(calls_used)} / {UI_CALL_BUDGET}"},
        {"label": "Measured external calls", "kind": "count",
         "value": measured_calls},
        {"label": "Measured input tokens", "kind": "count",
         "value": measured_or_label(input_tokens if measured_calls else None)},
        {"label": "Measured output tokens", "kind": "count",
         "value": measured_or_label(output_tokens if measured_calls else None)},
        {"label": "Measured external spend", "kind": "usd",
         "value": measured_or_label(spend if measured_calls else None)},
        {"label": "Average latency", "kind": "seconds",
         "value": measured_or_label(
             round(latency_s / 1000, 3) if measured_calls and latency_s else None)},
        {"label": "Session spend limit", "kind": "usd",
         "value": measured_or_label(limit, "Not configured")},
        {"label": "Reason not attempted", "kind": "text",
         "value": provider_state.get("reason_not_attempted") or "-"},
    ]


# The UI permits exactly one governed paid call per session; mirrored here for
# display only. ``multimodal_permission.UI_MAX_CALLS`` remains the authority.
UI_CALL_BUDGET = 1


def provider_panel_note(*, calls_used: int) -> str:
    if _int(calls_used):
        return ("Measured synthetic smoke test - not a comparative model "
                "benchmark.")
    return "No external provider call has been made in this session."


# ---------------------------------------------------------------- projections

def projection_rows(cost_dashboard: dict) -> list[dict]:
    """Re-label the projections workspace already computed. No maths here."""
    automated = cost_dashboard.get("enterprise_projection") or {}
    review = cost_dashboard.get("human_review_projection") or {}
    total = cost_dashboard.get("total_projection") or {}
    rows = []
    for key, label in _PROJECTION_SCALES:
        if key not in automated:
            continue
        rows.append({
            "scale": label,
            "automated_usd": _usd(automated.get(key)),
            "automated_basis": (automated.get(key) or {}).get("basis", "PROJECTED"),
            "human_review_usd": _usd(review.get(key)),
            "human_review_basis": (review.get(key) or {}).get("basis", "ASSUMED"),
            "total_usd": _usd(total.get(key)),
            "total_basis": (total.get(key) or {}).get("basis", "PROJECTED + ASSUMED"),
        })
    return rows


PROJECTION_ASSUMPTION = (
    "Automated cost is PROJECTED from this run's measured cost per page. "
    "Human review is an ASSUMED rate applied to the fields this run actually "
    "routed to a human. Neither is a capacity proof."
)


# -------------------------------------------------------------- system health

def system_health(*, ocr_binary: str | None, validator_fields: int,
                  provider_state: dict, workspace_ready: bool) -> list[dict]:
    """Only components this process can actually verify.

    Database, queue workers, and a hosted multimodal gateway are roadmap
    infrastructure. They are absent here because claiming they are healthy
    would be a claim about services that are not deployed.
    """
    return [
        {"component": "Streamlit app", "state": "Healthy",
         "detail": "Rendering this session"},
        {"component": "Local OCR engine",
         "state": "Available" if ocr_binary else "Unavailable",
         "detail": ocr_binary or
                   "tesseract binary not found on PATH or in the standard locations"},
        {"component": "Validator configuration",
         "state": "Available" if validator_fields else "Warning",
         "detail": f"{validator_fields} field policies loaded" if validator_fields
                   else "No field policy was loaded"},
        {"component": "Provider policy",
         "state": "Available" if provider_state.get("provider_name")
                  else "Not configured",
         "detail": provider_state.get("provider_name") or "No provider configured"},
        {"component": "External provider",
         "state": "Available" if provider_state.get("provider_enabled")
                  else "Disabled by policy",
         "detail": provider_state.get("reason_not_attempted") or "-"},
        {"component": "Provider credential",
         "state": "Available" if provider_state.get("credential_available")
                  else "Not configured",
         "detail": "Read from the environment; never displayed"},
        {"component": "Workspace session",
         "state": "Available" if workspace_ready else "Warning",
         "detail": "Session state initialised" if workspace_ready
                   else "Session state has not been initialised"},
    ]


def probe_runtime() -> dict:
    """Read the real environment. Imports are local: this touches config files."""
    from app import workspace
    from engine import governor
    from engine.ocr import tesseract_engine

    return {
        "ocr_binary": tesseract_engine._resolve_binary(),
        "validator_fields": len(governor._FIELDS),
        "provider_state": workspace._provider_policy_snapshot(),
    }
