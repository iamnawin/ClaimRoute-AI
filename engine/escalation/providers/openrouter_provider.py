"""OpenRouter provider — an OpenAI-compatible aggregator, held to extra rules.

Transport only, exactly like every other provider (see providers/base.py). It
subclasses the OpenAI adapter because OpenRouter speaks the chat-completions
wire format; what differs is credential source, cost reporting, and the fact
that an AGGREGATOR CAN SUBSTITUTE THE MODEL. Three consequences shape this file:

1. `allow_fallbacks: false` is sent on every request and cannot be configured
   on. A silent substitution to a pricier model is an unbounded spend, and the
   whole point of this path is a bounded one.
2. The model the provider says it SERVED is recorded separately from the model
   requested. Callers compare them; this adapter never assumes they match.
3. OpenRouter reports what it actually charged. That figure outranks any local
   price-table computation, because it is the only number that is a real charge
   rather than list price times reported tokens.

Two model classes are refused at construction, before a key is ever read:
Auto Router (the model is unknown until after you are billed) and `:free`
variants (different rate limits, different data-retention terms, and a
zero-cost receipt that would prove nothing about the paid path).

The API key is read from OPENROUTER_API_KEY at call time. It is never stored on
the instance, logged, placed in an error detail, or written to config.
"""
from __future__ import annotations

import json

from engine.escalation.contract import MultimodalRequest, UsageMetadata
from engine.escalation.errors import ErrorCategory, MultimodalError
from engine.escalation.providers.base import ProviderCall, build_prompt
from engine.escalation.providers.openai_provider import OpenAIMultimodalProvider

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
API_KEY_ENV = "OPENROUTER_API_KEY"

# Model ids that must never be selected, checked before any network access.
AUTO_ROUTER_IDS = frozenset({"openrouter/auto", "auto"})
FREE_SUFFIX = ":free"


class OpenRouterProvider(OpenAIMultimodalProvider):
    """OpenAI-compatible transport against OpenRouter, with substitution locked off."""

    name = "openrouter"

    def __init__(self, *, model: str,
                 endpoint: str = DEFAULT_ENDPOINT,
                 api_key_env: str = API_KEY_ENV,
                 max_output_tokens: int = 200,
                 price_row: str = "",
                 referer: str = "", title: str = "",
                 opener=None):
        reject = self.model_rejection(model)
        if reject:
            raise MultimodalError(ErrorCategory.CONFIGURATION_ERROR, reject)
        super().__init__(model=model, endpoint=endpoint, api_key_env=api_key_env,
                         max_output_tokens=max_output_tokens,
                         price_row=price_row or model, opener=opener)
        self.referer = referer
        self.title = title

    # --------------------------------------------------------------- policy

    @staticmethod
    def model_rejection(model: str) -> str:
        """-> reason the model id is refused, or "" when it is acceptable.

        Static and pure so the same rule can be applied by the live-call policy
        before a provider is ever constructed.
        """
        mid = (model or "").strip()
        if not mid:
            return "no model id configured"
        if mid.lower() in AUTO_ROUTER_IDS:
            return ("Auto Router is refused: the served model is unknown until "
                    "after the call is billed")
        if mid.lower().endswith(FREE_SUFFIX):
            return (f"free variants are refused: {mid!r} bills nothing, so it "
                    "cannot produce a receipt for the paid path")
        return ""

    def extra_headers(self) -> dict:
        """Attribution headers only. Optional, and never credential-bearing."""
        headers = {}
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title
        return headers

    # ----------------------------------------------------------------- call

    def invoke(self, request: MultimodalRequest, *, timeout_s: float) -> ProviderCall:
        key = self._api_key()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": build_prompt(request)},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{request.crop.b64}"}},
            ]}],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
            # Ask for the accounting block; without it OpenRouter omits `cost`
            # and we would be left pricing the call ourselves.
            "usage": {"include": True},
            # Not configurable. See the module docstring.
            "provider": {"allow_fallbacks": False},
        }

        status, body_bytes, latency_ms = self._perform(payload, key, timeout_s)

        try:
            body = json.loads(body_bytes.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MultimodalError(ErrorCategory.INVALID_RESPONSE,
                                  "response body is not JSON",
                                  status_code=status) from None

        # OpenRouter can return HTTP 200 with an error object in the body when an
        # upstream fails. Treating that as success would hand the parser an empty
        # string and report a schema fault for what is really a transport fault.
        if isinstance(body, dict) and body.get("error"):
            raise self._body_error(body["error"], status)

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise MultimodalError(
                ErrorCategory.INVALID_RESPONSE,
                "response envelope missing choices[0].message.content",
                status_code=status) from None

        if body.get("choices", [{}])[0].get("finish_reason") == "content_filter":
            raise MultimodalError(ErrorCategory.CONTENT_BLOCKED,
                                  "provider returned finish_reason=content_filter",
                                  status_code=status)

        usage = body.get("usage") or {}
        return ProviderCall(raw_text=text or "",
                            usage=self._usage(usage),
                            latency_ms=latency_ms, http_status=status,
                            reported_cost_usd=self._reported_cost(usage),
                            actual_model=str(body.get("model") or ""))

    # --------------------------------------------------------------- errors

    def _body_error(self, error, status: int) -> MultimodalError:
        """Categorise an error object returned inside a 200 body.

        Only the machine-readable code is inspected. A provider's human message
        can echo request content, so it never reaches an error detail.
        """
        code = 0
        if isinstance(error, dict):
            try:
                code = int(error.get("code") or 0)
            except (TypeError, ValueError):
                code = 0
        if code >= 400:
            from engine.escalation.errors import category_for_status
            return MultimodalError(category_for_status(code),
                                   f"provider error code {code}", status_code=code)
        return MultimodalError(ErrorCategory.UNKNOWN_PROVIDER_ERROR,
                               "provider returned an error object",
                               status_code=status)

    # ---------------------------------------------------------------- usage

    @staticmethod
    def _reported_cost(usage: dict) -> float | None:
        """The provider's own charge for this call, in USD, or None if absent.

        None means UNKNOWN and must stay unknown. Defaulting a missing cost to
        0.0 would let an unmetered call pass a budget check, which is exactly
        the failure this path exists to prevent.
        """
        raw = usage.get("cost")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)

    @staticmethod
    def _usage(usage: dict) -> UsageMetadata:
        """Normalise OpenRouter usage into the shared shape.

        Absent counts stay None. OpenRouter does not break out image tokens as a
        separate category, so `image_tokens` is left unknown rather than
        back-computed from a tile formula we cannot verify against a bill.
        """
        def _int(value):
            return int(value) if isinstance(value, (int, float)) and not isinstance(
                value, bool) else None

        in_details = usage.get("prompt_tokens_details") or {}
        out_details = usage.get("completion_tokens_details") or {}
        return UsageMetadata(
            input_tokens=_int(usage.get("prompt_tokens")),
            output_tokens=_int(usage.get("completion_tokens")),
            image_tokens=_int(in_details.get("image_tokens")),    # normally absent
            cached_tokens=_int(in_details.get("cached_tokens")),
            reasoning_tokens=_int(out_details.get("reasoning_tokens")),
        )
