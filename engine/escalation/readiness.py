"""One shared answer to "is the paid provider usable right now, and if not, why?"

`live_policy.LiveCallGovernor` decides whether ONE call may happen. It is the
only authority, and it runs again immediately before transport. This module
answers the question the UI asks a hundred times before that: what should the
operator be told, and what should they do next?

It exists because those two questions had drifted apart. The panel derived its
own boolean from configs/multimodal_providers.yaml, so six unrelated causes —
no key, configuration off, live-test permission withheld, a model missing from
the allowlist, an ineligible input, a malformed flag — all reached the screen as
"External provider disabled". An operator who had exported
CLAIMROUTE_MULTIMODAL_ENABLED and restarted saw exactly what a fresh clone saw,
with nothing to indicate which of the remaining switches was the problem.

Three properties are load-bearing:

- READY IS DISPLAY STATE, NEVER AUTHORISATION. `state is READY` means nothing in
  the operator's setup is missing. It does not mean a call is permitted, and it
  cannot make one permitted: the shipped config keeps `live_provider.enabled`
  false, and the governor re-checks flags, credential, provenance, allowlist and
  both budgets before any transport. Widening readiness cannot widen spending.

- ELIGIBILITY IS BORROWED, NOT REIMPLEMENTED. The input and model checks call
  the governor's own predicates. A second copy of "is this a crop?" is a second
  thing to keep in sync, and the one that drifts is always the one on screen.

- A MALFORMED FLAG IS AN ERROR, NOT A FALSE. `CLAIMROUTE_MULTIMODAL_ENABLED=yes
  please` silently reading as off is how "I set the flag" and "the flag is not
  set" are both true at once.

Configuration precedence, one order, used by every gate here:

    secure environment override  ->  application configuration  ->  safe default

The environment may open a gate the tracked file leaves closed, so an operator
enables a session without editing committed config. It is never the other way
around: a shipped file cannot open a gate the environment closed, because the
file travels with a clone and the environment does not.

Nothing in this module reads, stores, logs, hashes, or measures the API key. It
records only whether one is present.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from engine.escalation.live_policy import (DEFAULT_KEY_ENV, LIVE_TEST_ENV,
                                           MULTIMODAL_ENABLED_ENV,
                                           LiveCallGovernor)

# The documented truthy set, shared with live_policy so the gate and the panel
# cannot disagree about what "true" means.
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigurationFlagError(ValueError):
    """An environment flag held a value that is neither true nor false.

    Raised rather than defaulted. The operator believes they configured
    something; telling them it is off would be a lie they cannot debug.
    """


def parse_flag(name: str, raw) -> bool:
    """Parse one documented boolean environment value.

    Case-insensitive and whitespace-safe. Unset and empty are false, because an
    absent variable is a genuine "not configured" rather than a typo. Anything
    else raises.
    """
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if text == "":
        return False
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ConfigurationFlagError(
        f"{name} must be one of {', '.join(TRUE_VALUES)} (true) or "
        f"{', '.join(FALSE_VALUES)} (false), case-insensitive. Fix the value "
        f"and restart the application.")


class ReadinessState(str, Enum):
    """Every state the provider panel can be in. Exhaustive on purpose — a state
    that has no name here is a state that reaches the screen as some other
    state's message."""

    READY = "READY"
    DISABLED = "DISABLED"
    MISSING_KEY = "MISSING_KEY"
    TEST_PERMISSION_REQUIRED = "TEST_PERMISSION_REQUIRED"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    INPUT_INELIGIBLE = "INPUT_INELIGIBLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INITIALIZATION_ERROR = "INITIALIZATION_ERROR"


@dataclass(frozen=True)
class ProviderReadiness:
    """The verdict, plus everything needed to render it without recomputing it."""

    state: ReadinessState
    ready: bool
    reason: str
    required_action: str

    provider_name: str = ""
    model: str = ""
    model_alias: str = ""
    operating_mode: str = ""
    key_env: str = DEFAULT_KEY_ENV

    key_present: bool = False
    adapter_flag: bool = False
    live_test_flag: bool = False
    config_enabled: bool = False
    model_allowlisted: bool = False
    model_image_capable: bool = False
    # None when no input has been selected yet. "Nothing chosen" is not a
    # refusal, and rendering it as one tells the operator to fix a document
    # they have not picked.
    input_eligible: Optional[bool] = None

    def diagnostics(self) -> dict:
        """The PHI-safe gate report, suitable for an on-screen expander.

        Presence of the credential only. Never its value, prefix, length, or
        hash — each of those narrows a search, and an expander is a screenshot
        waiting to happen.
        """
        return {
            f"{self.key_env}_PRESENT": self.key_present,
            MULTIMODAL_ENABLED_ENV: self.adapter_flag,
            LIVE_TEST_ENV: self.live_test_flag,
            "CONFIG_PROVIDER_ENABLED": self.config_enabled,
            "SELECTED_MODE": self.operating_mode,
            "SELECTED_MODEL": self.model,
            "MODEL_ALLOWLISTED": self.model_allowlisted,
            "MODEL_IMAGE_CAPABLE": self.model_image_capable,
            "INPUT_ELIGIBLE": self.input_eligible,
            "PROVIDER_READY": self.ready,
            "BLOCKING_REASON": self.state.value,
        }

    def to_dict(self) -> dict:
        return {"state": self.state.value, "ready": self.ready,
                "reason": self.reason, "required_action": self.required_action,
                "provider_name": self.provider_name, "model": self.model,
                "model_alias": self.model_alias,
                "operating_mode": self.operating_mode,
                "key_env": self.key_env, "key_present": self.key_present,
                "adapter_flag": self.adapter_flag,
                "live_test_flag": self.live_test_flag,
                "config_enabled": self.config_enabled,
                "model_allowlisted": self.model_allowlisted,
                "model_image_capable": self.model_image_capable,
                "input_eligible": self.input_eligible}


