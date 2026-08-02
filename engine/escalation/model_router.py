"""Operating mode -> model alias -> exact model id, resolved once and explained.

This module exists because model selection had no owner. The provider entry in
configs/multimodal_providers.yaml carries a single static `model:`, and every
caller read it directly, so the operating mode could not influence which model
was billed: Economy, Balanced, and Accuracy all resolved to the same id. The
mode-to-model table in configs/multimodal_models.yaml was written but never
loaded by anything at runtime.

The split of authority is deliberate and is the whole point of the file:

  configs/multimodal_models.yaml     WHICH model each operating mode selects
  configs/multimodal_providers.yaml  HOW to reach a provider (endpoint, key env,
                                     timeouts, limits, budgets, allowlist)

A provider entry therefore describes a transport, not a choice. `providers.*.model`
survives only as the fallback for a mode with no configured alias, and it can no
longer silently override a mode that has one.

RESOLUTION IS NOT AUTHORISATION. This module answers "which model does this mode
select, and is that model usable?" and stops there. Whether a call may actually
be made stays with engine/escalation/live_policy.py, which re-checks the
allowlist itself. Resolving a model that is not allowlisted is a normal,
expected outcome: it is how the UI can name the model a mode selects while the
call remains blocked. A resolution never opens a socket and never spends.

Every refusal is a typed reason rather than a raised exception, because the UI
has to render "why is this blocked" next to the model it would have used.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

MODELS_CONFIG_PATH = Path("configs/multimodal_models.yaml")

# Mirrors app/service.py DEFAULT_MODE. Kept as a literal so the escalation
# boundary does not import the Streamlit-facing service layer.
DEFAULT_MODE = "balanced"


class ModelResolutionError(ValueError):
    """A mode names an alias that the models file does not define."""


@dataclass(frozen=True)
class ResolvedModel:
    """One fully-explained model selection, safe to render in a UI.

    `blocked_reason` being empty does NOT mean a call is authorised; it means
    nothing about the SELECTION itself is wrong. live_policy.py still owns the
    call decision and re-runs the allowlist check independently.
    """

    mode: str
    alias: str
    model_id: str
    supports_images: bool
    allowlisted: bool
    blocked_reason: str = ""
    is_fallback: bool = False
    fallback_alias: str = ""
    fallback_model_id: str = ""
    fallback_allowed: bool = False
    source: str = "multimodal_models.yaml"

    @property
    def usable(self) -> bool:
        """True when this selection could be sent, policy and budget aside."""
        return not self.blocked_reason

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "alias": self.alias,
            "model_id": self.model_id,
            "supports_images": self.supports_images,
            "allowlisted": self.allowlisted,
            "blocked_reason": self.blocked_reason,
            "is_fallback": self.is_fallback,
            "fallback_alias": self.fallback_alias,
            "fallback_model_id": self.fallback_model_id,
            "fallback_allowed": self.fallback_allowed,
            "source": self.source,
            "usable": self.usable,
        }


def load_models_config(path: Path | str = MODELS_CONFIG_PATH) -> dict:
    """Read the model-selection file.

    A missing file is not fatal. It degrades to the provider's static model,
    which is the behaviour that existed before this module and keeps a partial
    checkout running rather than breaking the whole app over routing metadata.
    """
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


class ModelRouter:
    """Resolves the model for an operating mode, and explains the result.

    Construction is cheap and side-effect free: no network, no credentials, no
    provider objects. It is safe to build one per render pass.
    """

    def __init__(self, models_config: Optional[dict] = None,
                 provider_config: Optional[dict] = None):
        # A caller-supplied provider config is self-contained: it may carry its
        # own mode table under `operating_mode_models`, and if it does not, it
        # gets none. Reading the repo-global file here instead would let a
        # file on disk override a config the caller passed in by hand, which
        # silently redirects the model a test or an embedder chose.
        if models_config is None and provider_config is not None:
            models_config = provider_config.get("operating_mode_models") or {}
        self._models_cfg = models_config if models_config is not None else load_models_config()
        self._provider_cfg = provider_config or {}
        self._models = self._models_cfg.get("models") or {}
        self._modes = self._models_cfg.get("operating_modes") or {}

    # ------------------------------------------------------------- allowlist

    @property
    def _live(self) -> dict:
        return self._provider_cfg.get("live_provider") or {}

    def allowlist_entry(self, model_id: str) -> Optional[dict]:
        """The approved-allowlist row for a model id, or None.

        Deliberately the same shape of lookup LiveCallGovernor performs. This
        one informs the UI; that one gates the money. Neither trusts the other.
        """
        for entry in self._live.get("model_allowlist") or []:
            if isinstance(entry, dict) and entry.get("id") == model_id:
                return entry
        return None

    def allowlisted_ids(self) -> list[str]:
        return [e.get("id") for e in self._live.get("model_allowlist") or []
                if isinstance(e, dict)]

    # -------------------------------------------------------------- fallback

    def _provider_static_model(self) -> str:
        """The provider entry's own `model:`, used only when a mode has no alias."""
        name = self._live.get("provider") or self._provider_cfg.get("active_provider") or ""
        spec = (self._provider_cfg.get("providers") or {}).get(name) or {}
        return spec.get("model") or ""

    def fallback_allowed(self, mode: str) -> bool:
        """Fallbacks require BOTH the mode to define one and limits to permit it.

        `allow_fallback_models` ships false, so a fallback listed in the models
        file stays inert until spend policy is explicitly widened. A model file
        alone must never be able to authorise a second billable model.
        """
        limits = self._live.get("limits") or {}
        if not bool(limits.get("allow_fallback_models", False)):
            return False
        return bool((self._modes.get(mode) or {}).get("fallback"))

    # -------------------------------------------------------------- resolve

    def resolve(self, mode: str, *, use_fallback: bool = False) -> ResolvedModel:
        """Resolve one operating mode to an exact, validated model id.

        Never raises for policy problems — an unknown mode, an unlisted model,
        or a model without vision support all resolve to a ResolvedModel that
        carries `blocked_reason`. Only a structurally broken config (a mode
        pointing at an alias that does not exist) raises, because that is an
        authoring error rather than a runtime state the UI should render.
        """
        # Stripped before the default is applied: "   " is truthy, so the
        # reverse order yields an empty mode that matches no entry in the table.
        mode = (mode or "").strip().lower() or DEFAULT_MODE
        mode_cfg = self._modes.get(mode)

        # No mode table at all, or a mode the file does not know: fall back to
        # the provider's static model. This is the pre-existing behaviour, now
        # explicitly labelled as such instead of being the only behaviour.
        if not mode_cfg:
            model_id = self._provider_static_model()
            entry = self.allowlist_entry(model_id)
            # A mode the table does not define, when the table EXISTS, is a
            # typo, not a request for the provider's static model. Resolving
            # it silently reported usable: true for a model the operator never
            # selected, so the selection is named unusable instead. An absent
            # table stays a legitimate degraded path (see load_models_config).
            if self._modes:
                reason = (f"operating mode {mode!r} is not defined in "
                          f"configs/multimodal_models.yaml operating_modes "
                          f"{sorted(self._modes)}")
            else:
                reason = "" if entry else (
                    f"{model_id!r} is not on live_provider.model_allowlist "
                    f"{self.allowlisted_ids()}" if model_id
                    else "no model configured for this mode and no provider model set")
            return ResolvedModel(
                mode=mode, alias="", model_id=model_id,
                supports_images=bool(entry and entry.get("vision") is True),
                allowlisted=entry is not None, blocked_reason=reason,
                source="multimodal_providers.yaml (no operating-mode entry)")

        alias_key = "fallback" if use_fallback else "primary"
        alias = mode_cfg.get(alias_key) or ""
        if not alias:
            raise ModelResolutionError(
                f"operating mode {mode!r} defines no {alias_key} model alias")

        spec = self._models.get(alias)
        if spec is None:
            raise ModelResolutionError(
                f"operating mode {mode!r} names alias {alias!r}, which is not "
                f"defined in models: {sorted(self._models)}")

        model_id = spec.get("model_id") or ""
        # The models file DECLARES vision support; the allowlist is what gets
        # CHECKED before spending. Both are reported so a mismatch is visible
        # rather than resolved silently in either direction.
        declares_images = spec.get("supports_images") is True
        entry = self.allowlist_entry(model_id)

        fb_alias = mode_cfg.get("fallback") or ""
        fb_spec = self._models.get(fb_alias) or {}

        return ResolvedModel(
            mode=mode, alias=alias, model_id=model_id,
            supports_images=declares_images,
            allowlisted=entry is not None,
            blocked_reason=self._blocked_reason(model_id, declares_images, entry),
            is_fallback=use_fallback,
            fallback_alias=fb_alias,
            fallback_model_id=fb_spec.get("model_id") or "",
            fallback_allowed=self.fallback_allowed(mode),
        )

    def _blocked_reason(self, model_id: str, declares_images: bool,
                        entry: Optional[dict]) -> str:
        """Why this model may not be sent, or "" when the selection is sound.

        Ordered from most categorical to most specific, so an operator is told
        the root problem rather than a downstream symptom of it.
        """
        if not model_id:
            return "no model id configured for the selected alias"

        # Refused classes are identity-based and outrank the allowlist: an
        # allowlist can be mis-edited, but Auto Router and :free variants are
        # never acceptable on the paid path.
        from engine.escalation.providers.openrouter_provider import OpenRouterProvider
        refusal = OpenRouterProvider.model_rejection(model_id)
        if refusal:
            return refusal

        if not declares_images:
            return (f"{model_id!r} does not declare supports_images: true in "
                    "configs/multimodal_models.yaml")
        if entry is None:
            return (f"{model_id!r} is not on live_provider.model_allowlist "
                    f"{self.allowlisted_ids()}; add and verify it before use")
        if entry.get("vision") is not True:
            return (f"{model_id!r} does not declare vision: true in its "
                    "allowlist entry")
        return ""
