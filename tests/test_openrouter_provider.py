"""OpenRouter transport: request shape, error typing, usage and cost normalisation.

The HTTP opener is injected in every test, so nothing here touches the network;
`test_no_socket_is_opened_anywhere_in_this_module` proves it by severing the
socket layer and driving a full call through the client.

No real API key is read, written, or asserted on. The placeholder below is
obviously not a credential.
"""
import json
import socket
import urllib.error

import pytest
from PIL import Image

from engine.escalation.client import MultimodalClient
from engine.escalation.contract import CropImage, MultimodalRequest
from engine.escalation.errors import ErrorCategory, MultimodalError
from engine.escalation.providers import build_provider
from engine.escalation.providers.openrouter_provider import (API_KEY_ENV,
                                                             DEFAULT_ENDPOINT,
                                                             OpenRouterProvider)

MODEL = "openai/gpt-5-nano"
FAKE_KEY = "placeholder-not-a-real-key"


# --------------------------------------------------------------------- helpers

def _request(field_name="provider_npi"):
    crop = CropImage.from_pil(Image.new("RGB", (90, 32), "white"),
                              source_page_px=(1700, 2200), region_px=(90, 32))
    return MultimodalRequest(field_name, crop,
                             expectation="a 10-digit NPI number",
                             doc_id="synthetic-doc", page_id="p1")


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


def _envelope(content, usage=None, model=MODEL, finish="stop"):
    return {"id": "gen-1", "model": model,
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": usage or {}}


def _opener(body, status=200, capture=None):
    def open_it(request, timeout=None):
        if capture is not None:
            capture.append({"request": request, "timeout": timeout})
        return _Response(body, status)
    return open_it


def _raising(exc):
    def open_it(request, timeout=None):
        raise exc
    return open_it


def _provider(opener=None, model=MODEL, **kw):
    return OpenRouterProvider(model=model, opener=opener, **kw)


def _answer(value="1234567893"):
    return json.dumps({"value": value, "visible": True, "confidence": 0.95})


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)


# ------------------------------------------------------ construction & config

def test_provider_is_built_from_config_by_kind():
    provider = build_provider("openrouter", {
        "kind": "openrouter_chat_completions", "model": MODEL,
        "max_output_tokens": 200, "price_row": "gpt-5-nano"})
    assert isinstance(provider, OpenRouterProvider)
    assert provider.model == MODEL
    assert provider.endpoint == DEFAULT_ENDPOINT


def test_config_cannot_redirect_the_key_to_another_variable():
    """A spec must not be able to borrow a different provider's credential."""
    provider = build_provider("openrouter", {
        "kind": "openrouter_chat_completions", "model": MODEL,
        "api_key_env": "OPENAI_API_KEY"})
    assert provider.api_key_env == API_KEY_ENV


def test_auto_router_is_refused_at_construction():
    with pytest.raises(MultimodalError) as e:
        _provider(model="openrouter/auto")
    assert e.value.category is ErrorCategory.CONFIGURATION_ERROR


def test_free_variants_are_refused_at_construction():
    with pytest.raises(MultimodalError) as e:
        _provider(model="qwen/qwen-2.5-vl:free")
    assert e.value.category is ErrorCategory.CONFIGURATION_ERROR


def test_empty_model_is_refused():
    with pytest.raises(MultimodalError):
        _provider(model="")


def test_missing_key_is_refused_before_any_socket(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)

    def explode(*a, **k):
        raise AssertionError("a call was attempted without a key")

    with pytest.raises(MultimodalError) as e:
        _provider(opener=explode).invoke(_request(), timeout_s=5)
    assert e.value.category is ErrorCategory.CONFIGURATION_ERROR


# ---------------------------------------------------------------- request shape

def test_request_disables_fallback_models_and_asks_for_usage():
    seen = []
    _provider(opener=_opener(_envelope(_answer()), capture=seen)).invoke(
        _request(), timeout_s=9)
    payload = json.loads(seen[0]["request"].data.decode())
    assert payload["provider"]["allow_fallbacks"] is False
    assert payload["usage"] == {"include": True}
    assert payload["model"] == MODEL
    assert payload["max_tokens"] == 200
    assert payload["response_format"] == {"type": "json_object"}
    assert seen[0]["timeout"] == 9


def test_request_carries_no_alternate_models_list():
    """`models` would let OpenRouter substitute; it must never be sent."""
    seen = []
    _provider(opener=_opener(_envelope(_answer()), capture=seen)).invoke(
        _request(), timeout_s=5)
    assert "models" not in json.loads(seen[0]["request"].data.decode())


