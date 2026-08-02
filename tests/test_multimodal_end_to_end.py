"""The whole path, with only the socket replaced.

Every other test in this repository injects a fake at some seam above the wire:
a fake client, a fake provider object, a stubbed runner. Each of those proves a
layer and silently skips the layers below it, and the layers below are where a
real call actually goes wrong -- the OpenRouter payload shape, the response
envelope, the strict parser, grounding, healthcare validation, the receipt.

Here the ONLY substitution is ``urllib.request.urlopen``. Everything above it is
the production code path: the real ``build_provider``, the real
``OpenRouterProvider.invoke`` building the real request body, the real
``MultimodalClient`` with its retry bounds and cost accounting, the real
governor, the real validators, the real workspace mutation and the real
exports. If this passes and a live call still fails, the failure is in the
network or the provider account -- not in this code.

No test here can reach the network: the opener is replaced before any provider
is constructed, and one test asserts that an un-faked socket would be refused.
"""
from __future__ import annotations

import io
import json
import urllib.request

import pytest
from PIL import Image

from app import multimodal_permission, service, streamlit_app, workspace
from app.intake import inspect_content
from engine.escalation.client import load_config, request_from_page
from engine.escalation.live_policy import (LIVE_CONFIG_ENABLED_ENV,
                                           LiveCallGovernor)
from engine.schemas import Attempt, FieldResult, FieldState, PageResult

KEY = "OPENROUTER_API_KEY"
ENABLE = "CLAIMROUTE_MULTIMODAL_ENABLED"
LIVE_TEST = "CLAIMROUTE_LIVE_PROVIDER_TEST"
FAKE_KEY = "test-key-not-a-credential"

ENV_ACTIVATED = {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true",
                 LIVE_CONFIG_ENABLED_ENV: "true"}

# A valid, checksum-correct synthetic NPI. Generated for tests; it belongs to
# nobody and appears in no organiser document.
SYNTHETIC_NPI = "1234567893"

REPO_CONFIG = load_config()


# ------------------------------------------------------------- the fake wire


class _Wire:
    """Stands in for urlopen at the HTTP boundary. Records what was sent."""

    def __init__(self, *, value=SYNTHETIC_NPI, usage=None, status=200,
                 include_cost=True):
        self.value = value
        self.usage = usage
        self.status = status
        self.include_cost = include_cost
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None):
        body = json.loads(request.data.decode())
        self.requests.append({
            "url": request.full_url,
            "model": body.get("model"),
            "has_image": any(
                part.get("type") == "image_url"
                for part in body["messages"][0]["content"]),
            "allow_fallbacks": (body.get("provider") or {}).get("allow_fallbacks"),
            "authorization_present": bool(
                request.headers.get("Authorization")
                or request.headers.get("authorization")),
        })
        usage = self.usage if self.usage is not None else {
            "prompt_tokens": 412, "completion_tokens": 9}
        if self.include_cost:
            usage = {**usage, "cost": 0.0000041}
        envelope = {
            "model": "google/gemini-3.5-flash-lite",
            "choices": [{"message": {"content": json.dumps({
                "value": self.value,
                "visible": self.value is not None,
                "confidence": 0.96,
            })}, "finish_reason": "stop"}],
            "usage": usage,
        }
        return _Response(envelope, self.status)

    @property
    def call_count(self) -> int:
        return len(self.requests)


