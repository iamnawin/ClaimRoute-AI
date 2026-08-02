"""Consent-aware bridge from the ClaimRoute UI to one governed paid call.

The UI controls user intent only. Every provider, model, provenance, duplicate,
call-count, and spend check remains owned by ``LiveCallGovernor`` and is run
again immediately before transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from engine.escalation.client import MultimodalClient
from engine.escalation.contract import MultimodalRequest
from engine.escalation.errors import MultimodalError
from engine.escalation.live_policy import LiveCallGovernor, LiveCallOutcome
from engine.escalation.providers import build_provider
from engine.schemas import Verdict
from engine.validators import validate_field


UI_MAX_CALLS = 1


@dataclass(frozen=True)
class PermissionStatus:
    can_run: bool
    reason: str
    policy: Optional[LiveCallOutcome] = None


def permission_status(*, enabled: bool, confirmed: bool,
                      synthetic_attested: bool, request: MultimodalRequest | None,
                      governor: LiveCallGovernor, calls_used: int) -> PermissionStatus:
    """Return the current button state without mutating policy/session counters."""
    if not enabled:
        return PermissionStatus(False, "AI calls are disabled by the user.")
    if not confirmed:
        return PermissionStatus(False, "Paid-call confirmation is required.")
    if not synthetic_attested:
        return PermissionStatus(
            False, "Selected input is not attested as synthetic and PHI-free.")
    if request is None:
        return PermissionStatus(False, "No eligible crop could be proven.")
    if calls_used >= UI_MAX_CALLS:
        return PermissionStatus(False, "Paid-call limit reached")
    if governor.limits.allow_fallback_models:
        return PermissionStatus(False, "Fallback models must remain disabled.")
    if governor.limits.allow_automatic_reruns:
        return PermissionStatus(False, "Automatic reruns must remain disabled.")
    outcome = governor.preview_authorization(request, model=governor.model)
    if not outcome.allowed:
        return PermissionStatus(False, outcome.reason, outcome)
    return PermissionStatus(True, "All UI and backend preflight checks passed.", outcome)


def run_one_candidate(
        request: MultimodalRequest | None, *, enabled: bool, confirmed: bool,
        synthetic_attested: bool, governor: LiveCallGovernor, config: dict,
        calls_used: int, context: Optional[dict] = None,
        provider_builder: Callable = build_provider,
        client_factory: Callable = MultimodalClient) -> tuple[dict, str | None]:
    """Attempt one candidate and return a PHI-safe receipt plus accepted value.

    The accepted value is returned only in memory for the ordinary field result;
    it is deliberately absent from the receipt. Callers cannot bypass consent by
    invoking this helper directly because the same checks precede authorization.
    """
    status = permission_status(
        enabled=enabled, confirmed=confirmed,
        synthetic_attested=synthetic_attested, request=request,
        governor=governor, calls_used=calls_used)
    if not status.can_run:
        return _blocked_receipt(request, governor, status.reason), None

    # Re-authorize after the UI preflight. This is the decision that reserves the
    # fingerprint and permits transport; UI state alone never grants authority.
    outcome = governor.authorize(request, model=governor.model)
    if not outcome.allowed:
        governor.release()
        return _blocked_receipt(request, governor, outcome.reason, outcome), None

    try:
        # The provider spec supplies TRANSPORT only (endpoint, key env, token
        # cap). The model comes from the governor's mode resolution and is
        # written over any static `model:` in the spec, so a stale provider
        # entry cannot redirect a call the mode did not select.
        provider_spec = dict((config.get("providers") or {})[governor.provider_name])
        provider_spec["model"] = governor.model
        provider_spec.setdefault("price_row", governor.model)
        provider = provider_builder(governor.provider_name, provider_spec)
        if getattr(provider, "model", governor.model) != governor.model:
            governor.release()
            return _blocked_receipt(
                request, governor,
                "Constructed provider model does not match the authorized exact model.",
                outcome), None
        call_config = dict(config)
        call_config["transport"] = {
            **(config.get("transport") or {}),
            "max_attempts": 1,
            "retry_on_invalid_response": False,
        }
        client = client_factory(config=call_config, provider=provider, enabled=True)
        result = client.read_field(request)
    except (KeyError, MultimodalError):
        governor.release()
        return _blocked_receipt(
            request, governor, "Provider construction failed safely; no call was made.",
            outcome), None

    governor.record_call(outcome, result)
    candidate = result.answer.value if result.answer is not None else None
    validation_context = dict(context or {})
    validation_context[request.field_name] = candidate
    stamps = validate_field(request.field_name, candidate, validation_context)
    validators_passed = bool(stamps) and all(
        stamp.verdict is not Verdict.FAIL for stamp in stamps)
    accepted = bool(
        result.ok and candidate not in (None, "") and validators_passed
        and not result.model_substituted)

    cost = result.cost
    receipt = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fingerprint": outcome.fingerprint,
        "field_name": request.field_name,
        "provider": result.provider or governor.provider_name,
        "requested_model": governor.model,
        "actual_model": result.actual_model or result.model or governor.model,
        "model_substituted": result.model_substituted,
        "called_provider": bool(result.called_provider),
        "attempts": int(result.attempts),
        "measured_cost_usd": cost.billed_usd,
        "cost_basis": cost.basis,
        "latency_ms": float(result.latency_ms),
        "usage": result.usage.to_dict(),
        "grounding_passed": bool(result.ok),
        "confidence": result.answer.confidence if result.answer else None,
        "healthcare_validators_passed": validators_passed,
        "final_field_outcome": "ACCEPTED" if accepted else "HUMAN_REVIEW_REQUIRED",
        "policy_decision": outcome.decision.value,
        "raw_response_persisted": False,
        "crop_contents_persisted": False,
        "synthetic_crop_only": True,
        "external_calls_made": int(bool(result.called_provider)),
    }
    return receipt, candidate if accepted else None


def _blocked_receipt(request: MultimodalRequest | None, governor: LiveCallGovernor,
                     reason: str, outcome: LiveCallOutcome | None = None) -> dict:
    # ``request`` is None when no eligible crop could be proven. That is a
    # refusal like any other and still has to leave an auditable receipt.
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fingerprint": outcome.fingerprint if outcome else "",
        "field_name": request.field_name if request else "",
        "provider": governor.provider_name,
        "requested_model": governor.model,
        "called_provider": False,
        "attempts": 0,
        "measured_cost_usd": 0.0,
        "latency_ms": 0.0,
        "final_field_outcome": "HUMAN_REVIEW_REQUIRED",
        "policy_decision": outcome.decision.value if outcome else "BLOCKED_UI_PERMISSION",
        "reason": reason,
        "raw_response_persisted": False,
        "crop_contents_persisted": False,
        "synthetic_crop_only": bool(request.synthetic) if request else False,
        "external_calls_made": 0,
    }
