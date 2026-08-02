"""What the operator actually reads, and the navigation that must survive.

The regressions these cover:

- Every blocked provider state rendered as one message, so an operator who had
  exported CLAIMROUTE_MULTIMODAL_ENABLED and restarted saw exactly what a fresh
  clone saw and had nothing to act on.
- The Dashboard destination disappearing from the workspace, taking the
  judge-facing session metrics with it.

No test here can make a network call: the shipped configuration keeps the live
path closed and every assertion is on rendered text.
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from app import streamlit_app, workspace
from engine.escalation.readiness import ReadinessState

FAKE_KEY = "test-key-not-a-credential"


def _app(monkeypatch, *, tab="Results", env=None, state=None):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    for name in ("CLAIMROUTE_MULTIMODAL_ENABLED", "CLAIMROUTE_LIVE_PROVIDER_TEST",
                 "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
    if state is not None:
        app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.session_state["cr_workspace_tabs"] = tab
    app.run(timeout=60)
    return app


def _text(app) -> str:
    return "\n".join([row.value for row in app.markdown]
                     + [row.value for row in app.info]
                     + [row.value for row in app.caption]
                     + [row.value for row in app.warning])


# ------------------------------------------------------------- navigation


def test_the_three_workspace_destinations_are_all_present():
    """Dashboard was restored WITHOUT removing the processing workspace."""
    assert "Dashboard" in streamlit_app.WORKSPACE_TABS
    assert "Intake & Run" in streamlit_app.WORKSPACE_TABS
    assert "Results" in streamlit_app.WORKSPACE_TABS
    assert "Human Review" in streamlit_app.WORKSPACE_TABS


def test_process_documents_and_evaluate_dataset_both_remain_selectable(monkeypatch):
    app = _app(monkeypatch, tab="Intake & Run")

    workflow = next(row for row in app.radio if row.label == "Workflow")
    assert list(workflow.options) == ["Process Documents", "Evaluate Dataset"]
    assert not app.exception


def test_dashboard_renders_with_zero_documents(monkeypatch):
    app = _app(monkeypatch, tab="Dashboard")

    assert not app.exception


# --------------------------------------------------- provider state on screen


def test_the_rail_does_not_say_disabled_when_only_live_permission_is_missing(
        monkeypatch):
    """The reported symptom, asserted on rendered text.

    Credentials present and the adapter flag exported: the one remaining switch
    is the live-test flag, and the rail must say so instead of reporting the
    whole provider as disabled.
    """
    app = _app(monkeypatch, tab="Dashboard",
               env={"OPENROUTER_API_KEY": FAKE_KEY,
                    "CLAIMROUTE_MULTIMODAL_ENABLED": "true"})
    rail = next(row.value for row in app.markdown
                if 'class="cr-rail-status' in row.value)

    assert "External providers disabled" not in rail
    assert "live-test permission" in rail.lower()
    assert not app.exception


def test_the_rail_reports_a_missing_credential_as_a_credential_problem(monkeypatch):
    app = _app(monkeypatch, tab="Dashboard",
               env={"CLAIMROUTE_MULTIMODAL_ENABLED": "true",
                    "CLAIMROUTE_LIVE_PROVIDER_TEST": "true"})
    rail = next(row.value for row in app.markdown
                if 'class="cr-rail-status' in row.value)

    assert "credential missing" in rail.lower()
    assert not app.exception


def test_an_unconfigured_clone_still_reports_disabled_by_configuration(monkeypatch):
    """The shipped default must remain unambiguous, and must not be alarming."""
    app = _app(monkeypatch, tab="Dashboard")
    rail = next(row.value for row in app.markdown
                if 'class="cr-rail-status' in row.value)

    assert "disabled by configuration" in rail.lower()
    assert not app.exception


@pytest.mark.parametrize("env,expected", [
    ({}, ReadinessState.DISABLED),
    ({"OPENROUTER_API_KEY": FAKE_KEY}, ReadinessState.DISABLED),
    ({"OPENROUTER_API_KEY": FAKE_KEY, "CLAIMROUTE_MULTIMODAL_ENABLED": "true"},
     ReadinessState.TEST_PERMISSION_REQUIRED),
    ({"CLAIMROUTE_MULTIMODAL_ENABLED": "true",
      "CLAIMROUTE_LIVE_PROVIDER_TEST": "true"}, ReadinessState.MISSING_KEY),
])
def test_the_rendered_state_matches_the_backend_contract(monkeypatch, env, expected):
    """The UI renders the backend verdict; it never derives one of its own."""
    for name in ("CLAIMROUTE_MULTIMODAL_ENABLED", "CLAIMROUTE_LIVE_PROVIDER_TEST",
                 "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    snapshot = workspace._provider_policy_snapshot()

    assert snapshot["readiness_state"] == expected.value
    assert streamlit_app._READINESS_HEADLINES[expected]


def test_every_typed_state_has_its_own_headline():
    """A state with no headline would inherit another state's wording, which is
    the exact class of defect this replaces."""
    headlines = streamlit_app._READINESS_HEADLINES

    assert set(headlines) == set(ReadinessState)
    assert len(set(headlines.values())) == len(ReadinessState)


# ---------------------------------------------------------------- secrecy


def test_the_key_is_never_rendered_anywhere_on_the_page(monkeypatch):
    app = _app(monkeypatch, tab="Dashboard",
               env={"OPENROUTER_API_KEY": FAKE_KEY,
                    "CLAIMROUTE_MULTIMODAL_ENABLED": "true",
                    "CLAIMROUTE_LIVE_PROVIDER_TEST": "true"})
    rendered = _text(app)

    assert FAKE_KEY not in rendered
    assert FAKE_KEY[:8] not in rendered
    assert not app.exception


def test_diagnostics_report_presence_without_the_value(monkeypatch):
    """The expander must be useful and still safe."""
    from engine.escalation.client import load_config
    from engine.escalation.readiness import evaluate_readiness

    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("CLAIMROUTE_MULTIMODAL_ENABLED", "true")
    monkeypatch.delenv("CLAIMROUTE_LIVE_PROVIDER_TEST", raising=False)

    diagnostics = evaluate_readiness(config=load_config(),
                                     mode="balanced").diagnostics()

    assert diagnostics["OPENROUTER_API_KEY_PRESENT"] is True
    assert diagnostics["CLAIMROUTE_LIVE_PROVIDER_TEST"] is False
    assert diagnostics["BLOCKING_REASON"] == "TEST_PERMISSION_REQUIRED"
    assert FAKE_KEY not in repr(diagnostics)


# ------------------------------------------------------------- resilience


def test_a_provider_initialization_failure_does_not_crash_the_page(monkeypatch):
    """A broken provider must cost the provider panel, not the local results
    already produced. The readiness call is on the sidebar path, which every tab
    renders, so an exception here would take the whole workspace with it."""
    def explode(**kwargs):
        raise RuntimeError("synthetic initialization failure")

    monkeypatch.setattr(workspace, "evaluate_readiness", explode)
    app = _app(monkeypatch, tab="Intake & Run")

    assert not app.exception
    snapshot = workspace._provider_policy_snapshot()
    assert snapshot["readiness_state"] == ReadinessState.INITIALIZATION_ERROR.value
    assert snapshot["provider_ready"] is False


def test_local_processing_controls_remain_available_with_the_provider_off(
        monkeypatch):
    """Nothing about an unavailable provider may disable local work."""
    app = _app(monkeypatch, tab="Intake & Run")

    modes = next(row for row in app.selectbox if row.label == "Operating mode")
    assert modes.disabled is False
    assert not app.exception