class _Response:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def refuse_network(monkeypatch):
    """Any un-faked socket is an immediate, loud failure."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test attempted a real network call")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    return refuse


# ------------------------------------------------------------ the document


def _synthetic_png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(stream, format="PNG")
    return stream.getvalue()


def _synthetic_session():
    """One generated document with one unresolved critical field and a bbox."""
    item = inspect_content("synthetic.png", _synthetic_png())
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
    return item, state, batch["documents"][0]


def _request():
    page = Image.new("RGB", (1200, 1600), "white")
    return request_from_page(page, (100, 200, 340, 244), "billing_provider_npi",
                             doc_id="synthetic-doc", page_id="p1", synthetic=True)


def _run_through_real_stack(wire, monkeypatch, *, value=SYNTHETIC_NPI):
    """run_one_candidate with NOTHING stubbed except the socket."""
    monkeypatch.setattr(urllib.request, "urlopen", wire)
    governor = LiveCallGovernor(REPO_CONFIG, env=dict(ENV_ACTIVATED),
                                mode="balanced")
    monkeypatch.setenv(KEY, FAKE_KEY)
    receipt, accepted = multimodal_permission.run_one_candidate(
        _request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0)
    return governor, receipt, accepted


# ------------------------------------------- the real adapter, end to end


def test_the_real_adapter_builds_a_crop_only_openrouter_request(monkeypatch):
    """What actually goes on the wire, asserted on the wire."""
    wire = _Wire()
    _, receipt, accepted = _run_through_real_stack(wire, monkeypatch)

    assert wire.call_count == 1
    sent = wire.requests[0]
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["model"] == "google/gemini-3.5-flash-lite"
    assert sent["has_image"] is True
    # Locked off, never configurable: a silent substitution to a pricier model
    # is an unbounded spend.
    assert sent["allow_fallbacks"] is False
    assert sent["authorization_present"] is True


def test_a_valid_answer_is_parsed_grounded_validated_and_accepted(monkeypatch):
    wire = _Wire()
    governor, receipt, accepted = _run_through_real_stack(wire, monkeypatch)

    assert receipt["called_provider"] is True
    assert receipt["external_calls_made"] == 1
    assert receipt["policy_decision"] == "ALLOW"
    assert receipt["grounding_passed"] is True
    assert receipt["healthcare_validators_passed"] is True
    assert receipt["final_field_outcome"] == "ACCEPTED"
    assert receipt["error_category"] == ""
    assert accepted == SYNTHETIC_NPI
    assert governor.calls_made == 1


def test_reported_usage_and_cost_are_captured_from_the_envelope(monkeypatch):
    wire = _Wire()
    _, receipt, _ = _run_through_real_stack(wire, monkeypatch)

    assert receipt["usage"]["input_tokens"] == 412
    assert receipt["usage"]["output_tokens"] == 9
    # OpenRouter does not break these out; they must stay unknown, not become 0.
    assert receipt["usage"]["image_tokens"] is None
    assert receipt["cost_basis"] == "provider_reported"
    assert receipt["measured_cost_usd"] == pytest.approx(0.0000041)


def test_absent_usage_stays_none_and_still_produces_a_receipt(monkeypatch):
    """The exact shape that crashed the Cost tab, now through the real adapter."""
    wire = _Wire(usage={}, include_cost=False)
    _, receipt, _ = _run_through_real_stack(wire, monkeypatch)

    assert receipt["called_provider"] is True
    assert receipt["usage"]["input_tokens"] is None
    assert receipt["usage"]["output_tokens"] is None
    assert json.dumps(receipt)          # serialises for export and audit


def test_an_invalid_value_is_rejected_and_the_field_stays_unresolved(monkeypatch):
    """A call that succeeded technically and produced a wrong answer. The money
    was still spent, and reporting the field as resolved would make the spend
    look like accuracy."""
    wire = _Wire(value="0000000000")           # fails the NPI checksum
    _, receipt, accepted = _run_through_real_stack(wire, monkeypatch)

    assert wire.call_count == 1
    assert receipt["called_provider"] is True
    assert receipt["external_calls_made"] == 1
    assert receipt["healthcare_validators_passed"] is False
    assert receipt["final_field_outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert receipt["error_category"] == multimodal_permission.VALIDATION_REJECTED
    assert receipt["required_action"]
    assert accepted is None


@pytest.mark.parametrize("status,expected", [
    (401, "AUTHENTICATION_ERROR"),
    (402, "INSUFFICIENT_CREDIT"),
    (404, "MODEL_NOT_AVAILABLE"),
    (429, "RATE_LIMIT"),
    (500, "PROVIDER_5XX"),
])
def test_each_provider_status_reaches_the_receipt_as_its_own_category(
        monkeypatch, status, expected):
    """Step 9, proven through the real adapter rather than asserted in the UI."""
    import urllib.error

    def failing(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, status, "err", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", failing)
    monkeypatch.setenv(KEY, FAKE_KEY)
    governor = LiveCallGovernor(REPO_CONFIG, env=dict(ENV_ACTIVATED),
                                mode="balanced")
    receipt, accepted = multimodal_permission.run_one_candidate(
        _request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0)

    assert receipt["error_category"] == expected
    assert receipt["error_summary"] and receipt["required_action"]
    assert receipt["final_field_outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert accepted is None


def test_a_repeated_request_makes_no_second_http_call(monkeypatch):
    """A Streamlit rerun re-executes the script with no user action at all."""
    wire = _Wire()
    monkeypatch.setattr(urllib.request, "urlopen", wire)
    monkeypatch.setenv(KEY, FAKE_KEY)
    governor = LiveCallGovernor(REPO_CONFIG, env=dict(ENV_ACTIVATED),
                                mode="balanced")
    request = _request()
    run = dict(enabled=True, confirmed=True, synthetic_attested=True,
               governor=governor, config=REPO_CONFIG)

    first, value = multimodal_permission.run_one_candidate(
        request, calls_used=0, **run)
    second, repeated = multimodal_permission.run_one_candidate(
        request, calls_used=1, **run)

    assert wire.call_count == 1
    assert first["external_calls_made"] == 1
    assert second["external_calls_made"] == 0
    assert repeated is None
    assert governor.calls_made == 1


def test_the_crop_never_appears_in_the_receipt(monkeypatch):
    wire = _Wire()
    _, receipt, _ = _run_through_real_stack(wire, monkeypatch)

    rendered = json.dumps(receipt)
    assert FAKE_KEY not in rendered
    assert "base64" not in rendered.lower()
    assert receipt["raw_response_persisted"] is False
    assert receipt["crop_contents_persisted"] is False
    # The accepted value is returned in memory for the field, never written to
    # the audit receipt.
    assert SYNTHETIC_NPI not in rendered


# ------------------------------------- document, counters and exports


def test_an_accepted_answer_updates_the_document_counters_and_exports(monkeypatch):
    wire = _Wire()
    monkeypatch.setattr(urllib.request, "urlopen", wire)
    monkeypatch.setenv(KEY, FAKE_KEY)
    _, state, document = _synthetic_session()
    before_unresolved = len(workspace.build_review_queue(document))
    governor = LiveCallGovernor(REPO_CONFIG, env=dict(ENV_ACTIVATED),
                                mode="balanced")

    receipt, accepted = multimodal_permission.run_one_candidate(
        _request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0)
    updated = workspace.apply_multimodal_candidate(
        document, page=1, field_name="billing_provider_npi",
        value=accepted, receipt=receipt)

    assert len(workspace.build_review_queue(updated)) == before_unresolved - 1
    assert SYNTHETIC_NPI in workspace.export_document_csv(updated)
    assert SYNTHETIC_NPI in workspace.export_document_json(updated)
    escalation = next(row for row in updated["provider_escalations"]
                      if row["field_name"] == "billing_provider_npi")
    assert escalation["external_call_count"] == 1
    assert escalation["final_workflow_state"] == "MULTIMODAL_ATTEMPTED"


def test_a_rejected_answer_leaves_the_field_for_a_human(monkeypatch):
    wire = _Wire(value="0000000000")
    monkeypatch.setattr(urllib.request, "urlopen", wire)
    monkeypatch.setenv(KEY, FAKE_KEY)
    _, state, document = _synthetic_session()
    before_unresolved = len(workspace.build_review_queue(document))
    governor = LiveCallGovernor(REPO_CONFIG, env=dict(ENV_ACTIVATED),
                                mode="balanced")

    receipt, accepted = multimodal_permission.run_one_candidate(
        _request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0)
    updated = workspace.apply_multimodal_candidate(
        document, page=1, field_name="billing_provider_npi",
        value=accepted, receipt=receipt)

    # The call happened and is counted. The field is not resolved.
    assert len(workspace.build_review_queue(updated)) == before_unresolved
    escalation = next(row for row in updated["provider_escalations"]
                      if row["field_name"] == "billing_provider_npi")
    assert escalation["external_call_count"] == 1
    assert escalation["final_workflow_state"] == "MULTIMODAL_FAILED"


# --------------------------------------------------- rendered, after a call


def test_every_tab_renders_after_a_completed_call(monkeypatch, refuse_network):
    """Including Cost, and including the receipt's failure category. Rendering
    must never open a socket, which `refuse_network` enforces."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    for tab in streamlit_app.WORKSPACE_TABS:
        _, state, _ = _synthetic_session()
        state["multimodal"]["receipts"]["fp"] = {
            "called_provider": True, "external_calls_made": 1,
            "measured_cost_usd": 0.0000041, "latency_ms": 640.0,
            "final_field_outcome": "HUMAN_REVIEW_REQUIRED",
            "usage": {"input_tokens": 412, "output_tokens": 9,
                      "image_tokens": None, "cached_tokens": None,
                      "reasoning_tokens": None},
            **multimodal_permission._failure_fields(
                multimodal_permission.VALIDATION_REJECTED),
        }
        app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
        app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
        app.session_state["cr_workspace_tabs"] = tab
        app.run(timeout=60)

        assert not app.exception, (
            f"{tab} raised {[str(e.value) for e in app.exception]}")


def test_the_named_failure_category_is_rendered_not_a_generic_message(monkeypatch,
                                                                     refuse_network):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    _, state, _ = _synthetic_session()
    state["multimodal"]["receipts"]["fp"] = {
        "called_provider": True, "external_calls_made": 1,
        "measured_cost_usd": 0.0, "latency_ms": 12.0,
        "final_field_outcome": "HUMAN_REVIEW_REQUIRED",
        "usage": {"input_tokens": None, "output_tokens": None},
        **multimodal_permission._failure_fields("INSUFFICIENT_CREDIT",
                                                "provider returned HTTP 402"),
    }
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.session_state["cr_workspace_tabs"] = "Results"
    app.run(timeout=60)

    assert not app.exception
    shown = " ".join([row.value for row in app.error]
                     + [row.value for row in app.warning])
    assert "INSUFFICIENT_CREDIT" in shown
    assert "Add credit" in shown
    # Local work stays usable after a provider failure.
    assert "remain" in shown