def test_the_image_is_sent_as_one_inline_png_crop():
    seen = []
    _provider(opener=_opener(_envelope(_answer()), capture=seen)).invoke(
        _request(), timeout_s=5)
    content = json.loads(seen[0]["request"].data.decode())["messages"][0]["content"]
    images = [p for p in content if p["type"] == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_attribution_headers_are_optional_and_carry_no_credential():
    seen = []
    _provider(opener=_opener(_envelope(_answer()), capture=seen),
              referer="https://example.invalid", title="ClaimRoute AI").invoke(
        _request(), timeout_s=5)
    headers = seen[0]["request"].headers
    assert headers["Http-referer"] == "https://example.invalid"
    assert headers["X-title"] == "ClaimRoute AI"
    assert FAKE_KEY not in json.dumps({k: v for k, v in headers.items()
                                       if k.lower() != "authorization"})


# ---------------------------------------------- 15. usage and cost normalisation

def test_provider_reported_cost_is_captured():
    call = _provider(opener=_opener(_envelope(_answer(), usage={
        "prompt_tokens": 812, "completion_tokens": 21, "cost": 0.00004891,
    }))).invoke(_request(), timeout_s=5)
    assert call.reported_cost_usd == pytest.approx(0.00004891)
    assert call.usage.input_tokens == 812
    assert call.usage.output_tokens == 21


def test_absent_cost_stays_unknown_rather_than_zero():
    """Zero would let an unmetered call pass a budget check."""
    call = _provider(opener=_opener(_envelope(_answer(), usage={
        "prompt_tokens": 10, "completion_tokens": 2}))).invoke(_request(), timeout_s=5)
    assert call.reported_cost_usd is None


def test_absent_token_categories_stay_unknown():
    call = _provider(opener=_opener(_envelope(_answer(), usage={
        "prompt_tokens": 10, "completion_tokens": 2}))).invoke(_request(), timeout_s=5)
    assert call.usage.image_tokens is None
    assert call.usage.cached_tokens is None
    assert call.usage.reasoning_tokens is None
    assert call.usage.to_dict()["image_tokens"] == "unknown"


def test_detailed_token_categories_are_normalised_when_reported():
    call = _provider(opener=_opener(_envelope(_answer(), usage={
        "prompt_tokens": 900, "completion_tokens": 30, "cost": 0.0001,
        "prompt_tokens_details": {"cached_tokens": 128, "image_tokens": 700},
        "completion_tokens_details": {"reasoning_tokens": 12},
    }))).invoke(_request(), timeout_s=5)
    assert call.usage.cached_tokens == 128
    assert call.usage.image_tokens == 700
    assert call.usage.reasoning_tokens == 12


def test_non_numeric_usage_values_are_treated_as_unknown():
    call = _provider(opener=_opener(_envelope(_answer(), usage={
        "prompt_tokens": "many", "completion_tokens": None, "cost": "free",
    }))).invoke(_request(), timeout_s=5)
    assert call.usage.input_tokens is None
    assert call.usage.output_tokens is None
    assert call.reported_cost_usd is None


def test_actual_model_served_is_recorded():
    call = _provider(opener=_opener(
        _envelope(_answer(), model="openai/gpt-5-nano-2026-01-01"))).invoke(
        _request(), timeout_s=5)
    assert call.actual_model == "openai/gpt-5-nano-2026-01-01"


# ------------------------------------------------------------ 14. typed errors

@pytest.mark.parametrize("status,category", [
    (401, ErrorCategory.AUTHENTICATION_ERROR),
    (403, ErrorCategory.AUTHENTICATION_ERROR),
    (408, ErrorCategory.TIMEOUT),
    (429, ErrorCategory.RATE_LIMIT),
    (500, ErrorCategory.PROVIDER_5XX),
    (503, ErrorCategory.PROVIDER_5XX),
])
def test_http_errors_are_categorised(status, category):
    err = urllib.error.HTTPError(DEFAULT_ENDPOINT, status, "err", {}, None)
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_raising(err)).invoke(_request(), timeout_s=5)
    assert e.value.category is category


def test_error_object_inside_a_200_body_is_typed_not_parsed_as_an_answer():
    """OpenRouter returns upstream failures in-band; a 200 is not a success."""
    body = {"error": {"code": 429, "message": "upstream rate limited"}}
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_opener(body)).invoke(_request(), timeout_s=5)
    assert e.value.category is ErrorCategory.RATE_LIMIT


def test_error_object_without_a_usable_code_is_still_typed():
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_opener({"error": {"message": "something"}})).invoke(
            _request(), timeout_s=5)
    assert e.value.category is ErrorCategory.UNKNOWN_PROVIDER_ERROR


def test_provider_error_details_never_echo_the_provider_message():
    """A provider message can quote request content; it must not reach a detail."""
    body = {"error": {"code": 400, "message": "bad value 1234567893 in image"}}
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_opener(body)).invoke(_request(), timeout_s=5)
    assert "1234567893" not in e.value.detail


def test_timeout_is_typed():
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_raising(socket.timeout())).invoke(_request(), timeout_s=5)
    assert e.value.category is ErrorCategory.TIMEOUT


def test_network_failure_is_typed():
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_raising(urllib.error.URLError("no route"))).invoke(
            _request(), timeout_s=5)
    assert e.value.category is ErrorCategory.NETWORK_ERROR


