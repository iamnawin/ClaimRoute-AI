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
from engine.escalation.errors import (RETRYABLE, ErrorCategory, MultimodalError,
                                      explain)
from engine.escalation.live_policy import (ConfigurationFlagError,
                                           LiveCallGovernor, LiveCallOutcome)
from engine.escalation.providers import build_provider
from engine.schemas import Verdict
from engine.validators import validate_field


UI_MAX_CALLS = 1

# The document-level run is bounded by the governor's own per-document call
# limit, not by a second number invented here. UI_MAX_CALLS stays the cap for
# the single-field action so the two paths cannot drift apart.


@dataclass(frozen=True)
class PermissionStatus:
    can_run: bool
    reason: str
    policy: Optional[LiveCallOutcome] = None


@dataclass(frozen=True)
class Blocker:
    """One named reason the paid path cannot run, safe to render verbatim.

    Separate from PermissionStatus because the UI has to show every unmet
    requirement at once. A single "blocked" string tells an operator to fix one
    thing, discover the next, and repeat; the enablement checklist is finite and
    is better shown whole.
    """

    key: str
    label: str
    satisfied: bool
    detail: str = ""


def enablement_blockers(*, governor: LiveCallGovernor, config: dict,
                        synthetic_attested: bool,
                        request: MultimodalRequest | None,
                        candidates: int) -> list[Blocker]:
    """Every enablement requirement and whether it is currently met.

    Reports configuration, environment, credential, provenance, model, and
    budget state as independent rows. Nothing here authorises anything: the
    governor re-checks all of it before any transport.
    """
    live = (config.get("live_provider") or {})
    resolved = governor.resolved
    live_env = live.get("live_test_env", "CLAIMROUTE_LIVE_PROVIDER_TEST")
    rows = [
        Blocker(
            "provider_configuration",
            "Provider configuration enabled",
            _live_path_open(governor),
            "configs/multimodal_providers.yaml sets live_provider.enabled: "
            "false; set CLAIMROUTE_LIVE_PROVIDER_CONFIG_ENABLED=true to "
            "authorise this session without editing tracked configuration",
        ),
        Blocker(
            "environment_flag",
            "Environment flags set",
            governor.adapter_enabled and governor.live_test_enabled,
            f"CLAIMROUTE_MULTIMODAL_ENABLED and {live_env} must both be true",
        ),
        Blocker(
            "credential",
            "Provider credential present",
            governor.credential_available,
            f"{governor.key_env} is read from the environment and never displayed",
        ),
        Blocker(
            "synthetic_input",
            "Input attested synthetic",
            bool(synthetic_attested),
            "the live path is synthetic-data-only; organiser and official "
            "documents are refused by data policy",
        ),
        Blocker(
            "crop_available",
            "Field crop available",
            request is not None,
            "a bounded field crop must be provable; full pages are never sent",
        ),
        Blocker(
            "model_available",
            "Model usable for this mode",
            bool(resolved.model_id) and not resolved.blocked_reason,
            resolved.blocked_reason or f"{resolved.mode} selects {resolved.model_id}",
        ),
        Blocker(
            "budget",
            "Budget remaining",
            governor.session_remaining_usd > 0,
            f"session budget remaining {governor.session_remaining_usd:.6f} USD",
        ),
        Blocker(
            "eligible_fields",
            "Eligible unresolved fields",
            candidates > 0,
            f"{candidates} field(s) eligible under the selected operating mode",
        ),
    ]
    return rows


def _live_path_open(governor: LiveCallGovernor) -> bool:
    """Whether the live path is open, asked of the governor rather than the file.

    This row used to read the tracked YAML directly. That made it the one place
    in the UI that could not see the activation override, so a session the
    governor would have authorised still rendered "provider configuration
    disabled" — and the toggle this row guards was never drawn at all. A
    malformed override reads as closed here; the governor reports it properly
    when the operator reaches the action.
    """
    try:
        return governor.live_path_enabled
    except ConfigurationFlagError:
        return False


