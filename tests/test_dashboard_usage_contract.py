"""Unknown token counts are unknown, not zero, and never a string in a number.

THE DEFECT THESE COVER. `UsageMetadata` declares `Optional[int]` and documents
"None means UNKNOWN and stays unknown" — and then its `to_dict()` replaced every
None with the STRING "unknown" on the way out. The dataclass was right; the
serialiser silently changed the type of the field it was serialising. The Cost
tab read that dict, called `int("unknown")`, and took the whole page down with a
ValueError.

WHY IT SURFACED ONLY NOW. The sentinel is older than the activation work — it is
present at a7d49ac and was introduced with the adapter itself. It was
unreachable because no live call could ever complete, so `called_provider` was
never true and the panel never looked at a usage dict. Opening the live path
made a latent contract mismatch a crash. It is still a real defect, and the fix
belongs at the contract, not at the call site that happened to find it.

THE RULE THIS RESTORES. A missing token count must never become 0 — zero reads
as a measurement, and an unmetered call that appears to cost nothing is how a
budget check passes something it should have stopped. Unknown stays unknown all
the way to the screen, where it is RENDERED as "Not measured" rather than
STORED as it.

`int()` is not a parser. It accepts booleans (True -> 1), so a malformed
provider field could quietly become a token count, and it raises on everything
else. Both behaviours are wrong for reading provider metadata, which is why the
helpers below return None rather than guessing or exploding.

No test here makes a network call or needs a credential.
"""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from app import dashboard, service, streamlit_app, workspace
from app.intake import inspect_content
from engine.escalation.contract import CostBreakdown, UsageMetadata
from engine.schemas import Attempt, FieldResult, FieldState, PageResult

PROVIDER_STATE = {
    "provider_name": "openrouter",
    "configured_model": "google/gemini-3.5-flash-lite",
    "provider_enabled": True,
    "credential_available": True,
    "reason_not_attempted": "-",
}


def _values(rows: list[dict]) -> dict:
    return {row["label"]: row["value"] for row in rows}


# ------------------------------------------------------------ the helpers


@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("", None),
    ("   ", None),
    ("Not measured", None),
    ("unknown", None),
    ("123", 123),
    (123, 123),
    (12.0, 12),
    (0, 0),
    (True, None),
    (False, None),
])
def test_safe_optional_int_never_guesses(raw, expected):
    assert dashboard.safe_optional_int(raw) is expected or \
        dashboard.safe_optional_int(raw) == expected


def test_zero_is_a_measurement_and_survives():
    """0 is a real count. `value or 0` erased the difference between "measured
    zero" and "never measured", which is exactly the distinction this panel
    exists to preserve."""
    assert dashboard.safe_optional_int(0) == 0
    assert dashboard.safe_optional_int(None) is None


def test_booleans_are_refused_rather_than_counted():
    """bool is a subclass of int, so int(True) is 1 and passes every numeric
    check. A provider field that arrived as a flag would become a token count
    nobody can trace."""
    assert dashboard.safe_optional_int(True) is None
    assert dashboard.safe_optional_float(True) is None


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("Not measured", None), ("unknown", None),
    ("1.5", 1.5), (1.5, 1.5), (2, 2.0), (True, None),
    (float("nan"), None), (float("inf"), None),
])
def test_safe_optional_float_never_guesses(raw, expected):
    result = dashboard.safe_optional_float(raw)
    assert result == expected if expected is not None else result is None


def test_a_non_integral_float_is_not_a_token_count():
    """12.5 tokens is not a thing. Rounding it would invent a precision the
    provider never reported, so it is refused like any other malformed value."""
    assert dashboard.safe_optional_int(12.5) is None


# ------------------------------------------------- the corrected contract


def test_unknown_token_counts_serialise_as_null_not_as_a_string():
    """The contract fix. None in, None out — the serialiser no longer changes
    the type of the field. Still never zero: that was always the point."""
    usage = UsageMetadata(input_tokens=430, output_tokens=24).to_dict()

    assert usage["input_tokens"] == 430
    assert usage["image_tokens"] is None
    assert usage["cached_tokens"] is None
    assert usage["reasoning_tokens"] is None
    # The load-bearing guarantee, unchanged: absent is never 0.
    assert usage["image_tokens"] != 0


