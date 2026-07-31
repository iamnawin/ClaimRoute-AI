"""Client behaviour: disabled by default, policy gates, bounded retries, audit safety.

Every provider here is a deterministic in-process fake. No test opens a socket,
and no test reads organiser, development, or holdout data.
"""
import json

import pytest
from PIL import Image

from engine.escalation.client import (ENABLE_ENV, MultimodalClient, build_request,
                                      load_config, request_from_page)
from engine.escalation.contract import UsageMetadata
from engine.escalation.errors import ErrorCategory, MultimodalError
from engine.escalation.providers.base import ProviderCall
from engine.escalation.providers.fake import DeterministicFakeProvider, ScriptedProvider
from engine.ledger import CostLedger

SYNTHETIC_NPI = "1393521955"

CONFIG = {
    "enabled": False,
    "active_provider": "openai",
    "request_policy": {"crop_only": True, "max_page_fraction": 0.25,
                       "require_page_provenance": True, "max_crop_bytes": 2_000_000,
                       "synthetic_data_only": True},
    "transport": {"timeout_seconds": 7, "max_attempts": 3,
                  "backoff_initial_seconds": 0.5, "backoff_multiplier": 2.0,
                  "backoff_max_seconds": 8.0, "retry_on_invalid_response": False},
    "response_policy": {"max_value_chars": 120},
    "providers": {"openai": {"kind": "openai_chat_completions", "model": "gpt-5-nano",
                             "api_key_env": "OPENAI_API_KEY",
                             "price_row": "gpt-5-nano"}},
}