def unmet(blockers: list[Blocker]) -> list[Blocker]:
    return [row for row in blockers if not row.satisfied]


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
    except (KeyError, MultimodalError) as error:
        governor.release()
        # The category is preserved rather than flattened. "Provider
        # construction failed safely" was true and useless: a missing key, an
        # unconfigured provider entry and a refused model id all arrived as one
        # sentence, and none of them named the thing to fix.
        category = (error.category.value
                    if isinstance(error, MultimodalError)
                    else ErrorCategory.CONFIGURATION_ERROR.value)
        detail = (error.detail if isinstance(error, MultimodalError)
                  else f"provider entry missing: {error}")
        return _blocked_receipt(
            request, governor,
            "Provider construction failed safely; no call was made.",
            outcome, error_category=category, error_detail=detail), None

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
        # WHY it failed, carried to the screen. The client already categorises
        # every failure; the receipt used to drop that and leave the UI with
        # nothing but "multimodal failed" to say. A bad key, an empty balance,
        # a wrong model id and an outage need four different people to do four
        # different things.
        **_failure_fields(
            result.error,
            result.error_detail,
            # A provider that answered but was rejected downstream is not a
            # provider failure. Naming the stage that rejected it is what tells
            # an operator whether to fix a key or look at the value.
            fallback=("" if accepted else
                      "VALIDATION_REJECTED" if result.ok and candidate
                      else "INVALID_RESPONSE" if result.called_provider and not result.ok
                      else "")),
        "raw_response_persisted": False,
        "crop_contents_persisted": False,
        "synthetic_crop_only": True,
        "external_calls_made": int(bool(result.called_provider)),
    }
    return receipt, candidate if accepted else None


def run_eligible_fields(
        candidates: list[dict], *, enabled: bool, confirmed: bool,
        synthetic_attested: bool, governor: LiveCallGovernor, config: dict,
        request_builder: Callable, context_builder: Callable,
        apply_result: Callable, receipts: dict,
        progress: Callable[[dict], None] | None = None,
        runner: Callable = run_one_candidate) -> dict:
    """Escalate every eligible unresolved field under one document confirmation.

    Sequential by construction: ``allow_parallel_paid_calls`` is false, and the
    governor refuses a second call while one is in flight. Each field is a
    separate authorization, so the per-field, per-page, per-document, batch, and
    spend limits all still apply mid-run and stop the loop the moment one binds.

    A field whose candidate fails grounding or healthcare validation keeps its
    unresolved state; ``apply_result`` decides that, not this loop. The paid call
    still happened and is still counted and reported.
    """
    summary = {
        "attempted": 0, "accepted": 0, "rejected": 0, "blocked": 0,
        "external_calls": 0, "measured_cost_usd": 0.0, "stopped_reason": "",
    }
    # UI_MAX_CALLS caps the SINGLE-FIELD action at one call. It is deliberately
    # not applied per field here: this run is bounded by the governor's own
    # per-document, per-page, and batch limits, which is the authority that also
    # stops the loop below. Passing it would cap the document run at one field.
    per_field_calls_used = 0
    for index, candidate in enumerate(candidates, 1):
        fingerprint_seen = None
        request = request_builder(candidate)
        # A fingerprint already in `receipts` is a field this session paid for.
        # Re-sending it would be a duplicate charge for a result already held.
        status = permission_status(
            enabled=enabled, confirmed=confirmed,
            synthetic_attested=synthetic_attested, request=request,
            governor=governor, calls_used=per_field_calls_used)
        if status.policy is not None:
            fingerprint_seen = status.policy.fingerprint
        if fingerprint_seen and fingerprint_seen in receipts:
            summary["blocked"] += 1
            continue
        if not status.can_run:
            summary["blocked"] += 1
            # Count- and budget-bound refusals end the run: every later field
            # would fail the same way, and retrying each one only produces a
            # longer list of identical refusals.
            if status.policy is not None and _is_exhausted(status.policy):
                summary["stopped_reason"] = status.reason
                break
            continue

        if progress:
            progress({"index": index, "total": len(candidates),
                      "field_name": candidate.get("field_name", "")})
        receipt, accepted_value = runner(
            request, enabled=enabled, confirmed=confirmed,
            synthetic_attested=synthetic_attested, governor=governor,
            config=config, calls_used=per_field_calls_used,
            context=context_builder(candidate))
        key = receipt.get("fingerprint") or f"{candidate.get('field_name')}-{index}"
        receipts[key] = receipt
        summary["attempted"] += 1
        summary["external_calls"] += int(receipt.get("external_calls_made") or 0)
        summary["measured_cost_usd"] += float(receipt.get("measured_cost_usd") or 0)
        if receipt.get("called_provider"):
            apply_result(candidate, accepted_value, receipt)
            if receipt.get("final_field_outcome") == "ACCEPTED":
                summary["accepted"] += 1
            else:
                summary["rejected"] += 1
        else:
            summary["blocked"] += 1
    summary["measured_cost_usd"] = round(summary["measured_cost_usd"], 9)
    return summary