def test_the_usage_contract_round_trips_through_json():
    """Receipts are serialised into exports and audit records. `null` is a real
    JSON value; "unknown" in an integer field is a type error waiting for a
    reader that trusts the schema."""
    payload = json.loads(json.dumps(UsageMetadata(input_tokens=10).to_dict()))

    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] is None


# ------------------------------------------------------- the provider panel


def test_1_no_provider_calls_reports_not_measured():
    rows = _values(dashboard.provider_panel_rows(PROVIDER_STATE, calls_used=0))

    assert rows["Measured input tokens"] == "Not measured"
    assert rows["Measured external calls"] == 0


def test_2_provider_configured_but_zero_measured_calls():
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, session_report={"calls_made": 0}, calls_used=0,
        usage=UsageMetadata().to_dict()))

    assert rows["Configured provider"] == "openrouter"
    assert rows["Measured output tokens"] == "Not measured"
    assert rows["Measured external spend"] == "Not measured"


def test_3_measured_call_with_numeric_token_values():
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, session_report={"calls_made": 1,
                                        "measured_incremental_usd": 0.000004},
        calls_used=1, usage={"input_tokens": 120, "output_tokens": 8},
        latency_ms=11.0))

    assert rows["Measured input tokens"] == 120
    assert rows["Measured output tokens"] == 8
    assert rows["Measured external spend"] == 0.000004
    assert rows["Average latency"] == 0.011


def test_4_measured_call_with_input_tokens_none():
    """The reported crash, at its narrowest. A call happened; the provider did
    not say what it used."""
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, calls_used=1,
        usage={"input_tokens": None, "output_tokens": None}))

    assert rows["Measured input tokens"] == "Not measured"
    assert rows["Measured output tokens"] == "Not measured"


def test_5_measured_call_with_missing_token_keys():
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, calls_used=1, usage={}))

    assert rows["Measured input tokens"] == "Not measured"


def test_6_the_legacy_string_sentinel_does_not_reach_int():
    """Receipts written before the contract fix still carry the string. They
    must render, not crash — a stored session is not re-serialisable."""
    for sentinel in ("unknown", "Not measured", "n/a", "-"):
        rows = _values(dashboard.provider_panel_rows(
            PROVIDER_STATE, calls_used=1,
            usage={"input_tokens": sentinel, "output_tokens": sentinel}))

        assert rows["Measured input tokens"] == "Not measured", sentinel


def test_7_mixed_numeric_and_unavailable_fields_render_side_by_side():
    """The realistic shape: OpenRouter reports prompt and completion tokens and
    says nothing about image tokens. One unavailable field must not suppress a
    measured one."""
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, calls_used=1,
        usage={"input_tokens": 120, "output_tokens": None}))

    assert rows["Measured input tokens"] == 120
    assert rows["Measured output tokens"] == "Not measured"


def test_8_malformed_metadata_does_not_crash_the_panel():
    """Whatever a provider or a stored session hands over, the panel renders."""
    for broken in ({"input_tokens": {"nested": 1}}, {"input_tokens": []},
                   {"input_tokens": object()}, {"input_tokens": "1e9999"},
                   {"input_tokens": float("nan")}):
        rows = _values(dashboard.provider_panel_rows(
            PROVIDER_STATE, calls_used=1, usage=broken))

        assert rows["Measured input tokens"] == "Not measured", broken


def test_a_malformed_session_report_does_not_crash_the_panel():
    rows = _values(dashboard.provider_panel_rows(
        PROVIDER_STATE, calls_used=1,
        session_report={"calls_made": "lots",
                        "measured_incremental_usd": "Not measured",
                        "limits": {"max_session_spend_usd": "none"}},
        usage={"input_tokens": 5, "output_tokens": 5},
        latency_ms="unknown"))

    assert rows["Session spend limit"] == "Not configured"
    assert rows["Average latency"] == "Not measured"


def test_9_measured_and_projected_cost_stay_separate():
    """The fix must not blur the basis columns. A projected number presented as
    measured is a claim about money that was never spent."""
    cost_dashboard = {
        "components": {
            "primary_ocr": {"value_usd": 0.001, "basis": "MEASURED"},
            "projected_api": {"value_usd": 0.02, "basis": "PROJECTED"},
            "total_automated": {"value_usd": 0.001, "basis": "MEASURED"},
        },
        "human_review_estimate": {"total": {"value_usd": 0.5, "basis": "ASSUMED"}},
    }

    rows = dashboard.cost_breakdown_rows(cost_dashboard)
    groups = {row["label"]: row["group"] for row in rows}

    assert groups["Primary OCR"] == "measured"
    assert groups["Selective AI cost"] == "projected"
    assert groups["Human review"] == "assumed"
    assert dashboard.measured_total(cost_dashboard) == 0.001


