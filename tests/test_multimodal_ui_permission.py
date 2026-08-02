"""The paid-call UI gate is consent-driven and never uses a real provider."""
from __future__ import annotations

import io

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


def test_streamlit_toggle_defaults_off_and_warning_appears_only_when_on(monkeypatch):
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = _workspace_ui_state()
    app.session_state["cr_workspace_tabs"] = "Results"
    app.run(timeout=30)

    toggle = next(row for row in app.toggle
                  if row.label == "Enable paid multimodal AI calls")
    action = next(row for row in app.button
                  if row.label == "Run one eligible synthetic field")
    assert toggle.value is False
    assert action.disabled is True
    assert any("AI calls disabled. No data will leave this machine." in row.value
               for row in app.info)

    toggle.set_value(True).run(timeout=30)
    assert any("Paid multimodal AI calls enabled" in row.value for row in app.warning)
    confirmation = next(row for row in app.checkbox
                        if row.label == "I understand that this may make a paid external API call.")
    assert confirmation.value is False
    assert next(row for row in app.button
                if row.label == "Run one eligible synthetic field").disabled is True


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

    assert any(row.value == "Paid-call limit reached" for row in app.error)
    assert next(row for row in app.button
                if row.label == "Run one eligible synthetic field").disabled is True
    assert state["multimodal"]["receipts"]["safe-fingerprint"][
        "external_calls_made"] == 1