# Categories the UI must be able to show that are NOT provider transport
# failures. They are outcomes of our own gates, and an operator needs them
# named for the same reason: each implies a different next action.
VALIDATION_REJECTED = "VALIDATION_REJECTED"
BUDGET_BLOCKED = "BUDGET_BLOCKED"
DUPLICATE_REQUEST_BLOCKED = "DUPLICATE_REQUEST_BLOCKED"

_LOCAL_GUIDANCE = {
    VALIDATION_REJECTED: (
        "The provider answered and the answer failed healthcare validation.",
        "The field stays unresolved and goes to human review. The call was "
        "still made and is still counted and costed."),
    BUDGET_BLOCKED: (
        "A spend or call limit stopped this request before any call was made.",
        "Nothing was billed. Raise the limit deliberately, or send this field "
        "to human review."),
    DUPLICATE_REQUEST_BLOCKED: (
        "An identical request was already answered in this session.",
        "The previous answer is reused. Nothing was billed a second time."),
}

# LiveDecision values that are really budget or duplicate outcomes, mapped so
# the UI shows the operator-facing category rather than the internal enum.
_DECISION_CATEGORIES = {
    "BLOCKED_SESSION_BUDGET": BUDGET_BLOCKED,
    "BLOCKED_DOCUMENT_BUDGET": BUDGET_BLOCKED,
    "BLOCKED_FIELD_CALL_LIMIT": BUDGET_BLOCKED,
    "BLOCKED_PAGE_CALL_LIMIT": BUDGET_BLOCKED,
    "BLOCKED_DOCUMENT_CALL_LIMIT": BUDGET_BLOCKED,
    "BLOCKED_BATCH_CALL_LIMIT": BUDGET_BLOCKED,
    "BLOCKED_FIELD_PAID_ATTEMPTS": BUDGET_BLOCKED,
    "BLOCKED_DUPLICATE_REQUEST": DUPLICATE_REQUEST_BLOCKED,
    "REUSED_CACHED_RESULT": DUPLICATE_REQUEST_BLOCKED,
}


def _failure_fields(category, detail: str = "", *, fallback: str = "") -> dict:
    """The safe, renderable explanation of one failure. Never payload-bearing."""
    name = str(category or fallback or "")
    if not name:
        return {"error_category": "", "error_detail": "", "error_summary": "",
                "required_action": "", "error_retryable": False}
    if name in _LOCAL_GUIDANCE:
        summary, action = _LOCAL_GUIDANCE[name]
        retryable = False
    else:
        summary, action = explain(name)
        try:
            retryable = ErrorCategory(name) in RETRYABLE
        except ValueError:
            retryable = False
    return {"error_category": name, "error_detail": str(detail or ""),
            "error_summary": summary, "required_action": action,
            "error_retryable": retryable}


def failure_for_decision(decision: str) -> dict:
    """Explain a governor refusal in the same shape as a provider failure."""
    return _failure_fields(_DECISION_CATEGORIES.get(decision, ""))


def _is_exhausted(outcome: LiveCallOutcome) -> bool:
    """True when a refusal means no further field can succeed either."""
    return outcome.decision.value in {
        "BLOCKED_SESSION_BUDGET", "BLOCKED_DOCUMENT_BUDGET",
        "BLOCKED_DOCUMENT_CALL_LIMIT", "BLOCKED_BATCH_CALL_LIMIT",
    }


def _blocked_receipt(request: MultimodalRequest | None, governor: LiveCallGovernor,
                     reason: str, outcome: LiveCallOutcome | None = None,
                     *, error_category: str = "", error_detail: str = "") -> dict:
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
        # A refusal is a category too. Budget and duplicate blocks in
        # particular are routinely mistaken for provider failures, and they are
        # the two where nothing was billed and nothing is wrong.
        **_failure_fields(
            error_category
            or _DECISION_CATEGORIES.get(
                outcome.decision.value if outcome else "", ""),
            error_detail),
    }
