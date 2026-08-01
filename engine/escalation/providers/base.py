"""Provider interface — transport only.

A provider's entire job is: take a MultimodalRequest, perform one call, and come
back with the raw body text plus normalised usage. It does NOT parse the answer,
ground it, price it, retry it, or decide policy. Keeping providers this thin is
what makes "model-agnostic" a structural property instead of a claim: a second
adapter cannot introduce a second opinion about what a valid answer is, because
it never sees that question.

Failures are raised as MultimodalError with a category. A provider must not
return a sentinel or swallow an error — the client needs the category to decide
retryability.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from engine.escalation.contract import REQUIRED_KEYS, MultimodalRequest, UsageMetadata


@dataclass
class ProviderCall:
    """One completed round trip.

    `raw_text` is transient: the client hashes it, parses it, and drops it. It is
    never persisted, logged, or placed in an audit record.

    `reported_cost_usd` is the provider's own charge for this call, when it
    returns one. None means the provider did not report a cost — which stays
    unknown rather than being defaulted to zero, because a zero would understate
    spend against a budget.

    `actual_model` is the model the provider says it actually served. It can
    differ from the model requested (aggregators substitute), so it is recorded
    separately instead of assuming the request was honoured.
    """
    raw_text: str
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    latency_ms: float = 0.0
    http_status: Optional[int] = None
    reported_cost_usd: Optional[float] = None
    actual_model: str = ""

    def __repr__(self) -> str:                  # keep bodies out of tracebacks
        return (f"ProviderCall(chars={len(self.raw_text)}, "
                f"status={self.http_status}, latency_ms={self.latency_ms:.1f})")


class MultimodalProvider(ABC):
    """Transport adapter. Subclass + a price row in configs/prices.yaml is the
    entire cost of adding a provider."""

    name: str = "base"
    model: str = ""
    price_row: str = ""

    @abstractmethod
    def invoke(self, request: MultimodalRequest, *, timeout_s: float) -> ProviderCall:
        """One call. Raises MultimodalError (categorised) on any failure."""

    def estimate_text_tokens(self, request: MultimodalRequest) -> int:
        """Coarse prompt-size estimate used ONLY when a provider reports no usage.

        Text tokens only. Image tokens are not estimated here and are never
        invented — see CostBreakdown, where such an estimate is marked a lower
        bound rather than presented as the cost.
        """
        return max(1, len(build_prompt(request)) // 4)


def build_prompt(request: MultimodalRequest) -> str:
    """The strict, field-scoped instruction. One box, one value, no prose."""
    return PROMPT_TEMPLATE.format(
        field_name=request.field_name,
        expectation=request.expectation or "a short printed value")


# Deliberately boring and closed-form. The response schema is stated as the only
# acceptable output so that any deviation is a contract breach the client can
# reject mechanically rather than a judgement call.
PROMPT_TEMPLATE = """You are reading ONE field box cropped from a US healthcare claim form.

Field: {field_name}
Expected content: {expectation}

Return ONLY a JSON object with exactly these three keys and nothing else:
  "value"      - the value printed in this box, transcribed exactly, or null if the box is empty or unreadable.
  "visible"    - true if you can actually see the box contents, false otherwise.
  "confidence" - a number from 0.0 to 1.0.

Rules:
- Transcribe only what is printed in THIS box. Never infer, complete, or correct a value.
- Never report a value from a neighbouring box.
- If you cannot see the contents, return {{"value": null, "visible": false, "confidence": 0.0}}.
- Do not add explanation, markdown, or any key beyond the three above."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# Derived, not hand-maintained. Editing the prompt or the response schema changes
# these automatically, so a duplicate-call fingerprint computed under the old
# wording can never match one computed under the new wording — a stale cached
# answer cannot survive a contract change just because nobody bumped a constant.
PROMPT_VERSION = _digest(PROMPT_TEMPLATE)
SCHEMA_VERSION = _digest(",".join(sorted(REQUIRED_KEYS)))
