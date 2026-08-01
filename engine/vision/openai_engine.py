"""OpenAI vision adapter (gpt-5-nano / gpt-5-mini).

Live path. Requires OPENAI_API_KEY; without it, construction fails loudly rather
than silently degrading to a stub — a pipeline that quietly stops calling the
model it claims to call is a cost lie waiting to happen.

Zero-retention and crops-only are enforced upstream (engine/escalate.py checks
policy; engine/cropper.py physically bounds what can be sent).
"""
from __future__ import annotations

import json
import os
import time
import hashlib
import urllib.error
import urllib.request

from engine.cropper import crop_b64
from engine.vision.base import (PROMPT, VisionEngine, VisionResponse,
                                VisionErrorType, expectation_for, parse_response,
                                price_call)

ENDPOINT = "https://api.openai.com/v1/chat/completions"
TIMEOUT_S = 30


class OpenAIVisionEngine(VisionEngine):
    def __init__(self, model: str = "gpt-5-nano"):
        self.name = model
        self.model = model
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                f"OPENAI_API_KEY not set — cannot run vision engine {model!r}. "
                "Use the offline-oracle adapter for boundary testing, and label "
                "its numbers as projected."
            )

    def read_field(self, crop, field_name: str, **kw) -> VisionResponse:
        prompt = PROMPT.format(field_name=field_name,
                               expectation=expectation_for(field_name))
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{crop_b64(crop)}"}},
            ]}],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 200,
        }
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                body = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError,
                json.JSONDecodeError) as e:
            if isinstance(e, TimeoutError):
                error_type = VisionErrorType.TIMEOUT
            elif isinstance(e, (UnicodeDecodeError, json.JSONDecodeError)):
                error_type = VisionErrorType.INVALID_RESPONSE
            else:
                error_type = VisionErrorType.TRANSPORT
            return VisionResponse(None, "", 0.0, model=self.model,
                                  latency_ms=(time.perf_counter() - t0) * 1000,
                                  parse_error=f"transport: {type(e).__name__}: {e}",
                                  error_type=error_type)
        ms = (time.perf_counter() - t0) * 1000

        if not isinstance(body, dict):
            response = parse_response(json.dumps(body), self.model)
            response.latency_ms = ms
            return response

        usage = body.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return VisionResponse(
                None, "", 0.0, model=self.model, latency_ms=ms,
                input_tokens=in_tok, output_tokens=out_tok,
                cost_usd=price_call(self.model, in_tok, out_tok),
                raw_sha256=hashlib.sha256(
                    json.dumps(body, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                parse_error="no candidate text in response",
                error_type=VisionErrorType.INVALID_RESPONSE,
            )

        resp = parse_response(text, self.model)
        resp.input_tokens, resp.output_tokens = in_tok, out_tok
        resp.cost_usd = price_call(self.model, in_tok, out_tok)
        resp.latency_ms = ms
        return resp
