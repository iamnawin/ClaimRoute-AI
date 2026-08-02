"""Gemini vision adapter (gemini-2.5-flash-lite / gemini-3.1-flash-lite).

Second provider, same interface — that is the point. Model-agnostic
orchestration is demonstrated by two adapters differing only in transport, with
zero pipeline changes between them.

Requires GEMINI_API_KEY. Fails loudly when absent (see openai_engine.py).
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

ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
TIMEOUT_S = 30


class GeminiVisionEngine(VisionEngine):
    def __init__(self, model: str = "gemini-2.5-flash-lite"):
        self.name = model
        self.model = model
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                f"GEMINI_API_KEY not set — cannot run vision engine {model!r}. "
                "Use the offline-oracle adapter for boundary testing, and label "
                "its numbers as projected."
            )

    def read_field(self, crop, field_name: str, **kw) -> VisionResponse:
        prompt = PROMPT.format(field_name=field_name,
                               expectation=expectation_for(field_name))
        payload = {
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": crop_b64(crop)}},
            ]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "maxOutputTokens": 200},
        }
        url = ENDPOINT.format(model=self.model)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"x-goog-api-key": self.api_key,
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

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            usage = body.get("usageMetadata", {})
            in_tok = usage.get("promptTokenCount", 0)
            out_tok = usage.get("candidatesTokenCount", 0)
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
        usage = body.get("usageMetadata", {})
        in_tok = usage.get("promptTokenCount", 0)
        out_tok = usage.get("candidatesTokenCount", 0)

        resp = parse_response(text, self.model)
        resp.input_tokens, resp.output_tokens = in_tok, out_tok
        resp.cost_usd = price_call(self.model, in_tok, out_tok)
        resp.latency_ms = ms
        return resp