def evaluate_readiness(*, config: dict, env: Optional[dict] = None,
                       mode: Optional[str] = None,
                       request=None) -> ProviderReadiness:
    """Compute the current readiness verdict. Never opens a socket, never spends.

    Gate order matches the operator's repair order rather than the governor's
    cost order: the credential first, then the two switches, then the model,
    then the selected input. Each answer is the next thing they must fix.

    Recomputed on every call. Caching this would make "restart from a configured
    terminal" the only way to observe a corrected setting, which is the failure
    this contract exists to remove.
    """
    # Deferred: app.service imports engine, and importing it at module scope
    # would make engine depend on the application layer.
    from engine.escalation.model_router import ModelRouter

    values = dict(env) if env is not None else None
    live = config.get("live_provider") or {}
    live_test_env = live.get("live_test_env", LIVE_TEST_ENV)

    def _get(name: str):
        if values is not None:
            return values.get(name)
        import os
        return os.environ.get(name)

    provider_name = live.get("provider") or config.get("active_provider") or ""
    provider_spec = (config.get("providers") or {}).get(provider_name) or {}
    key_env = provider_spec.get("api_key_env") or DEFAULT_KEY_ENV
    key_present = bool(str(_get(key_env) or "").strip())

    # 0. Malformed flags before anything else. A value nobody can interpret must
    #    not be interpreted.
    try:
        adapter_flag = parse_flag(MULTIMODAL_ENABLED_ENV,
                                  _get(MULTIMODAL_ENABLED_ENV))
        live_test_flag = parse_flag(live_test_env, _get(live_test_env))
    except ConfigurationFlagError as error:
        return ProviderReadiness(
            state=ReadinessState.CONFIGURATION_ERROR, ready=False,
            reason=str(error),
            required_action=("Correct the environment variable to a documented "
                             "value and restart the application."),
            provider_name=provider_name, key_env=key_env,
            key_present=key_present)

    config_enabled = bool(config.get("enabled", False)
                          and live.get("enabled", False))

    # Resolve the model the selected mode would actually send. Structural
    # authoring errors surface as a state, not a traceback on a results page.
    try:
        resolved = ModelRouter(provider_config=config).resolve(mode or "balanced")
        model, alias = resolved.model_id, resolved.alias
        resolved_mode = resolved.mode
        allowlisted = bool(resolved.allowlisted)
        image_capable = bool(resolved.supports_images)
        model_blocked = resolved.blocked_reason
    except Exception as error:                  # noqa: BLE001 - reported, not raised
        return ProviderReadiness(
            state=ReadinessState.INITIALIZATION_ERROR, ready=False,
            reason=f"The provider could not be initialised: {error}",
            required_action=("Check configs/multimodal_providers.yaml and "
                             "configs/multimodal_models.yaml for the selected mode."),
            provider_name=provider_name, operating_mode=mode or "",
            key_env=key_env, key_present=key_present,
            adapter_flag=adapter_flag, live_test_flag=live_test_flag,
            config_enabled=config_enabled)

    # The router reads image support from the model table; the governor reads it
    # from the allowlist entry's checked `vision:` declaration. A call needs
    # BOTH, so the panel reports both — reporting only the router's view would
    # show "image capable" for a model the governor is about to refuse.
    try:
        entry = LiveCallGovernor(config, env=values).allowlist_entry(model)
    except Exception:                           # noqa: BLE001 - reported below
        entry = None
    allowlisted = bool(allowlisted and entry is not None)
    image_capable = bool(image_capable and (entry or {}).get("vision") is True)

    common = {"provider_name": provider_name, "model": model, "model_alias": alias,
              "operating_mode": resolved_mode, "key_env": key_env,
              "key_present": key_present, "adapter_flag": adapter_flag,
              "live_test_flag": live_test_flag, "config_enabled": config_enabled,
              "model_allowlisted": allowlisted,
              "model_image_capable": image_capable}

    # Gate order is the operator's REPAIR order, not the governor's cost order.
    # Each answer is the next thing they must change, so the most categorical
    # switch comes first and the most specific condition last. A missing
    # credential is reported after the switches because telling someone to
    # export a key for a provider the application has turned off sends them to
    # do work that changes nothing.
    #
    # The tracked configuration approving the live path satisfies BOTH switches:
    # editing `enabled` and `live_provider.enabled` is already the deliberate,
    # reviewable act the environment flags exist to substitute for. The flags
    # are the per-session route, and that route needs both.
    enable_gate = config_enabled or adapter_flag
    live_test_gate = config_enabled or live_test_flag

    # 1. Switched on at all.
    if not enable_gate:
        return ProviderReadiness(
            state=ReadinessState.DISABLED, ready=False,
            reason=("The provider is disabled by application configuration."
                    if not key_present else
                    "Credentials are available, but the provider is disabled by "
                    "application configuration."),
            required_action=(f"Set {MULTIMODAL_ENABLED_ENV}=true before starting "
                             "the application, or enable the approved live-provider "
                             "configuration."),
            **common)

    # 2. Explicit live-test permission. Deliberately separate from the adapter
    #    flag so enabling the adapter for a fake provider can never turn a paid
    #    provider on as a side effect.
    if not live_test_gate:
        return ProviderReadiness(
            state=ReadinessState.TEST_PERMISSION_REQUIRED, ready=False,
            reason=("The provider is configured, but explicit live-test "
                    "permission is disabled."),
            required_action=(f"Set {live_test_env}=true before starting the "
                             "application."),
            **common)

    # 3. Model. The allowlist is approval to bill; a model missing from it, or
    #    one that does not declare vision, is refused before a credential or an
    #    input matters, because no key makes an unapproved model callable.
    if not allowlisted or not image_capable or model_blocked:
        detail = model_blocked or (
            f"{model!r} is not on the approved allowlist"
            if not allowlisted else
            f"{model!r} does not declare image support")
        return ProviderReadiness(
            state=ReadinessState.MODEL_NOT_ALLOWED, ready=False,
            reason=f"The provider is configured, but the selected model cannot "
                   f"be used: {detail}.",
            required_action=("Choose an operating mode whose model is "
                             "allowlisted and image-capable, or add the model to "
                             "live_provider.model_allowlist after verifying it."),
            **common)

    # 4. Credential. Last of the configuration gates: everything above it is a
    #    decision the operator makes once, and this is the one they make per
    #    terminal.
    if not key_present:
        return ProviderReadiness(
            state=ReadinessState.MISSING_KEY, ready=False,
            reason=f"{key_env} is not available to this process.",
            required_action=(f"Set {key_env} in the terminal that starts the "
                             "application, then restart it. Local OCR, "
                             "validation, retry, review and exports remain "
                             "available without it."),
            **common)

    # 5. The selected input, when there is one. Absence of a selection is not a
    #    refusal — the panel must be able to say "ready" before anything is
    #    picked.
    if request is not None:
        ineligible = _input_refusal(config, values, request)
        if ineligible:
            return ProviderReadiness(
                state=ReadinessState.INPUT_INELIGIBLE, ready=False,
                reason=f"The provider is ready, but this input is not eligible "
                       f"for external processing: {ineligible}",
                required_action=("Select an approved synthetic field crop. Only "
                                 "those may be sent under the current safety "
                                 "policy."),
                input_eligible=False, **common)
        return ProviderReadiness(
            state=ReadinessState.READY, ready=True,
            reason=_ready_reason(resolved_mode, model),
            required_action="", input_eligible=True, **common)

    return ProviderReadiness(
        state=ReadinessState.READY, ready=True,
        reason=_ready_reason(resolved_mode, model),
        required_action="", input_eligible=None, **common)


def _ready_reason(mode: str, model: str) -> str:
    return f"Provider ready. Mode: {mode}. Model: {model}."


def _input_refusal(config: dict, env: Optional[dict], request) -> str:
    """-> refusal text, or "" when the input may be sent.

    Delegates to the governor's own predicates rather than restating them, so
    the panel and the gate cannot disagree about what an eligible input is.
    """
    if not getattr(request, "synthetic", False):
        return ("the request is not attested as synthetic, and the live path is "
                "synthetic-data-only")
    try:
        governor = LiveCallGovernor(config, env=env)
        return governor._check_crop(request)
    except Exception as error:                  # noqa: BLE001 - reported, not raised
        return f"eligibility could not be established ({error})"
