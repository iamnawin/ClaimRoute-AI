"""The paid-call UI gate is consent-driven and never uses a real provider."""
from __future__ import annotations

import io

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import multimodal_permission, service, streamlit_app, workspace
from app.intake import inspect_content
from engine.escalation.client import request_from_page
from engine.escalation.contract import (CostBreakdown, MultimodalResult,
                                        ParsedAnswer, UsageMetadata)
from engine.escalation.live_policy import LiveCallGovernor, LiveDecision
from engine.schemas import Attempt, FieldResult, FieldState, PageResult


def _config(*, key=True) -> tuple[dict, dict]:
    config = {
        "enabled": True,
        "request_policy": {
            "crop_only": True, "max_page_fraction": .25,
            "require_page_provenance": True, "synthetic_data_only": True,
        },
        "transport": {"max_attempts": 3, "retry_on_invalid_response": False},
        "providers": {"openrouter": {
            "kind": "openrouter_chat_completions",
            "model": "qwen/qwen3.7-flash", "api_key_env": "OPENROUTER_API_KEY",
        }},
        "live_provider": {
            "enabled": True, "provider": "openrouter",
            "live_test_env": "CLAIMROUTE_LIVE_PROVIDER_TEST",
            "model_allowlist": [{"id": "qwen/qwen3.7-flash", "vision": True}],
            "limits": {
                "max_calls_per_field": 1, "max_calls_per_page": 2,
                "max_calls_per_document": 3, "max_calls_per_batch": 5,
                "max_paid_attempts_per_field": 1,
                "max_session_spend_usd": .02,
                "max_document_spend_usd": .005,
                "allow_fallback_models": False,
                "allow_parallel_paid_calls": False,
                "allow_automatic_reruns": False,
            },
            "duplicate_policy": {"reuse_previous_result": True},
        },
    }
    env = {
        "CLAIMROUTE_MULTIMODAL_ENABLED": "true",
        "CLAIMROUTE_LIVE_PROVIDER_TEST": "true",
    }
    if key:
        env["OPENROUTER_API_KEY"] = "synthetic-test-key"
    return config, env


def _request(*, synthetic=True):
    page = Image.new("RGB", (400, 300), "white")
    return request_from_page(
        page, (30, 30, 100, 55), "billing_provider_npi",
        doc_id="synthetic-doc", page_id="p1", synthetic=synthetic)


def _result(request_id: str) -> MultimodalResult:
    return MultimodalResult(
        request_id=request_id, provider="openrouter",
        model="qwen/qwen3.7-flash", actual_model="qwen/qwen3.7-flash",
        field_name="billing_provider_npi",
        answer=ParsedAnswer("1234567893", True, .99),
        usage=UsageMetadata(input_tokens=10, output_tokens=5),
        cost=CostBreakdown(basis="provider_reported", reported_usd=.00001),
        latency_ms=12.5, attempts=1, called_provider=True,
        raw_sha256="safe-hash",
    )


def test_default_off_and_unconfirmed_states_make_zero_client_calls():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    request = _request()
    client_calls = []

    class NeverClient:
        def __init__(self, **kwargs):
            client_calls.append(kwargs)

    off, _ = multimodal_permission.run_one_candidate(
        request, enabled=False, confirmed=True, synthetic_attested=True,
        governor=governor, config=config, calls_used=0,
        client_factory=NeverClient)
    unconfirmed, _ = multimodal_permission.run_one_candidate(
        request, enabled=True, confirmed=False, synthetic_attested=True,
        governor=governor, config=config, calls_used=0,
        client_factory=NeverClient)

    assert off["external_calls_made"] == 0
    assert unconfirmed["external_calls_made"] == 0
    assert client_calls == []
    assert governor.calls_made == 0


def test_ineligible_candidate_is_refused_with_a_receipt_not_an_exception():
    """An unprovable crop is a refusal, not a crash.

    ``permission_status`` already contemplates ``request is None``, so the
    execution path must refuse it the same way and still leave a receipt. A
    traceback here would lose the audit record for a blocked attempt.
    """
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    client_calls = []

    class NeverClient:
        def __init__(self, **kwargs):
            client_calls.append(kwargs)

    receipt, value = multimodal_permission.run_one_candidate(
        None, enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=config, calls_used=0,
        client_factory=NeverClient)

    assert receipt["external_calls_made"] == 0
    assert receipt["final_field_outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert receipt["policy_decision"] == "BLOCKED_UI_PERMISSION"
    assert receipt["reason"] == "No eligible crop could be proven."
    assert receipt["field_name"] == ""
    assert receipt["synthetic_crop_only"] is False
    assert value is None
    assert client_calls == []
    assert governor.calls_made == 0


def test_missing_key_and_non_synthetic_input_block_action():
    config, no_key = _config(key=False)
    missing = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True,
        request=_request(), governor=LiveCallGovernor(config, env=no_key),
        calls_used=0)
    assert not missing.can_run
    assert missing.policy.decision is LiveDecision.BLOCKED_NO_API_KEY

    config, env = _config()
    non_synthetic = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True,
        request=_request(synthetic=False), governor=LiveCallGovernor(config, env=env),
        calls_used=0)
    assert not non_synthetic.can_run
    assert non_synthetic.policy.decision is LiveDecision.BLOCKED_NOT_SYNTHETIC


