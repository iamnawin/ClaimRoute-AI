"""Deterministic fake providers — test doubles for the multimodal boundary.

WHY: the part worth proving is the boundary (policy gate, crop-only enforcement,
strict parsing, grounding, retry bounds, error categorisation, usage and cost
separation). Proving it needs a responder, not a paid one — and certainly not a
network call inside a unit test.

HONESTY RULES, same as engine/vision/offline_engine.py:
- Nothing produced here is evidence about any real model's accuracy.
- Any cost derived from these adapters is PROJECTED, never measured spend.
- Seeding uses crc32 of a stable string, never Python's hash() (randomised per
  process — a hard rule in this repo).

These classes are never registered in configs/multimodal_providers.yaml: a test
double must be injected deliberately, never selected by configuration drift.
"""
from __future__ import annotations

import json
import zlib
from typing import Optional

from engine.escalation.contract import MultimodalRequest, UsageMetadata
from engine.escalation.errors import MultimodalError
from engine.escalation.providers.base import MultimodalProvider, ProviderCall


class ScriptedProvider(MultimodalProvider):
    """Replays a fixed script, one entry per call.

    Each entry is either a `ProviderCall`, a raw body `str`, or a
    `MultimodalError` to raise — which is what makes retry bounds, backoff and
    error categorisation testable without a socket.
    """

    name = "fake-scripted"

    def __init__(self, script, *, model: str = "fake-model",
                 price_row: str = "gpt-5-nano", usage: Optional[UsageMetadata] = None):
        self.model = model
        self.price_row = price_row
        self._script = list(script)
        self._usage = usage
        self.calls: list = []               # request_ids seen, for assertions
        self.timeouts: list = []            # timeout_s values seen

    def invoke(self, request: MultimodalRequest, *, timeout_s: float) -> ProviderCall:
        self.calls.append(request.request_id)
        self.timeouts.append(timeout_s)
        if not self._script:
            raise AssertionError("ScriptedProvider exhausted: unexpected extra call")
        item = self._script.pop(0)
        if isinstance(item, MultimodalError):
            raise item
        if isinstance(item, ProviderCall):
            return item
        return ProviderCall(raw_text=str(item), latency_ms=1.0, http_status=200,
                            usage=self._usage or UsageMetadata())

    @property
    def call_count(self) -> int:
        return len(self.calls)


class DeterministicFakeProvider(MultimodalProvider):
    """Answers from a caller-supplied table with seeded, reproducible behaviour.

    Same request in, same answer out, every run and every process. Used to
    exercise the happy path and the grounding rejections without a script.
    """

    name = "fake-deterministic"

    def __init__(self, answers: Optional[dict] = None, *,
                 model: str = "fake-model", price_row: str = "gpt-5-nano",
                 usage: Optional[UsageMetadata] = None,
                 confidence_range: tuple = (0.90, 0.99)):
        self.model = model
        self.price_row = price_row
        self.answers = dict(answers or {})
        self._usage = usage
        self._lo, self._hi = confidence_range
        self.calls: list = []

    def invoke(self, request: MultimodalRequest, *, timeout_s: float) -> ProviderCall:
        self.calls.append(request.request_id)
        value = self.answers.get(request.field_name)
        seed = zlib.crc32(f"{request.field_name}|{request.crop.sha256}".encode())
        span = self._hi - self._lo
        confidence = round(self._lo + (seed % 1000) / 1000 * span, 2)
        body = json.dumps({"value": value,
                           "visible": value is not None,
                           "confidence": confidence if value is not None else 0.0})
        return ProviderCall(
            raw_text=body, latency_ms=1.0, http_status=200,
            usage=self._usage or UsageMetadata(
                input_tokens=len(body) // 4 + 100, output_tokens=max(8, len(body) // 4)))
