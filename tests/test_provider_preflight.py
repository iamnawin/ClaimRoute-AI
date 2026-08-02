"""Answer the answerable questions before spending, and name the one that fails.

A paid call that fails teaches you almost nothing: the money is gone and the
message is whatever the provider chose to return. Worse, five unrelated
conditions used to arrive on screen as the same sentence. A revoked key, an
empty balance, a model id that does not exist, a rate limit and an answer that
failed healthcare validation need five different people to do five different
things, and "multimodal failed" sends every one of them to guess.

Three things are proven here:

- 402, 404 and 400 have their own categories. They used to fall through to
  UNKNOWN_PROVIDER_ERROR, which put "add credit", "fix the model id" and "fix
  the request we built" behind one word.
- The credential can be checked WITHOUT sending a crop and WITHOUT being
  billed, so a 401 is never discovered by paying for an image request.
- Nothing in any report, receipt, or error path contains the key.

No test here opens a socket. Every HTTP interaction is a local double.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest
from PIL import Image

from app import multimodal_permission, preflight
from engine.escalation.client import load_config, request_from_page
from engine.escalation.errors import (RETRYABLE, ErrorCategory, MultimodalError,
                                      category_for_status, explain)
from engine.escalation.live_policy import (LIVE_CONFIG_ENABLED_ENV,
                                           LiveCallGovernor)

KEY = "OPENROUTER_API_KEY"
ENABLE = "CLAIMROUTE_MULTIMODAL_ENABLED"
LIVE_TEST = "CLAIMROUTE_LIVE_PROVIDER_TEST"

# Never a realistic key shape. A fixture that looks like a credential invites
# someone to paste a real one in beside it.
FAKE_KEY = "test-key-not-a-credential"

ENV_ACTIVATED = {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true",
                 LIVE_CONFIG_ENABLED_ENV: "true"}

REPO_CONFIG = load_config()


def _crop_request(*, synthetic=True):
    page = Image.new("RGB", (1200, 1600), "white")
    return request_from_page(page, (100, 200, 340, 244), "billing_provider_npi",
                             doc_id="synthetic-doc", page_id="p1",
                             synthetic=synthetic)


def _governor(env=None, mode="balanced"):
    return LiveCallGovernor(REPO_CONFIG, env=dict(env or ENV_ACTIVATED), mode=mode)


# ------------------------------------------------------- status categories


@pytest.mark.parametrize("status,expected", [
    (400, ErrorCategory.INVALID_REQUEST),
    (401, ErrorCategory.AUTHENTICATION_ERROR),
    (402, ErrorCategory.INSUFFICIENT_CREDIT),
    (403, ErrorCategory.AUTHENTICATION_ERROR),
    (404, ErrorCategory.MODEL_NOT_AVAILABLE),
    (408, ErrorCategory.TIMEOUT),
    (429, ErrorCategory.RATE_LIMIT),
    (500, ErrorCategory.PROVIDER_5XX),
    (503, ErrorCategory.PROVIDER_5XX),
])
def test_each_status_gets_its_own_category(status, expected):
    assert category_for_status(status) is expected


def test_no_two_actionable_statuses_share_a_category():
    """The regression itself. 401, 402 and 404 mean rotate a key, add credit,
    and fix a model id. Collapsing them sends someone to do the wrong one."""
    distinct = {category_for_status(code) for code in (401, 402, 404, 429, 500)}

    assert len(distinct) == 5


@pytest.mark.parametrize("category", list(ErrorCategory))
def test_every_category_explains_itself_and_names_an_action(category):
    summary, action = explain(category)

    assert summary and action
    assert "multimodal failed" not in summary.lower()


def test_funding_and_credential_failures_do_not_share_an_explanation():
    assert explain(ErrorCategory.INSUFFICIENT_CREDIT) != \
        explain(ErrorCategory.AUTHENTICATION_ERROR)


def test_unfundable_and_malformed_conditions_are_never_retried():
    """Retrying a 402 or a 400 bills again for an identical outcome."""
    assert ErrorCategory.INSUFFICIENT_CREDIT not in RETRYABLE
    assert ErrorCategory.INVALID_REQUEST not in RETRYABLE
    assert ErrorCategory.MODEL_NOT_AVAILABLE not in RETRYABLE
    assert ErrorCategory.RATE_LIMIT in RETRYABLE


def test_an_unrecognised_category_still_explains_itself():
    assert explain("SOMETHING_NEW") == explain(ErrorCategory.UNKNOWN_PROVIDER_ERROR)


# ------------------------------------------------------ environment report


def test_environment_report_states_presence_and_never_the_key():
    report = preflight.environment_report(ENV_ACTIVATED)

    assert report[f"{KEY}_PRESENT"] is True
    assert report[f"{KEY}_IS_PLACEHOLDER"] is False
    assert FAKE_KEY not in json.dumps(report)
    assert FAKE_KEY[:6] not in json.dumps(report)


@pytest.mark.parametrize("placeholder", [
    "YOUR_CORRECT_KEY", "your_api_key", "changeme", "sk-xxx", "  TODO  "])
def test_a_placeholder_is_reported_rather_than_sent(placeholder):
    """Pasting the instructions instead of the key produces a 401 that is
    indistinguishable from a revoked key unless it is caught here."""
    report = preflight.environment_report({**ENV_ACTIVATED, KEY: placeholder})

    assert report[f"{KEY}_IS_PLACEHOLDER"] is True


def test_surrounding_whitespace_is_stripped_and_reported():
    """A key pasted with a trailing newline is present, is not blank, and still
    fails at the provider with a 401 that says nothing about whitespace."""
    report = preflight.environment_report({**ENV_ACTIVATED, KEY: "  real-key\n"})

    assert report[f"{KEY}_PRESENT"] is True
    assert report[f"{KEY}_HAD_SURROUNDING_WHITESPACE"] is True


def test_a_key_of_only_whitespace_is_not_present():
    report = preflight.environment_report({**ENV_ACTIVATED, KEY: "   "})

    assert report[f"{KEY}_PRESENT"] is False


def test_a_malformed_flag_is_reported_as_malformed_not_as_false():
    report = preflight.environment_report({**ENV_ACTIVATED, ENABLE: "yeah-sure"})

    assert report[ENABLE] == "MALFORMED"


# -------------------------------------------------------- provider report


def test_provider_report_names_the_real_endpoint_and_budgets():
    report = preflight.provider_report(REPO_CONFIG, mode="balanced",
                                       env=ENV_ACTIVATED)

    assert report["provider_name"] == "openrouter"
    assert report["endpoint"] == "https://openrouter.ai/api/v1/chat/completions"
    assert report["model_allowlisted"] is True
    assert report["model_image_capable"] is True
    assert report["fallback_models_allowed"] is False
    assert report["automatic_reruns_allowed"] is False
    assert report["session_budget_usd"] > 0
    assert report["document_budget_usd"] > 0


def test_the_shipped_endpoint_raises_no_warnings():
    report = preflight.provider_report(REPO_CONFIG, env=ENV_ACTIVATED)

    assert preflight.endpoint_warnings(report) == []


@pytest.mark.parametrize("endpoint,fragment", [
    ("http://openrouter.ai/api/v1/chat/completions", "not HTTPS"),
    ("https://api.openai.com/v1/chat/completions", "another host"),
    ("https://localhost:8080/v1/chat/completions", "test target"),
    ("", "no endpoint"),
])
def test_a_misrouted_endpoint_is_named_rather_than_silently_used(endpoint, fragment):
    """A call that goes somewhere unintended is worse than one that fails: it
    can succeed, bill a different account, and look exactly like success."""
    warnings = preflight.endpoint_warnings(
        {"provider_name": "openrouter", "endpoint": endpoint})

    assert any(fragment in warning for warning in warnings), warnings


# --------------------------------------------------------------- dry run


def test_dry_run_reports_safe_metadata_and_no_payload():
    request = _crop_request()
    receipt = preflight.dry_run_receipt(
        request, governor=_governor(), config=REPO_CONFIG)

    assert receipt["provider"] == "openrouter"
    assert receipt["model"] == "google/gemini-3.5-flash-lite"
    assert receipt["crop_width_px"] > 0 and receipt["crop_height_px"] > 0
    assert receipt["crop_bytes"] > 0
    assert receipt["crop_mime_type"] == "image/png"
    assert receipt["synthetic"] is True
    assert receipt["full_page"] is False
    assert receipt["organiser_data"] is False
    assert receipt["max_calls"] == 1
    assert len(receipt["request_fingerprint"]) == 32
    assert receipt["authorized"] is True


def test_dry_run_never_contains_the_image_or_the_key():
    request = _crop_request()
    rendered = json.dumps(preflight.dry_run_receipt(
        request, governor=_governor(), config=REPO_CONFIG))

    assert request.crop.b64[:32] not in rendered
    assert FAKE_KEY not in rendered
    assert preflight.render_dry_run(json.loads(rendered))


def test_dry_run_does_not_reserve_a_call_or_move_a_counter():
    """Looking at an approval receipt must not consume the thing it describes.
    Rendering happens on every Streamlit rerun."""
    governor = _governor()
    request = _crop_request()

    for _ in range(5):
        receipt = preflight.dry_run_receipt(
            request, governor=governor, config=REPO_CONFIG)
        assert receipt["authorized"] is True

    assert governor.calls_made == 0
    assert governor.session_spend_usd == 0.0


def test_dry_run_reports_the_blocking_gate_when_one_is_shut():
    receipt = preflight.dry_run_receipt(
        _crop_request(), governor=_governor({ENABLE: "true", LIVE_TEST: "true",
                                             LIVE_CONFIG_ENABLED_ENV: "true"}),
        config=REPO_CONFIG)

    assert receipt["authorized"] is False
    assert receipt["authorization"] == "BLOCKED_NO_API_KEY"
    assert "BLOCKED_NO_API_KEY" in preflight.render_dry_run(receipt)


# ---------------------------------------------------- credential preflight


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self._body = json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://openrouter.ai/api/v1/key", code, "err", {}, None)
    return opener


def test_a_valid_credential_is_confirmed_without_sending_a_crop():
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["has_body"] = request.data is not None
        return _Response({"data": {"label": "test", "usage": 0, "limit": None}})

    check = preflight.check_credentials(key=FAKE_KEY, opener=opener)

    assert check.ok is True
    assert seen["method"] == "GET"
    assert seen["has_body"] is False       # no crop, nothing billable
    assert "openrouter.ai" in seen["url"]


@pytest.mark.parametrize("status,expected", [
    (401, ErrorCategory.AUTHENTICATION_ERROR),
    (402, ErrorCategory.INSUFFICIENT_CREDIT),
    (403, ErrorCategory.AUTHENTICATION_ERROR),
    (404, ErrorCategory.MODEL_NOT_AVAILABLE),
    (429, ErrorCategory.RATE_LIMIT),
    (500, ErrorCategory.PROVIDER_5XX),
])
def test_each_provider_status_maps_to_its_own_category(status, expected):
    check = preflight.check_credentials(key=FAKE_KEY, opener=_http_error(status))

    assert check.ok is False
    assert check.category is expected
    assert check.status_code == status
    summary, action = check.guidance
    assert summary and action


def test_a_network_failure_is_not_an_authentication_failure():
    def opener(request, timeout=None):
        raise urllib.error.URLError(OSError("connection refused"))

    check = preflight.check_credentials(key=FAKE_KEY, opener=opener)

    assert check.category is ErrorCategory.NETWORK_ERROR


def test_a_timeout_is_reported_as_a_timeout():
    def opener(request, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    check = preflight.check_credentials(key=FAKE_KEY, opener=opener)

    assert check.category is ErrorCategory.TIMEOUT


def test_an_exhausted_key_is_caught_before_the_image_request():
    """A key at its usage limit will 402 on the real call. Saying so here is the
    difference between one wasted request and none."""
    def opener(request, timeout=None):
        return _Response({"data": {"usage": 5.0, "limit": 5.0}})

    check = preflight.check_credentials(key=FAKE_KEY, opener=opener)

    assert check.ok is False
    assert check.category is ErrorCategory.INSUFFICIENT_CREDIT


def test_a_missing_key_is_a_configuration_error_and_opens_no_socket():
    def opener(request, timeout=None):
        raise AssertionError("no request may be made without a credential")

    check = preflight.check_credentials(key="", opener=opener)

    assert check.category is ErrorCategory.CONFIGURATION_ERROR


def test_a_placeholder_key_is_refused_before_the_network():
    def opener(request, timeout=None):
        raise AssertionError("a placeholder must never be sent")

    check = preflight.check_credentials(key="YOUR_CORRECT_KEY", opener=opener)

    assert check.category is ErrorCategory.CONFIGURATION_ERROR


def test_the_credential_never_appears_in_any_check_result():
    """Error strings are the most likely thing to be pasted somewhere public."""
    for opener in (_http_error(401), _http_error(500)):
        check = preflight.check_credentials(key=FAKE_KEY, opener=opener)
        rendered = json.dumps(check.to_dict()) + repr(check.__dict__)

        assert FAKE_KEY not in rendered
        assert FAKE_KEY[:8] not in rendered


def test_a_non_json_credential_response_is_an_invalid_response():
    class Garbage:
        status = 200

        def read(self):
            return b"<html>proxy</html>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    check = preflight.check_credentials(key=FAKE_KEY,
                                        opener=lambda r, timeout=None: Garbage())

    assert check.category is ErrorCategory.INVALID_RESPONSE


# --------------------------------------------------- receipts name the cause


def test_a_provider_failure_receipt_carries_the_category_not_a_generic_string():
    """The step-9 defect: the client already categorised every failure and the
    receipt dropped it, leaving the UI with nothing but "multimodal failed"."""
    fields = multimodal_permission._failure_fields(
        ErrorCategory.INSUFFICIENT_CREDIT.value, "provider returned HTTP 402")

    assert fields["error_category"] == "INSUFFICIENT_CREDIT"
    assert fields["error_summary"]
    assert fields["required_action"]
    assert fields["error_retryable"] is False


def test_a_validation_rejection_is_not_reported_as_a_provider_failure():
    """The provider worked. The answer was wrong. Reporting the safety net as a
    fault is how a working guardrail gets switched off."""
    fields = multimodal_permission._failure_fields(
        multimodal_permission.VALIDATION_REJECTED)

    assert fields["error_category"] == "VALIDATION_REJECTED"
    assert "validation" in fields["error_summary"].lower()
    assert fields["error_retryable"] is False


@pytest.mark.parametrize("decision,expected", [
    ("BLOCKED_SESSION_BUDGET", multimodal_permission.BUDGET_BLOCKED),
    ("BLOCKED_DOCUMENT_BUDGET", multimodal_permission.BUDGET_BLOCKED),
    ("BLOCKED_FIELD_PAID_ATTEMPTS", multimodal_permission.BUDGET_BLOCKED),
    ("BLOCKED_DUPLICATE_REQUEST", multimodal_permission.DUPLICATE_REQUEST_BLOCKED),
    ("REUSED_CACHED_RESULT", multimodal_permission.DUPLICATE_REQUEST_BLOCKED),
])
def test_budget_and_duplicate_refusals_are_named_not_called_failures(
        decision, expected):
    """Nothing was billed and nothing is wrong. Both are routinely mistaken for
    provider failures."""
    assert multimodal_permission.failure_for_decision(
        decision)["error_category"] == expected


def test_a_successful_call_carries_no_failure_category():
    assert multimodal_permission._failure_fields(None)["error_category"] == ""


def test_a_construction_failure_keeps_its_category():
    """A missing key, an unconfigured provider entry and a refused model id all
    used to arrive as "Provider construction failed safely"."""
    config = {**REPO_CONFIG, "providers": {}}
    governor = _governor()
    receipt, value = multimodal_permission.run_one_candidate(
        _crop_request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=config, calls_used=0,
        client_factory=lambda **kw: None)

    assert value is None
    assert receipt["external_calls_made"] == 0
    assert receipt["error_category"] == ErrorCategory.CONFIGURATION_ERROR.value
    assert receipt["required_action"]
