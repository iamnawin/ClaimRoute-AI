"""OpenAI chat-completions provider — the real multimodal path.

Transport only (see providers/base.py). Uses urllib from the standard library,
matching the repo's existing vision adapters: enabling a paid model adds no new
dependency and no new licence row.

The API key is read from the environment named in configs/multimodal_providers.yaml
and is never stored on the instance beyond the call, never logged, and never
included in an error detail. A missing key is a CONFIGURATION_ERROR raised before
any socket is opened.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

from engine.escalation.contract import MultimodalRequest, UsageMetadata
from engine.escalation.errors import ErrorCategory, MultimodalError, category_for_status
from engine.escalation.providers.base import (MultimodalProvider, ProviderCall,
                                              build_prompt)

DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"

# Substrings that identify a 400 as a policy or image problem rather than a
# generic bad request. Matched against the provider's error CODE/TYPE fields
# only — never against anything derived from the crop.
_BLOCKED_MARKERS = ("content_policy", "content_filter", "safety", "moderation")
_IMAGE_MARKERS = ("image", "invalid_image", "unsupported_image", "image_parse")


class OpenAIMultimodalProvider(MultimodalProvider):
    name = "openai"

    def __init__(self, *, model: str = "gpt-5-nano",
                 endpoint: str = DEFAULT_ENDPOINT,
                 api_key_env: str = "OPENAI_API_KEY",
                 max_output_tokens: int = 200,
                 price_row: str = "", opener=None):
        self.model = model
        self.endpoint = endpoint
        self.api_key_env = api_key_env
        self.max_output_tokens = max_output_tokens
        self.price_row = price_row or model
        # Injectable for tests. The default is the real urlopen; unit tests never
        # construct this class with the default, and never reach the network.
        self._opener = opener or urllib.request.urlopen

    # ------------------------------------------------------------------ key

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MultimodalError(
                ErrorCategory.CONFIGURATION_ERROR,
                f"{self.api_key_env} is not set; refusing to call {self.model!r}")
        return key

    # --------------------------------------------------------------- call

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
            "max_completion_tokens": self.max_output_tokens,
        }
        status, body_bytes, latency_ms = self._perform(payload, key, timeout_s)

        try:
            body = json.loads(body_bytes.decode())
            text = body["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError,
                TypeError):
            raise MultimodalError(
                ErrorCategory.INVALID_RESPONSE,
                "response envelope missing choices[0].message.content",
                status_code=status) from None

        if body.get("choices", [{}])[0].get("finish_reason") == "content_filter":
            raise MultimodalError(ErrorCategory.CONTENT_BLOCKED,
                                  "provider returned finish_reason=content_filter",
                                  status_code=status)

        return ProviderCall(raw_text=text or "",
                            usage=self._usage(body.get("usage") or {}),
                            latency_ms=latency_ms, http_status=status)

    # ----------------------------------------------------------- transport

    def extra_headers(self) -> dict:
        """Provider-specific headers. Never carries credentials."""
        return {}

    def _perform(self, payload: dict, key: str,
                 timeout_s: float) -> tuple[int, bytes, float]:
        """One HTTP round trip with every failure categorised.

        Kept separate from invoke() so an OpenAI-compatible provider reuses this
        exact error mapping rather than restating it — two adapters must not be
        able to disagree about what a 429 or a socket timeout means.
        """
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     **self.extra_headers()})

        t0 = time.perf_counter()
        try:
            with self._opener(req, timeout=timeout_s) as r:
                status = getattr(r, "status", 200)
                body_bytes = r.read()
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except (socket.timeout, TimeoutError):
            raise MultimodalError(ErrorCategory.TIMEOUT,
                                  f"no response within {timeout_s}s") from None
        except urllib.error.URLError as e:
            # URLError wraps a socket timeout on some platforms.
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise MultimodalError(ErrorCategory.TIMEOUT,
                                      f"no response within {timeout_s}s") from None
            raise MultimodalError(ErrorCategory.NETWORK_ERROR,
                                  f"{type(e).__name__}") from None
        except Exception as e:                    # never leak an uncategorised failure
            raise MultimodalError(ErrorCategory.UNKNOWN_PROVIDER_ERROR,
                                  f"{type(e).__name__}") from None

        return status, body_bytes, (time.perf_counter() - t0) * 1000

    # -------------------------------------------------------------- errors

    def _http_error(self, e: urllib.error.HTTPError) -> MultimodalError:
        status = int(getattr(e, "code", 0) or 0)
        code = ""
        try:
            detail = json.loads(e.read().decode()).get("error") or {}
            # Only the machine-readable code/type is inspected. The human message
            # can echo request content, so it is never read into an error detail.
            code = f"{detail.get('code') or ''} {detail.get('type') or ''}".lower()
        except Exception:
            code = ""

        if status == 400 and any(m in code for m in _BLOCKED_MARKERS):
            return MultimodalError(ErrorCategory.CONTENT_BLOCKED,
                                   "provider blocked the request", status_code=status)
        if status == 400 and any(m in code for m in _IMAGE_MARKERS):
            return MultimodalError(ErrorCategory.UNSUPPORTED_IMAGE,
                                   "provider rejected the image", status_code=status)

        category = category_for_status(status)
        retry_after = None
        try:
            raw_ra = (e.headers or {}).get("Retry-After")
            retry_after = float(raw_ra) if raw_ra else None
        except (TypeError, ValueError):
            retry_after = None
        return MultimodalError(category, f"HTTP {status}", status_code=status,
                               retry_after_s=retry_after)

    # --------------------------------------------------------------- usage

    @staticmethod
    def _usage(usage: dict) -> UsageMetadata:
        """Normalise OpenAI usage into the shared shape.

        Absent counts stay None (unknown). OpenAI does not break out image tokens
        for a chat-completions image part, so `image_tokens` is left unknown
        rather than back-computed from a tile formula we cannot verify.
        """
        def _int(value):
            return int(value) if isinstance(value, (int, float)) and not isinstance(
                value, bool) else None

        in_details = usage.get("prompt_tokens_details") or {}
        out_details = usage.get("completion_tokens_details") or {}
        return UsageMetadata(
            input_tokens=_int(usage.get("prompt_tokens")),
            output_tokens=_int(usage.get("completion_tokens")),
            image_tokens=_int(in_details.get("image_tokens")),   # normally absent
            cached_tokens=_int(in_details.get("cached_tokens")),
            reasoning_tokens=_int(out_details.get("reasoning_tokens")),
        )