def test_call_limit_and_each_spend_limit_block_action():
    config, env = _config()
    request = _request()
    exhausted_calls = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True, request=request,
        governor=LiveCallGovernor(config, env=env), calls_used=1)
    assert exhausted_calls.reason == "Paid-call limit reached"

    session_governor = LiveCallGovernor(config, env=env)
    session_governor._counters.session_spend = .02
    session = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True, request=request,
        governor=session_governor, calls_used=0)
    assert session.policy.decision is LiveDecision.BLOCKED_SESSION_BUDGET

    document_governor = LiveCallGovernor(config, env=env)
    document_governor._counters.spend_per_document[request.doc_id] = .005
    document = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True, request=request,
        governor=document_governor, calls_used=0)
    assert document.policy.decision is LiveDecision.BLOCKED_DOCUMENT_BUDGET


def test_duplicate_fingerprint_blocks_action_without_mutating_preview():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    request = _request()
    allowed = governor.authorize(request)
    governor.record_call(allowed, _result(request.request_id))
    avoided_before = governor.paid_calls_avoided

    duplicate = multimodal_permission.permission_status(
        enabled=True, confirmed=True, synthetic_attested=True, request=request,
        governor=governor, calls_used=0)

    assert not duplicate.can_run
    assert duplicate.policy.decision is LiveDecision.REUSED_CACHED_RESULT
    assert governor.paid_calls_avoided == avoided_before


def test_one_fake_call_forces_no_retries_and_rerun_cannot_repeat_it():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    request = _request()
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["config"]["transport"]["max_attempts"] == 1
            assert kwargs["config"]["transport"]["retry_on_invalid_response"] is False

        def read_field(self, candidate):
            calls.append(candidate.request_id)
            return _result(candidate.request_id)

    receipt, value = multimodal_permission.run_one_candidate(
        request, enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=config, calls_used=0,
        provider_builder=lambda *args: object(), client_factory=FakeClient)
    rerun, repeated_value = multimodal_permission.run_one_candidate(
        request, enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=config, calls_used=1,
        provider_builder=lambda *args: object(), client_factory=FakeClient)

    assert receipt["external_calls_made"] == 1
    assert receipt["final_field_outcome"] == "ACCEPTED"
    assert "1234567893" not in str(receipt)
    assert value == "1234567893"
    assert rerun["external_calls_made"] == 0
    assert repeated_value is None
    assert calls == [request.request_id]


