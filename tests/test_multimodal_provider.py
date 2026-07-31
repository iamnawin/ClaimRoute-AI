"""OpenAI provider adapter: transport, error categorisation, usage normalisation.

The HTTP opener is injected in every test, so nothing here touches the network.
No API key is read, written, or asserted on beyond its presence/absence.
"""
import io
import json
import socket
import urllib.error

import pytest
from PIL import Image

from engine.escalation.contract import CropImage, MultimodalRequest
from engine.escalation.errors import ErrorCategory, MultimodalError, category_for_status
from engine.escalation.providers import build_provider
from engine.escalation.providers.base import build_prompt
from engine.escalation.providers.openai_provider import OpenAIMultimodalProvider

KEY_ENV = "CLAIMROUTE_TEST_FAKE_KEY_ENV"


def _request(field_name="billing_provider_npi"):
    crop = CropImage.from_pil(Image.new("RGB", (90, 32), "white"),
                              source_page_px=(1700, 2200), region_px=(90, 32))
    return MultimodalRequest(field_name, crop, expectation="a 10-digit NPI number",
                             doc_id="synthetic-doc")


class _Response:
    def __init__(self, body, status=200):
        self._body = json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _envelope(content, usage=None):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": usage or {}}


def _opener_returning(body, status=200, capture=None):
    def opener(request, timeout=None):
        if capture is not None:
            capture.append({"request": request, "timeout": timeout})
        return _Response(body, status)
    return opener


def _opener_raising(exc):
    def opener(request, timeout=None):
        raise exc
    return opener


def _http_error(status, payload=None, headers=None):
    return urllib.error.HTTPError(
        "https://api.openai.com/v1/chat/completions", status, "err", headers or {},
        io.BytesIO(json.dumps(payload or {}).encode()))


def _provider(opener, monkeypatch, *, key="test-key-not-real"):
    if key is not None:
        monkeypatch.setenv(KEY_ENV, key)
    else:
        monkeypatch.delenv(KEY_ENV, raising=False)
    return OpenAIMultimodalProvider(model="gpt-5-nano", api_key_env=KEY_ENV,
                                    price_row="gpt-5-nano", opener=opener)


# ------------------------------------------------------------------- config

def test_missing_api_key_is_a_configuration_error_before_any_call(monkeypatch):
    calls = []
    provider = _provider(_opener_returning(_envelope("{}"), capture=calls),
                         monkeypatch, key=None)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)

    assert excinfo.value.category == ErrorCategory.CONFIGURATION_ERROR
    assert calls == []                       # no socket was opened
    assert excinfo.value.retryable is False


def test_api_key_is_read_from_the_environment_only(monkeypatch):
    calls = []
    provider = _provider(_opener_returning(_envelope('{"value":null,"visible":false,'
                                                     '"confidence":0.0}'),
                                           capture=calls), monkeypatch,
                         key="secret-value-under-test")
    provider.invoke(_request(), timeout_s=5)

    header = calls[0]["request"].get_header("Authorization")
    assert header == "Bearer secret-value-under-test"
    # The key lives in the environment and the outgoing header, nowhere else.
    assert not hasattr(provider, "api_key")
    assert "secret-value-under-test" not in repr(provider.__dict__)


def test_build_provider_rejects_an_unknown_kind():
    with pytest.raises(MultimodalError) as excinfo:
        build_provider("mystery", {"kind": "telepathy"})
    assert excinfo.value.category == ErrorCategory.CONFIGURATION_ERROR


def test_build_provider_constructs_the_configured_openai_adapter():
    provider = build_provider("openai", {"kind": "openai_chat_completions",
                                         "model": "gpt-5-nano",
                                         "api_key_env": "OPENAI_API_KEY",
                                         "price_row": "gpt-5-nano"})
    assert isinstance(provider, OpenAIMultimodalProvider)
    assert provider.name == "openai" and provider.price_row == "gpt-5-nano"


# ------------------------------------------------------------------ request

def test_request_sends_the_crop_and_the_strict_prompt(monkeypatch):
    calls = []
    provider = _provider(_opener_returning(_envelope('{"value":"1393521955",'
                                                     '"visible":true,'
                                                     '"confidence":0.9}'),
                                           capture=calls), monkeypatch)
    request = _request()
    provider.invoke(request, timeout_s=11)

    sent = json.loads(calls[0]["request"].data.decode())
    assert calls[0]["timeout"] == 11
    assert sent["response_format"] == {"type": "json_object"}
    parts = sent["messages"][0]["content"]
    assert parts[0]["text"] == build_prompt(request)
    # The image travels as the crop's own bytes, base64 in a data URL.
    assert parts[1]["image_url"]["url"].endswith(request.crop.b64)


def test_prompt_names_the_three_key_schema_and_forbids_prose():
    prompt = build_prompt(_request())
    for key in ('"value"', '"visible"', '"confidence"'):
        assert key in prompt
    assert "Do not add explanation" in prompt
    assert "neighbouring box" in prompt


# ------------------------------------------------------------------- errors