def test_cost_breakdown_survives_a_malformed_component():
    """One unreadable component must not take the Cost tab down either."""
    rows = dashboard.cost_breakdown_rows({
        "components": {"primary_ocr": {"value_usd": "Not measured"},
                       "retry_ocr": {"value_usd": None}}})

    assert all(isinstance(row["value_usd"], float) for row in rows)


# --------------------------------------------------------- rendered app


def _document_with_sentinel_receipt():
    """A session holding a completed call whose usage the provider never gave."""
    stream = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(stream, format="PNG")
    item = inspect_content("synthetic.png", stream.getvalue())
    page = PageResult(item.safe_source_id, "p1", "cms1500", quality_score=.9)
    field = FieldResult(item.safe_source_id, "p1", "billing_provider_npi", None,
                        FieldState.ESCALATE, .2, bbox=(30, 30, 100, 55))
    field.attempts = [Attempt("primary_ocr", "stub", None, .2)]
    page.fields = {field.field_name: field}
    page.decisions = {field.field_name: [("ESCALATE", "synthetic unresolved")]}
    batch = workspace.run_batch(
        [item], processor=lambda *_: workspace.process_item(
            item, page_processor=lambda *_: service.build_receipt(
                page, [], "balanced", 10, source_kind="local_workspace")))

    state = streamlit_app._new_workspace_state({})
    state["inventory"] = [item]
    state["selected_document_ids"] = [item.safe_source_id]
    streamlit_app._store_workspace_batch(state, batch)
    # Exactly what run_one_candidate writes: usage straight from the provider
    # result, cost with nothing reported.
    state["multimodal"]["receipts"]["fp"] = {
        "called_provider": True,
        "external_calls_made": 1,
        "measured_cost_usd": CostBreakdown(basis="unknown").billed_usd,
        "latency_ms": 11.0,
        "final_field_outcome": "HUMAN_REVIEW_REQUIRED",
        "usage": UsageMetadata().to_dict(),
    }
    return state


def test_10_every_workspace_tab_renders_with_an_unreported_usage_receipt(monkeypatch):
    """The end of the crash. Each tab is rendered with the exact session that
    produced the ValueError, including Cost, and each must come back clean."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    for tab in streamlit_app.WORKSPACE_TABS:
        app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
        app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = \
            _document_with_sentinel_receipt()
        app.session_state["cr_workspace_tabs"] = tab
        app.run(timeout=60)

        assert not app.exception, (
            f"{tab} raised "
            f"{[str(e.value) for e in app.exception]}")


def test_the_cost_tab_shows_not_measured_rather_than_a_fabricated_zero(monkeypatch):
    """A zero here would read as "the call was free", which is a claim about
    spending nobody measured."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = \
        _document_with_sentinel_receipt()
    app.session_state["cr_workspace_tabs"] = "Cost"
    app.run(timeout=60)

    assert not app.exception

    # Scoped to the provider panel. The readiness diagnostics table renders its
    # own legitimate "unknown" for an unselected input, which is a different
    # question with a different answer.
    panel = next(
        (rows for rows in (_frame_rows(frame) for frame in app.dataframe)
         if any(str(row.get("Property")) == "Measured input tokens"
                for row in rows if isinstance(row, dict))),
        None)
    assert panel is not None, "the provider panel did not render"
    tokens = {str(row["Property"]): str(row["Value"]) for row in panel}

    assert tokens["Measured input tokens"] == "Not measured"
    assert tokens["Measured output tokens"] == "Not measured"
    # Not a zero, and not the old string sentinel.
    assert tokens["Measured input tokens"] not in ("0", "unknown")


def _frame_rows(frame):
    data = frame.value
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    return data or []


def test_no_external_call_is_made_by_rendering(monkeypatch):
    """Rendering a dashboard must never open a socket. The panel reports on a
    call that already happened; it does not make one."""
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("the dashboard attempted a network call")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    rows = dashboard.provider_panel_rows(
        PROVIDER_STATE, calls_used=1, usage=UsageMetadata().to_dict())

    assert _values(rows)["Measured input tokens"] == "Not measured"
