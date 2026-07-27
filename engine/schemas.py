"""Shared field schema — the single source of truth for every pipeline stage.

Architecture v1.2 state model:
    ACCEPT, ACCEPT_WITH_FLAG, RETRY, ESCALATE, HUMAN_REVIEW, ACCEPT_WITH_OVERRIDE

ACCEPT_WITH_OVERRIDE is unreachable from automated paths: it can only be produced
via FieldResult.human_override(), which requires reviewer identity and a reason,
and is audit-logged by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class FieldState(str, Enum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_FLAG = "ACCEPT_WITH_FLAG"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ACCEPT_WITH_OVERRIDE = "ACCEPT_WITH_OVERRIDE"  # human-only; see human_override()


# States a governor / automated path may legally emit.
AUTOMATED_STATES = frozenset(
    {FieldState.ACCEPT, FieldState.ACCEPT_WITH_FLAG, FieldState.RETRY,
     FieldState.ESCALATE, FieldState.HUMAN_REVIEW}
)

TERMINAL_STATES = frozenset(
    {FieldState.ACCEPT, FieldState.ACCEPT_WITH_FLAG, FieldState.ACCEPT_WITH_OVERRIDE}
)


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INAPPLICABLE = "INAPPLICABLE"


@dataclass
class ValidationStamp:
    """Outcome of one validator run against one candidate value."""
    validator: str
    verdict: Verdict
    detail: str = ""


@dataclass
class Attempt:
    """One entry in a field's attempt history (governor input #4)."""
    rung: str                  # primary_ocr | retry_ocr | multimodal | human
    engine: str                # e.g. paddleocr, tesseract, gpt-5-nano, reviewer:<id>
    value: Optional[str]
    confidence: float          # fused confidence for this candidate, 0..1
    cost_usd: float = 0.0
    latency_ms: float = 0.0


@dataclass
class FieldResult:
    """The unit every stage produces and consumes. One per (page, field)."""
    doc_id: str
    page_id: str
    field_name: str
    value: Optional[str] = None
    state: FieldState = FieldState.RETRY          # not-yet-resolved default
    confidence: float = 0.0
    bbox: Optional[tuple] = None                  # (x0, y0, x1, y1) in page-image coords
    stamps: list = field(default_factory=list)    # list[ValidationStamp]
    attempts: list = field(default_factory=list)  # list[Attempt]
    override: Optional[dict] = None               # populated only by human_override()

    def set_state(self, state: FieldState) -> None:
        """Automated transition — refuses the human-only state."""
        if state == FieldState.ACCEPT_WITH_OVERRIDE:
            raise PermissionError(
                "ACCEPT_WITH_OVERRIDE cannot be set by automated paths; "
                "use FieldResult.human_override()."
            )
        self.state = state

    def human_override(self, *, corrected_value: str, failing_validator: str,
                       reviewer_id: str, reason: str) -> dict:
        """Terminal, human-only. Returns the audit record; caller must persist it."""
        if not reviewer_id or not reason:
            raise ValueError("Override requires reviewer identity and a reason.")
        self.value = corrected_value
        self.state = FieldState.ACCEPT_WITH_OVERRIDE
        self.override = {
            "corrected_value": corrected_value,
            "failing_validator": failing_validator,
            "reviewer_id": reviewer_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        return self.override

    @property
    def resolved(self) -> bool:
        return self.state in TERMINAL_STATES

    def attempts_used(self, rung: str) -> int:
        return sum(1 for a in self.attempts if a.rung == rung)


@dataclass
class PageResult:
    doc_id: str
    page_id: str
    doc_type: str                       # cms1500 | ub04 | unstructured | unknown
    quality_score: float = 0.0
    fields: dict = field(default_factory=dict)   # field_name -> FieldResult

    def to_json_dict(self) -> dict:
        """Final structured output: value + validation stamp + provenance + cost."""
        out = {}
        for name, fr in self.fields.items():
            out[name] = {
                "value": fr.value,
                "state": fr.state.value,
                "confidence": round(fr.confidence, 4),
                "stamps": [{"validator": s.validator, "verdict": s.verdict.value}
                           for s in fr.stamps],
                "provenance": [{"rung": a.rung, "engine": a.engine} for a in fr.attempts],
                "cost_usd": round(sum(a.cost_usd for a in fr.attempts), 6),
            }
            if fr.override:
                out[name]["override"] = fr.override
        return out
