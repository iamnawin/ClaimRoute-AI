"""Cost Governor — Architecture v1.2.

Decision inputs (all four, explicitly):
    fused confidence + validator verdicts + field policy + attempt history

Emits only AUTOMATED_STATES. ACCEPT_WITH_OVERRIDE is unreachable here by
construction (see engine/schemas.py). Attempt budgets come from
configs/pipeline.yaml; an exhausted budget routes to HUMAN_REVIEW, so no field
can loop indefinitely — bounded spend is a property of the design, not a hope.
"""
from __future__ import annotations

import re

import yaml

from engine.schemas import FieldResult, FieldState, Verdict

_PIPE = yaml.safe_load(open("configs/pipeline.yaml"))
_POLICY = yaml.safe_load(open("configs/field_policy.yaml"))
_FIELDS = {**_POLICY["fields"], **_POLICY.get("ub04_fields", {})}
_DEFAULTS = _POLICY["defaults"]
BUDGET = _PIPE["attempt_budget"]


def field_policy(field_name: str) -> dict:
    m = re.fullmatch(r"line\d+_(\w+)", field_name)
    p = (_POLICY["service_line_template"].get(m.group(1), {}) if m
         else _FIELDS.get(field_name, {}))
    return {**_DEFAULTS, **p}


def preset(name: str | None = None) -> dict:
    return _PIPE["presets"][name or _PIPE["active_preset"]]


def _validators_failed(fr: FieldResult) -> list[str]:
    return [s.validator for s in fr.stamps if s.verdict == Verdict.FAIL]


def decide(fr: FieldResult, preset_name: str | None = None) -> tuple[FieldState, str]:
    """-> (state, human-readable reason). Pure function of the four inputs."""
    p = field_policy(fr.field_name)
    ps = preset(preset_name)
    failed = _validators_failed(fr)
    conf = fr.confidence
    retries_left = fr.attempts_used("retry_ocr") < BUDGET["retry_ocr"]
    escalations_left = fr.attempts_used("multimodal") < BUDGET["multimodal"]
    may_escalate = p.get("external_model_allowed", True) and escalations_left

    def next_rung(reason: str) -> tuple[FieldState, str]:
        """Cheapest remaining rung, in ladder order."""
        if retries_left:
            return FieldState.RETRY, f"{reason}; retry budget available"
        if may_escalate:
            return FieldState.ESCALATE, f"{reason}; retry exhausted"
        return FieldState.HUMAN_REVIEW, f"{reason}; attempt budget exhausted"

    # 0. Legitimately-blank optional box: accept as empty, spend nothing.
    #    (Paying a model to inspect a box the form permits to be blank is pure
    #    waste; hallucinating a value into it is penalised by the metric.)
    if not fr.value and p.get("optional"):
        return FieldState.ACCEPT, "optional field legitimately empty"

    # 1. Hard validator failure — never acceptable, regardless of confidence.
    if failed:
        return next_rung(f"validator FAIL: {','.join(failed)}")

    # 2. Missing value on a required field.
    if not fr.value and p.get("required_validators"):
        return next_rung("empty value on required field")

    # 3. Clean validators + high confidence -> accept.
    if conf >= ps["accept_threshold"]:
        return FieldState.ACCEPT, f"validators clean, conf {conf:.2f} >= accept"

    # 4. Middle band: non-critical fields may be accepted with a flag rather
    #    than spending on them (the cheapest legitimate resolution).
    if (conf >= ps["escalate_threshold"] and ps["allow_accept_with_flag"]
            and p.get("allow_accept_with_flag") and p.get("criticality") == "low"):
        return (FieldState.ACCEPT_WITH_FLAG,
                f"low criticality, validators clean, conf {conf:.2f} tolerable")

    # 5. Otherwise buy more evidence, cheapest rung first.
    return next_rung(f"conf {conf:.2f} below accept threshold")


def apply(fr: FieldResult, preset_name: str | None = None) -> tuple[FieldState, str]:
    """decide() + record the state on the field (automated states only)."""
    state, reason = decide(fr, preset_name)
    fr.set_state(state)
    return state, reason
