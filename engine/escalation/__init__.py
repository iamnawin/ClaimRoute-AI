"""Multimodal escalation adapter — provider-independent Tier-2 candidate generation.

STATUS: standalone and NOT integrated. Nothing in engine/extract.py imports this
package; connecting it to the governed escalation rung is a separate task. See
docs/development/multimodal_adapter_status.md.

DISABLED BY DEFAULT: configs/multimodal_providers.yaml ships `enabled: false`, so
importing or constructing a client cannot produce a network call.

Layout:
    errors.py      typed failure categories + retryability
    contract.py    request/result types, strict parsing, grounding, usage, cost
    providers/     transport adapters (OpenAI, OpenRouter) + deterministic fakes
    client.py      policy gate, bounded retries, hashing, safe audit record
    live_policy.py spending guardrails for the real, paid provider path

The live path is a further layer of "off". live_policy.LiveCallGovernor permits
zero spending by default and requires tracked config, two environment flags, a
key, synthetic input, a proven crop, an allowlisted vision model and remaining
budget before a single paid call is authorised.
"""
from __future__ import annotations

from engine.escalation.client import (MultimodalClient, build_request, load_config,
                                      request_from_page)
from engine.escalation.contract import (CostBreakdown, CropImage, MultimodalRequest,
                                        MultimodalResult, ParsedAnswer, UsageMetadata,
                                        ground_answer, parse_answer)
from engine.escalation.errors import (RETRYABLE, ErrorCategory, MultimodalError,
                                      category_for_status)
from engine.escalation.live_policy import (LiveCallGovernor, LiveCallOutcome,
                                           LiveDecision, SpendLimits, fingerprint)
from engine.escalation.providers import MultimodalProvider, ProviderCall, build_provider

__all__ = [
    "MultimodalClient", "MultimodalProvider", "ProviderCall",
    "MultimodalRequest", "MultimodalResult", "CropImage", "ParsedAnswer",
    "UsageMetadata", "CostBreakdown",
    "ErrorCategory", "MultimodalError", "RETRYABLE", "category_for_status",
    "parse_answer", "ground_answer",
    "build_request", "request_from_page", "build_provider", "load_config",
    "LiveCallGovernor", "LiveCallOutcome", "LiveDecision", "SpendLimits",
    "fingerprint",
]
