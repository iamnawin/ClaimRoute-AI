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

# kind -> builder. Adding a provider is a new module plus one row here. No client
# and no contract change; that is what keeps "model-agnostic" structural.
_KINDS = {"openai_chat_completions", "openrouter_chat_completions"}


def _build_openai(spec: dict) -> MultimodalProvider:
    from engine.escalation.providers.openai_provider import OpenAIMultimodalProvider
    return OpenAIMultimodalProvider(
        model=spec.get("model", "gpt-5-nano"),
        endpoint=spec.get("endpoint",
                          "https://api.openai.com/v1/chat/completions"),
        api_key_env=spec.get("api_key_env", "OPENAI_API_KEY"),
        max_output_tokens=int(spec.get("max_output_tokens", 200)),
        price_row=spec.get("price_row") or spec.get("model", "gpt-5-nano"),
    )


def _build_openrouter(spec: dict) -> MultimodalProvider:
    from engine.escalation.providers.openrouter_provider import (DEFAULT_ENDPOINT,
                                                                 API_KEY_ENV,
                                                                 OpenRouterProvider)
    # No model default. An aggregator with a guessed model id is how you end up
    # billed for something nobody chose, so configuration must be explicit.
    return OpenRouterProvider(
        model=spec.get("model", ""),
        endpoint=spec.get("endpoint", DEFAULT_ENDPOINT),
        # The key env is fixed by the adapter contract; a spec cannot redirect it
        # at another variable and quietly borrow a different provider's key.
        api_key_env=API_KEY_ENV,
        max_output_tokens=int(spec.get("max_output_tokens", 200)),
        price_row=spec.get("price_row") or spec.get("model", ""),
        referer=spec.get("referer", ""), title=spec.get("title", ""),
    )


_BUILDERS = {"openai_chat_completions": _build_openai,
             "openrouter_chat_completions": _build_openrouter}


def build_provider(name: str, spec: dict) -> MultimodalProvider:
    """Construct a provider from its configs/multimodal_providers.yaml entry."""
    kind = (spec or {}).get("kind")
    if kind not in _KINDS:
        raise MultimodalError(
            ErrorCategory.CONFIGURATION_ERROR,
            f"provider {name!r} has unknown kind {kind!r}; known kinds: {sorted(_KINDS)}")

    provider = _BUILDERS[kind](spec or {})
    provider.name = name
    return provider
