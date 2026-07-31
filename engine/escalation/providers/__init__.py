"""Provider adapters for the multimodal escalation boundary.

Only real, configured providers are constructible by name. Test doubles live in
`fake.py` and must be injected explicitly — a fake can never be reached through
configuration.
"""
from __future__ import annotations

from engine.escalation.errors import ErrorCategory, MultimodalError
from engine.escalation.providers.base import (MultimodalProvider, ProviderCall,
                                              build_prompt)

__all__ = ["MultimodalProvider", "ProviderCall", "build_prompt", "build_provider"]

# kind -> constructor. Adding a provider is a new module plus one row here and a
# price row in configs/prices.yaml. No client or contract change.
_KINDS = {"openai_chat_completions"}


def build_provider(name: str, spec: dict) -> MultimodalProvider:
    """Construct a provider from its configs/multimodal_providers.yaml entry."""
    kind = (spec or {}).get("kind")
    if kind not in _KINDS:
        raise MultimodalError(
            ErrorCategory.CONFIGURATION_ERROR,
            f"provider {name!r} has unknown kind {kind!r}; known kinds: {sorted(_KINDS)}")

    from engine.escalation.providers.openai_provider import OpenAIMultimodalProvider
    provider = OpenAIMultimodalProvider(
        model=spec.get("model", "gpt-5-nano"),
        endpoint=spec.get("endpoint",
                          "https://api.openai.com/v1/chat/completions"),
        api_key_env=spec.get("api_key_env", "OPENAI_API_KEY"),
        max_output_tokens=int(spec.get("max_output_tokens", 200)),
        price_row=spec.get("price_row") or spec.get("model", "gpt-5-nano"),
    )
    provider.name = name
    return provider