def _workspace_ui_state():
    page_image = Image.new("RGB", (400, 300), "white")
    stream = io.BytesIO()
    page_image.save(stream, format="PNG")
    item = inspect_content("synthetic.png", stream.getvalue())
    page = PageResult(item.safe_source_id, "p1", "cms1500", quality_score=.9)
    field = FieldResult(
        item.safe_source_id, "p1", "billing_provider_npi", None,
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
    return state


def test_no_enabled_looking_control_when_configuration_forbids_execution(monkeypatch):
    """The repository ships the live path disabled, so the UI must not offer consent.

    This runs against the REAL configs/multimodal_providers.yaml. Offering an
    enabled-looking paid-AI toggle there invited an operator to attest to
    synthetic data and confirm billing for a call that configuration refuses.
    The panel must state the blockers instead, and expose no toggle at all.
    """
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state()
    app.session_state["cr_workspace_tabs"] = "Results"
    app.run(timeout=30)

    assert not [row for row in app.toggle
                if row.label == "Enable paid multimodal AI calls"]
    action = next(row for row in app.button
                  if row.label == "Enablement requirements not satisfied")
    assert action.disabled is True
    assert any("External AI disabled" in row.value for row in app.info)
    # The consent checkboxes must not be reachable while execution is impossible.
    assert not [row for row in app.checkbox
                if row.label.startswith("I understand that this may make")]


def test_operating_modes_are_labelled_local_only_when_provider_disabled(monkeypatch):
    """Modes stay selectable, because they drive real local thresholds."""
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    # Case A of the enablement contract: no runtime flags, so the AI rung is
    # unavailable. Cleared explicitly because an exported flag would otherwise
    # silently change what this test is measuring.
    monkeypatch.delenv("CLAIMROUTE_MULTIMODAL_ENABLED", raising=False)
    monkeypatch.delenv("CLAIMROUTE_LIVE_PROVIDER_TEST", raising=False)
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state()
    app.run(timeout=30)

    selector = next(row for row in app.selectbox if row.label == "Operating mode")
    assert all("local policy active, AI rung unavailable" in str(option)
               for option in selector.options)
    # Every mode is still offered. The label narrows what is unavailable to the
    # AI rung rather than implying the whole control is inert, because the mode
    # sets the local accept/retry/flag thresholds the governor actually applies.
    assert len(selector.options) == len(service.MODE_LABELS)


def test_runtime_flags_make_the_rung_available_without_permitting_a_call(monkeypatch):
    """Case B: flags set, no credential.

    The panel must stop claiming policy forbids the rung, because it no longer
    does, and must name the credential as the specific remaining blocker. The
    two states are asserted separately so "available for inspection" can never
    be confused with "permitted to spend": external calls stay at zero here.
    """
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    monkeypatch.setenv("CLAIMROUTE_MULTIMODAL_ENABLED", "true")
    monkeypatch.setenv("CLAIMROUTE_LIVE_PROVIDER_TEST", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    state = workspace._provider_policy_snapshot()

    assert state["provider_enabled"] is True
    assert state["reason_not_attempted"] != "disabled by policy"
    assert state["credential_available"] is False
    assert state["external_call_attempted"] is False
    assert state["external_call_count"] == 0


def test_runtime_flags_never_override_the_shipped_config_for_execution(monkeypatch):
    """Flags enable inspection only. The governor still refuses the call.

    This is the load-bearing separation: if enabling the panel also enabled
    spending, an operator debugging the UI would start billing by accident.
    """
    monkeypatch.setenv("CLAIMROUTE_MULTIMODAL_ENABLED", "true")
    monkeypatch.setenv("CLAIMROUTE_LIVE_PROVIDER_TEST", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from engine.escalation.client import load_config

    config = load_config()
    # Shipped config is still false, so the live path stays shut regardless of
    # what the environment says.
    assert config["enabled"] is False
    assert config["live_provider"]["enabled"] is False


@pytest.mark.parametrize("value", ["", "false", "0", "no", "maybe", "TRUE-ish"])
def test_only_recognised_truth_values_enable_the_panel(monkeypatch, value):
    """A malformed flag is not an enable. Anything unrecognised means off."""
    monkeypatch.setenv("CLAIMROUTE_MULTIMODAL_ENABLED", value)
    monkeypatch.setenv("CLAIMROUTE_LIVE_PROVIDER_TEST", value)

    assert workspace._provider_policy_snapshot()["provider_enabled"] is False


def test_one_flag_alone_does_not_enable_the_panel(monkeypatch):
    """Both flags are required; either alone leaves the rung unavailable."""
    for present, absent in (("CLAIMROUTE_MULTIMODAL_ENABLED",
                             "CLAIMROUTE_LIVE_PROVIDER_TEST"),
                            ("CLAIMROUTE_LIVE_PROVIDER_TEST",
                             "CLAIMROUTE_MULTIMODAL_ENABLED")):
        monkeypatch.setenv(present, "true")
        monkeypatch.delenv(absent, raising=False)

        state = workspace._provider_policy_snapshot()

        assert state["provider_enabled"] is False, f"{present} alone enabled it"
        assert state["reason_not_attempted"] == "disabled by policy"


def test_streamlit_rerun_preserves_receipt_and_keeps_paid_action_disabled(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    state = _workspace_ui_state()
    source_id = state["selected_result_id"]
    state["multimodal"]["receipts"]["safe-fingerprint"] = {
        "external_calls_made": 1,
        "measured_cost_usd": .00001,
        "latency_ms": 12.5,
        "final_field_outcome": "ACCEPTED",
    }
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.session_state["cr_workspace_tabs"] = "Results"
    app.session_state[f"cr_multimodal_enabled_{source_id}"] = True

    app.run(timeout=30)
    app.run(timeout=30)

    # Enablement is unsatisfied under the shipped config, so the action stays
    # disabled and the prior receipt survives the rerun unchanged.
    assert next(row for row in app.button
                if row.label == "Enablement requirements not satisfied").disabled is True
    assert state["multimodal"]["receipts"]["safe-fingerprint"][
        "external_calls_made"] == 1