class _Sleeps:
    """Captures backoff waits so retry tests never actually sleep."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


def _page(w=1700, h=2200):
    return Image.new("RGB", (w, h), "white")


def _request(field_name="billing_provider_npi", **kw):
    return request_from_page(_page(), [200, 300, 420, 340], field_name,
                             doc_id="synthetic-doc", page_id="p1", **kw)


def _ok_body(value=SYNTHETIC_NPI, **kw):
    payload = {"value": value, "visible": True, "confidence": 0.96}
    payload.update(kw)
    return json.dumps(payload)


def _client(provider, *, enabled=True, config=None, sleep=None, ledger=None):
    return MultimodalClient(config=config or CONFIG, provider=provider,
                            enabled=enabled, sleep=sleep or _Sleeps(),
                            ledger=ledger, env={})


# ------------------------------------------------------- disabled by default

def test_shipped_config_is_disabled_and_holds_no_api_key():
    config = load_config()
    assert config["enabled"] is False
    text = json.dumps(config)
    assert "sk-" not in text
    # Keys are named, never valued.
    assert config["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert "api_key" not in config["providers"]["openai"]


def test_client_is_disabled_when_nothing_enables_it():
    provider = ScriptedProvider([_ok_body()])
    client = MultimodalClient(config=CONFIG, provider=provider, env={})
    result = client.read_field(_request())

    assert client.enabled is False
    assert result.error == ErrorCategory.CONFIGURATION_ERROR.value
    # The decisive assertion: disabled means no call was attempted at all.
    assert provider.call_count == 0
    assert result.called_provider is False
    assert result.ok is False


def test_environment_flag_can_enable_for_one_process():
    provider = ScriptedProvider([_ok_body()])
    client = MultimodalClient(config=CONFIG, provider=provider,
                              env={ENABLE_ENV: "1"}, sleep=_Sleeps())
    assert client.enabled is True
    assert client.read_field(_request()).ok is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
def test_non_affirmative_environment_values_leave_it_disabled(value):
    client = MultimodalClient(config=CONFIG, provider=ScriptedProvider([]),
                              env={ENABLE_ENV: value})
    assert client.enabled is False


# ------------------------------------------------------------- policy gates

def test_full_page_request_is_refused_before_any_call():
    page = _page(400, 400)
    request = build_request(page, "patient_name", source_page_px=(400, 400),
                            region_px=(400, 400))
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider).read_field(request)

    assert result.error == ErrorCategory.UNSUPPORTED_IMAGE.value
    assert "full pages are never sent" in result.error_detail
    assert provider.call_count == 0


def test_image_without_page_provenance_is_refused():
    request = build_request(Image.new("RGB", (80, 30), "white"), "patient_name")
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider).read_field(request)

    assert result.error == ErrorCategory.UNSUPPORTED_IMAGE.value
    assert "cannot prove the image is a field crop" in result.error_detail
    assert provider.call_count == 0


def test_non_synthetic_request_is_refused_while_synthetic_only_is_set():
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider).read_field(_request(synthetic=False))

    assert result.error == ErrorCategory.CONFIGURATION_ERROR.value
    assert provider.call_count == 0


def test_oversized_crop_is_refused():
    config = {**CONFIG, "request_policy": {**CONFIG["request_policy"],
                                           "max_crop_bytes": 10}}
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider, config=config).read_field(_request())

    assert result.error == ErrorCategory.UNSUPPORTED_IMAGE.value
    assert provider.call_count == 0


def test_legitimate_field_crop_passes_the_gate():
    provider = DeterministicFakeProvider({"billing_provider_npi": SYNTHETIC_NPI})
    result = _client(provider).read_field(_request())
    assert result.ok is True and result.answer.value == SYNTHETIC_NPI


# ---------------------------------------------------------------- retries

def test_transient_failures_are_retried_then_succeed():
    sleeps = _Sleeps()
    provider = ScriptedProvider([
        MultimodalError(ErrorCategory.RATE_LIMIT, "HTTP 429", status_code=429),
        MultimodalError(ErrorCategory.PROVIDER_5XX, "HTTP 503", status_code=503),
        _ok_body(),
    ])
    result = _client(provider, sleep=sleeps).read_field(_request())

    assert result.ok is True
    assert provider.call_count == 3 and result.attempts == 3
    assert sleeps.waits == [0.5, 1.0]          # bounded exponential backoff


def test_retries_are_bounded_by_max_attempts():
    provider = ScriptedProvider([
        MultimodalError(ErrorCategory.TIMEOUT, "slow") for _ in range(10)])
    result = _client(provider).read_field(_request())

    assert result.error == ErrorCategory.TIMEOUT.value
    # Exactly max_attempts calls: a retry loop must not be able to spend forever.
    assert provider.call_count == 3 and result.attempts == 3


def test_authentication_failure_is_not_retried():
    provider = ScriptedProvider([
        MultimodalError(ErrorCategory.AUTHENTICATION_ERROR, "HTTP 401",
                        status_code=401)])
    result = _client(provider).read_field(_request())

    assert result.error == ErrorCategory.AUTHENTICATION_ERROR.value
    assert provider.call_count == 1


@pytest.mark.parametrize("category", [ErrorCategory.CONTENT_BLOCKED,
                                      ErrorCategory.UNSUPPORTED_IMAGE,
                                      ErrorCategory.CONFIGURATION_ERROR])
def test_permanent_categories_are_not_retried(category):
    provider = ScriptedProvider([MultimodalError(category, "permanent")])
    result = _client(provider).read_field(_request())
    assert result.error == category.value and provider.call_count == 1


def test_provider_retry_after_overrides_the_backoff_curve():
    sleeps = _Sleeps()
    provider = ScriptedProvider([
        MultimodalError(ErrorCategory.RATE_LIMIT, "HTTP 429", status_code=429,
                        retry_after_s=2.5),
        _ok_body(),
    ])
    _client(provider, sleep=sleeps).read_field(_request())
    assert sleeps.waits == [2.5]


def test_backoff_is_capped():
    sleeps = _Sleeps()
    config = {**CONFIG, "transport": {**CONFIG["transport"], "max_attempts": 5,
                                      "backoff_initial_seconds": 4.0,
                                      "backoff_max_seconds": 6.0}}
    provider = ScriptedProvider([
        MultimodalError(ErrorCategory.NETWORK_ERROR, "down") for _ in range(5)])
    _client(provider, config=config, sleep=sleeps).read_field(_request())
    assert sleeps.waits == [4.0, 6.0, 6.0, 6.0]


def test_malformed_answer_is_not_retried_by_default():
    provider = ScriptedProvider(["I think this box says something."])
    result = _client(provider).read_field(_request())

    # A schema breach is not transient; paying twice for it would learn nothing.
    assert provider.call_count == 1
    assert result.error is None            # transport succeeded
    assert result.rejects and result.ok is False


def test_timeout_value_from_config_reaches_the_provider():
    provider = ScriptedProvider([_ok_body()])
    _client(provider).read_field(_request())
    assert provider.timeouts == [7]


def test_unexpected_provider_exception_is_categorised_not_raised():
    class Broken(ScriptedProvider):
        def invoke(self, request, *, timeout_s):
            raise ValueError("provider bug")

    result = _client(Broken([])).read_field(_request())
    assert result.error == ErrorCategory.UNKNOWN_PROVIDER_ERROR.value


# ------------------------------------------------------------ audit safety

def test_raw_response_is_hashed_and_never_retained():
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider).read_field(_request())

    assert len(result.raw_sha256) == 64
    serialised = json.dumps(result.audit)
    assert result.raw_sha256 in serialised
    # The body itself is gone: no raw text on the result and none in the audit.
    assert not hasattr(result, "raw")
    assert SYNTHETIC_NPI not in serialised


def test_audit_record_carries_no_values_and_no_pixels():
    provider = DeterministicFakeProvider({"patient_name": "SMITH, JOHN"})
    result = _client(provider).read_field(_request("patient_name"))

    serialised = json.dumps(result.audit)
    assert result.ok is True
    assert "SMITH" not in serialised and "JOHN" not in serialised
    # Shape is reported instead of content.
    assert result.audit["answer"] == {"has_value": True, "value_chars": 11,
                                      "visible": True,
                                      "confidence": result.answer.confidence}
    assert result.audit["crop_sha256"] and "png_bytes" not in serialised


def test_audit_record_reports_latency_attempts_and_provider_identity():
    provider = ScriptedProvider([_ok_body()])
    result = _client(provider).read_field(_request())
    audit = result.audit

    assert audit["attempts"] == 1 and audit["called_provider"] is True
    assert audit["enabled"] is True and audit["ok"] is True
    assert audit["latency_ms"] >= 0 and len(audit["provider_latency_ms"]) == 1
    assert audit["model"] == "fake-model"
    assert audit["synthetic_data"] is True


def test_ledger_row_is_written_without_values(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.jsonl")
    provider = DeterministicFakeProvider({"patient_name": "SMITH, JOHN"})
    _client(provider, ledger=ledger).read_field(_request("patient_name"))

    entries = ledger.entries()
    assert len(entries) == 1
    assert entries[0]["operation"] == "multimodal_fake-deterministic"
    assert "SMITH" not in json.dumps(entries[0])


def test_blocked_request_is_ledgered_as_blocked_with_zero_cost(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.jsonl")
    provider = ScriptedProvider([_ok_body()])
    MultimodalClient(config=CONFIG, provider=provider, env={},
                     ledger=ledger).read_field(_request())

    entry = ledger.entries()[0]
    assert entry["operation"] == "multimodal_blocked"
    assert entry["cost_usd"] == 0.0
    assert provider.call_count == 0


# ------------------------------------------------------------------- cost

def test_reported_usage_produces_measured_cost():
    provider = ScriptedProvider(
        [_ok_body()], usage=UsageMetadata(input_tokens=1000, output_tokens=100))
    result = _client(provider).read_field(_request())

    assert result.cost.basis == "measured_usage"
    # gpt-5-nano: $0.05/1M in, $0.40/1M out.
    assert result.cost.measured_usd == pytest.approx(1000 / 1e6 * 0.05
                                                     + 100 / 1e6 * 0.40)
    assert result.cost.estimated_usd is None


def test_absent_usage_falls_back_to_a_flagged_lower_bound_estimate():
    provider = ScriptedProvider([ProviderCall(raw_text=_ok_body(), latency_ms=1.0,
                                              usage=UsageMetadata())])
    result = _client(provider).read_field(_request())

    assert result.cost.basis == "estimated_usage"
    assert result.cost.measured_usd is None
    assert result.cost.estimated_usd > 0
    # Image tokens are unknown, so the estimate is explicitly incomplete.
    assert result.cost.estimate_excludes_image_tokens is True
    assert result.usage.image_tokens is None


def test_unknown_price_row_reports_unknown_rather_than_guessing():
    provider = ScriptedProvider([_ok_body()], price_row="no-such-model",
                                usage=UsageMetadata(input_tokens=10,
                                                    output_tokens=10))
    result = _client(provider).read_field(_request())
    assert result.cost.basis == "unknown"
    assert result.cost.measured_usd is None and result.cost.estimated_usd is None


def test_a_rejected_answer_still_reports_the_cost_it_incurred():
    provider = ScriptedProvider(
        ["not json at all"], usage=UsageMetadata(input_tokens=800, output_tokens=20))
    result = _client(provider).read_field(_request())

    # We paid for the call even though the answer is unusable; hiding that would
    # flatter the cost story.
    assert result.ok is False and result.rejects
    assert result.cost.basis == "measured_usage" and result.cost.measured_usd > 0