def test_content_filter_is_typed():
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_opener(_envelope(_answer(), finish="content_filter"))).invoke(
            _request(), timeout_s=5)
    assert e.value.category is ErrorCategory.CONTENT_BLOCKED


def test_non_json_body_is_typed_as_invalid_response():
    class _Raw:
        status = 200

        def read(self):
            return b"<html>gateway</html>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with pytest.raises(MultimodalError) as e:
        _provider(opener=lambda r, timeout=None: _Raw()).invoke(_request(), timeout_s=5)
    assert e.value.category is ErrorCategory.INVALID_RESPONSE


def test_missing_envelope_fields_are_typed_as_invalid_response():
    with pytest.raises(MultimodalError) as e:
        _provider(opener=_opener({"model": MODEL, "choices": []})).invoke(
            _request(), timeout_s=5)
    assert e.value.category is ErrorCategory.INVALID_RESPONSE


# ------------------------- 12/13. structured-response validation via the client

def _client(opener, **kw):
    provider = _provider(opener=opener, **kw)
    return MultimodalClient(config={"request_policy": {}, "transport": {},
                                    "response_policy": {}},
                            provider=provider, enabled=True, sleep=lambda s: None)


def test_structured_response_validation_accepts_a_well_formed_answer():
    result = _client(_opener(_envelope(_answer(), usage={
        "prompt_tokens": 800, "completion_tokens": 20, "cost": 0.00005,
    }))).read_field(_request())
    assert result.ok
    assert result.answer.value == "1234567893"
    assert result.answer.visible is True
    assert result.rejects == []


def test_invalid_json_is_rejected():
    result = _client(_opener(_envelope("the NPI is 1234567893"))).read_field(_request())
    assert not result.ok
    assert result.answer is None
    assert any("invalid JSON" in r for r in result.rejects)


def test_extra_keys_are_rejected_as_a_contract_breach():
    body = json.dumps({"value": "1234567893", "visible": True,
                       "confidence": 0.9, "patient_name": "DOE, JANE"})
    result = _client(_opener(_envelope(body))).read_field(_request())
    assert not result.ok
    assert any("unexpected keys" in r for r in result.rejects)


def test_a_value_of_the_wrong_shape_is_rejected():
    result = _client(_opener(_envelope(_answer("NOT-AN-NPI")))).read_field(_request())
    assert not result.ok
    assert any("type mismatch" in r for r in result.rejects)


def test_rejection_reasons_never_contain_the_extracted_value():
    result = _client(_opener(_envelope(_answer("NOT-AN-NPI")))).read_field(_request())
    assert "NOT-AN-NPI" not in " ".join(result.rejects)


def test_raw_body_is_hashed_and_discarded():
    result = _client(_opener(_envelope(_answer()))).read_field(_request())
    assert len(result.raw_sha256) == 64
    blob = json.dumps(result.audit)
    assert "1234567893" not in blob
    assert FAKE_KEY not in blob


# ------------------------------- 16. measured and reported costs stay separate

def test_provider_reported_cost_outranks_the_local_price_computation():
    result = _client(_opener(_envelope(_answer(), usage={
        "prompt_tokens": 812, "completion_tokens": 21, "cost": 0.00004891,
    })), price_row="gpt-5-nano").read_field(_request())

    assert result.cost.basis == "provider_reported"
    assert result.cost.reported_usd == pytest.approx(0.00004891)
    # The local list-price figure is kept alongside, not overwritten, so the two
    # can be compared when a price row drifts.
    assert result.cost.measured_usd is not None
    assert result.cost.billed_usd == pytest.approx(0.00004891)


def test_without_a_reported_cost_the_basis_falls_back_to_measured_usage():
    result = _client(_opener(_envelope(_answer(), usage={
        "prompt_tokens": 812, "completion_tokens": 21})),
        price_row="gpt-5-nano").read_field(_request())
    assert result.cost.basis == "measured_usage"
    assert result.cost.reported_usd is None
    assert result.cost.billed_usd == result.cost.measured_usd


def test_an_estimate_is_never_treated_as_money_billed():
    """estimated_usd excludes image tokens; billed_usd must not adopt it."""
    result = _client(_opener(_envelope(_answer())), price_row="gpt-5-nano").read_field(
        _request())
    assert result.cost.basis == "estimated_usage"
    assert result.cost.estimated_usd is not None
    assert result.cost.billed_usd is None


def test_model_substitution_is_recorded_not_silently_accepted():
    result = _client(_opener(_envelope(_answer(), model="meta/llama-substitute"))
                     ).read_field(_request())
    assert result.model_substituted is True
    assert result.actual_model == "meta/llama-substitute"
    assert result.audit["model_substituted"] is True


# ------------------------------------------------------------ 17. no network

def test_no_socket_is_opened_anywhere_in_this_module(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unit tests must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    result = _client(_opener(_envelope(_answer(), usage={
        "prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001,
    }))).read_field(_request())
    assert result.ok