@pytest.mark.parametrize("status,expected", [
    (401, ErrorCategory.AUTHENTICATION_ERROR),
    (403, ErrorCategory.AUTHENTICATION_ERROR),
    (408, ErrorCategory.TIMEOUT),
    (429, ErrorCategory.RATE_LIMIT),
    (500, ErrorCategory.PROVIDER_5XX),
    (503, ErrorCategory.PROVIDER_5XX),
    (418, ErrorCategory.UNKNOWN_PROVIDER_ERROR),
])
def test_http_status_maps_to_a_category(status, expected, monkeypatch):
    provider = _provider(_opener_raising(_http_error(status)), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == expected
    assert excinfo.value.status_code == status
    assert category_for_status(status) in (expected, ErrorCategory.UNKNOWN_PROVIDER_ERROR)


def test_content_policy_rejection_is_its_own_category(monkeypatch):
    error = _http_error(400, {"error": {"code": "content_policy_violation",
                                        "type": "invalid_request_error"}})
    provider = _provider(_opener_raising(error), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.CONTENT_BLOCKED
    assert excinfo.value.retryable is False


def test_image_rejection_is_its_own_category(monkeypatch):
    error = _http_error(400, {"error": {"code": "invalid_image",
                                        "type": "invalid_request_error"}})
    provider = _provider(_opener_raising(error), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.UNSUPPORTED_IMAGE


def test_finish_reason_content_filter_is_blocked(monkeypatch):
    body = {"choices": [{"message": {"content": "{}"},
                         "finish_reason": "content_filter"}], "usage": {}}
    provider = _provider(_opener_returning(body), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.CONTENT_BLOCKED


def test_retry_after_header_is_captured(monkeypatch):
    error = _http_error(429, headers={"Retry-After": "3"})
    provider = _provider(_opener_raising(error), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.retry_after_s == 3.0
    assert excinfo.value.retryable is True


@pytest.mark.parametrize("exc", [socket.timeout("slow"), TimeoutError("slow")])
def test_socket_timeout_maps_to_timeout(exc, monkeypatch):
    provider = _provider(_opener_raising(exc), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.TIMEOUT


def test_url_error_maps_to_network_error(monkeypatch):
    provider = _provider(_opener_raising(urllib.error.URLError("no route")),
                         monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.NETWORK_ERROR
    assert excinfo.value.retryable is True


def test_url_error_wrapping_a_timeout_maps_to_timeout(monkeypatch):
    provider = _provider(_opener_raising(urllib.error.URLError(socket.timeout())),
                         monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.TIMEOUT


def test_malformed_envelope_is_invalid_response(monkeypatch):
    provider = _provider(_opener_returning({"unexpected": True}), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert excinfo.value.category == ErrorCategory.INVALID_RESPONSE


def test_error_details_never_echo_the_provider_message(monkeypatch):
    # A provider's human-readable message can quote request content, so only the
    # machine-readable code is inspected and the message is never surfaced.
    error = _http_error(400, {"error": {"code": "invalid_image",
                                        "message": "could not parse SMITH, JOHN"}})
    provider = _provider(_opener_raising(error), monkeypatch)
    with pytest.raises(MultimodalError) as excinfo:
        provider.invoke(_request(), timeout_s=5)
    assert "SMITH" not in str(excinfo.value)
    assert "SMITH" not in json.dumps(excinfo.value.to_dict())


# -------------------------------------------------------------------- usage

def test_usage_is_normalised_from_the_provider_shape(monkeypatch):
    usage = {"prompt_tokens": 812, "completion_tokens": 19,
             "prompt_tokens_details": {"cached_tokens": 640},
             "completion_tokens_details": {"reasoning_tokens": 7}}
    provider = _provider(_opener_returning(_envelope('{"value":null,"visible":false,'
                                                     '"confidence":0.0}', usage)),
                         monkeypatch)
    call = provider.invoke(_request(), timeout_s=5)

    assert call.usage.input_tokens == 812 and call.usage.output_tokens == 19
    assert call.usage.cached_tokens == 640 and call.usage.reasoning_tokens == 7
    # Not reported by this provider, and never back-computed from a tile formula.
    assert call.usage.image_tokens is None
    assert call.http_status == 200 and call.latency_ms >= 0


def test_absent_usage_stays_unknown_rather_than_zero(monkeypatch):
    provider = _provider(_opener_returning(_envelope('{"value":null,"visible":false,'
                                                     '"confidence":0.0}')),
                         monkeypatch)
    call = provider.invoke(_request(), timeout_s=5)

    assert call.usage.input_tokens is None and call.usage.output_tokens is None
    assert call.usage.billable_known is False


def test_provider_call_repr_hides_the_response_body(monkeypatch):
    provider = _provider(_opener_returning(_envelope('{"value":"SMITH, JOHN",'
                                                     '"visible":true,'
                                                     '"confidence":0.9}')),
                         monkeypatch)
    call = provider.invoke(_request("patient_name"), timeout_s=5)
    assert "SMITH" not in repr(call) and "chars=" in repr(call)
