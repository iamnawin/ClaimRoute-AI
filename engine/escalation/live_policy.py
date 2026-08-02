"""Spending guardrails for the real, paid provider path.

The adapter in client.py answers "is this response usable?". This module answers
the question that comes BEFORE it and costs money to get wrong: "may we call a
paid provider at all, right now, for this crop?"

DEFAULT BEHAVIOUR PERMITS ZERO SPENDING. Every gate is closed until explicitly
opened, and they are ANDed — there is no path where one permissive setting
unlocks a call on its own. A paid call requires all nine of:

    1. live_provider.enabled                     (tracked config)
    2. CLAIMROUTE_MULTIMODAL_ENABLED             (environment)
    3. CLAIMROUTE_LIVE_PROVIDER_TEST             (environment)
    4. the provider's API key present            (environment)
    5. the request marked synthetic
    6. the image PROVEN to be a field crop, not a page
    7. the model on the allowlist AND declaring vision support
    8. session and document budgets both still positive
    9. the request not a duplicate

Design decisions that are load-bearing:

- EVERY refusal is a typed outcome, never an exception and never a bare False.
  An operator needs to know whether a field went unanswered because the money
  ran out or because the model was wrong, and those demand different fixes.

- A refusal ROUTES THE FIELD TO HUMAN REVIEW. Silently dropping a field would
  make a budget cap look like an accuracy result.

- Budgets are checked against MONEY ACTUALLY BILLED (CostBreakdown.billed_usd),
  never against the text-only estimate. That estimate excludes image tokens and
  is an explicit lower bound; spending a session against lower bounds would
  overrun the cap by construction.

- A call whose cost is UNKNOWN is charged to the budget as the full remaining
  document allowance. Treating unknown as zero is how an unmetered path drains
  an account, so the pessimistic reading is the safe one.

- Nothing here logs crop bytes, extracted values, prompts, or response bodies.
  Requests are identified by a fingerprint over hashes and names only.
"""
from __future__ import annotations

import copy
import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from engine.escalation.contract import MultimodalRequest
from engine.escalation.providers.base import PROMPT_VERSION, SCHEMA_VERSION
from engine.grounding import _type_key

MULTIMODAL_ENABLED_ENV = "CLAIMROUTE_MULTIMODAL_ENABLED"
LIVE_TEST_ENV = "CLAIMROUTE_LIVE_PROVIDER_TEST"
DEFAULT_KEY_ENV = "OPENROUTER_API_KEY"

_TRUE = {"1", "true", "yes", "on"}


class ModeError(TypeError):
    """The caller passed something that is not an operating mode.

    A TypeError subclass on purpose: passing a non-mode is a programmer defect,
    not a runtime policy state, and it must keep failing loudly for callers that
    already catch TypeError. It carries a readable message so the UI's
    containment boundary can name the problem instead of rendering a redacted
    "TypeError" with no detail, which is exactly how this class came to exist.
    """


class LiveDecision(str, Enum):
    """Every way a live-call authorisation can end. Exhaustive on purpose."""

    ALLOW = "ALLOW"
    REUSED_CACHED_RESULT = "REUSED_CACHED_RESULT"

    # --- not switched on -----------------------------------------------
    BLOCKED_LIVE_PATH_DISABLED = "BLOCKED_LIVE_PATH_DISABLED"
    BLOCKED_ADAPTER_DISABLED = "BLOCKED_ADAPTER_DISABLED"
    BLOCKED_LIVE_TEST_FLAG_UNSET = "BLOCKED_LIVE_TEST_FLAG_UNSET"
    BLOCKED_NO_API_KEY = "BLOCKED_NO_API_KEY"

    # --- wrong input ----------------------------------------------------
    BLOCKED_NOT_SYNTHETIC = "BLOCKED_NOT_SYNTHETIC"
    BLOCKED_NOT_A_CROP = "BLOCKED_NOT_A_CROP"

    # --- wrong model ----------------------------------------------------
    BLOCKED_MODEL_NOT_ALLOWLISTED = "BLOCKED_MODEL_NOT_ALLOWLISTED"
    BLOCKED_MODEL_NOT_VISION = "BLOCKED_MODEL_NOT_VISION"
    BLOCKED_MODEL_REFUSED = "BLOCKED_MODEL_REFUSED"

    # --- out of allowance -----------------------------------------------
    BLOCKED_FIELD_CALL_LIMIT = "BLOCKED_FIELD_CALL_LIMIT"
    BLOCKED_PAGE_CALL_LIMIT = "BLOCKED_PAGE_CALL_LIMIT"
    BLOCKED_DOCUMENT_CALL_LIMIT = "BLOCKED_DOCUMENT_CALL_LIMIT"
    BLOCKED_BATCH_CALL_LIMIT = "BLOCKED_BATCH_CALL_LIMIT"
    BLOCKED_FIELD_PAID_ATTEMPTS = "BLOCKED_FIELD_PAID_ATTEMPTS"
    BLOCKED_SESSION_BUDGET = "BLOCKED_SESSION_BUDGET"
    BLOCKED_DOCUMENT_BUDGET = "BLOCKED_DOCUMENT_BUDGET"

    # --- repetition ------------------------------------------------------
    BLOCKED_DUPLICATE_REQUEST = "BLOCKED_DUPLICATE_REQUEST"
    BLOCKED_PARALLEL_CALL = "BLOCKED_PARALLEL_CALL"

    @property
    def allows_call(self) -> bool:
        return self is LiveDecision.ALLOW


@dataclass(frozen=True)
class SpendLimits:
    """Initial smoke-test limits. NOT production calibration."""

    max_calls_per_field: int = 1
    max_calls_per_page: int = 2
    max_calls_per_document: int = 3
    max_calls_per_batch: int = 5
    max_paid_attempts_per_field: int = 1
    max_session_spend_usd: float = 0.02
    max_document_spend_usd: float = 0.005
    allow_fallback_models: bool = False
    allow_parallel_paid_calls: bool = False
    allow_automatic_reruns: bool = False

    @classmethod
    def from_config(cls, cfg: Optional[dict]) -> "SpendLimits":
        """Build from the `limits` block, ignoring unknown keys.

        Defaults are the safe values above, so a truncated or partly-written
        config yields the tight limits rather than an absent one.
        """
        cfg = cfg or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in cfg.items() if k in known})

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class LiveCallOutcome:
    """The typed result of one authorisation. Never an exception, never a bool."""

    decision: LiveDecision
    reason: str = ""
    fingerprint: str = ""
    field_name: str = ""
    model: str = ""
    doc_id: str = ""
    page_id: str = ""
    # Set when a duplicate was served from the session cache instead of paid for.
    reused_from: str = ""
    avoided_cost_usd: Optional[float] = None

    @property
    def field_key(self) -> tuple:
        """Identity of the FIELD, independent of which crop was sent for it."""
        return (self.doc_id, self.page_id, self.field_name)

    @property
    def allowed(self) -> bool:
        return self.decision.allows_call

    @property
    def route_to_human_review(self) -> bool:
        """Anything that is neither a call nor a reused answer leaves the field
        unanswered, and an unanswered field is a human's problem, not a silent
        gap in the output."""
        return self.decision not in (LiveDecision.ALLOW,
                                     LiveDecision.REUSED_CACHED_RESULT)

    def to_dict(self) -> dict:
        return {"decision": self.decision.value, "reason": self.reason,
                "fingerprint": self.fingerprint, "field_name": self.field_name,
                "model": self.model, "doc_id": self.doc_id, "page_id": self.page_id,
                "allowed": self.allowed,
                "route_to_human_review": self.route_to_human_review,
                "reused_from": self.reused_from,
                "avoided_cost_usd": self.avoided_cost_usd}


@dataclass
class _Counters:
    per_field: dict = field(default_factory=dict)
    per_page: dict = field(default_factory=dict)
    per_document: dict = field(default_factory=dict)
    batch_calls: int = 0
    paid_attempts_per_field: dict = field(default_factory=dict)
    spend_per_document: dict = field(default_factory=dict)
    session_spend: float = 0.0


def fingerprint(request: MultimodalRequest, model: str) -> str:
    """Deterministic identity for one paid request.

    Built from SAFE METADATA ONLY — a crop hash, names, and version digests. Raw
    crop bytes and extracted values are deliberately absent: this string ends up
    in audit records and logs, and neither belongs there.

    Prompt and schema versions are included because the same crop asked a
    different question is a different request; without them a cached answer
    would survive a contract change it never actually satisfied.
    """
    parts = [request.crop.sha256, request.field_name,
             _type_key(request.field_name) or "untyped",
             model, PROMPT_VERSION, SCHEMA_VERSION]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class LiveCallGovernor:
    """Session-scoped authority over paid provider calls.

    One instance per process run. It holds the counters and the duplicate cache,
    so "session budget" means the life of this object rather than something
    ambient that a second import could reset.
    """

    def __init__(self, config: Optional[dict] = None, *,
                 env: Optional[dict] = None,
                 adapter_enabled: Optional[bool] = None,
                 mode: Optional[str] = None,
                 router: Optional["ModelRouter"] = None):
        cfg = config or {}
        self._live = cfg.get("live_provider") or {}
        self._request_policy = cfg.get("request_policy") or {}
        self._providers = cfg.get("providers") or {}
        self._env = env
        self._adapter_enabled_override = adapter_enabled

        # Model selection belongs to the router, not to the provider entry. The
        # governor still re-checks the allowlist itself in _check_model: a
        # resolved model is a proposal, and this class does not trust it.
        from engine.escalation.model_router import DEFAULT_MODE, ModelRouter
        # `mode` is normalised rather than trusted. Callers hand this straight
        # through from UI state, and the receipt shape for an operating mode is
        # a dict ({"key": ..., "label": ...}) while the batch shape is a bare
        # string. Accepting both here keeps one supported contract at the call
        # site instead of making every caller remember which shape it holds.
        if isinstance(mode, dict):
            mode = mode.get("key")
        if mode is not None and not isinstance(mode, str):
            raise ModeError(
                f"operating mode must be a string or a receipt dict with a "
                f"'key', got {type(mode).__name__}")
        # Strip BEFORE the default, not after: "   " is truthy, so the reverse
        # order kept it and left self.mode == "", which resolved to the
        # provider's static model instead of the default mode.
        self.mode = (mode or "").strip().lower() or DEFAULT_MODE
        self._router = router if router is not None else ModelRouter(
            provider_config=cfg)

        self.limits = SpendLimits.from_config(self._live.get("limits"))
        self._counters = _Counters()
        self._results: dict = {}          # fingerprint -> (billed_usd, request_id)
        self._in_flight: Optional[str] = None
        self.calls_made = 0
        self.paid_calls_avoided = 0
        self._projected_uncached = 0.0

    # ------------------------------------------------------------ environment

    def _getenv(self, name: str) -> Optional[str]:
        if self._env is not None:
            return self._env.get(name)
        return os.environ.get(name)

    def _flag(self, name: str) -> bool:
        raw = self._getenv(name)
        return bool(raw) and str(raw).strip().lower() in _TRUE

    @property
    def provider_name(self) -> str:
        return self._live.get("provider", "openrouter")

    @property
    def key_env(self) -> str:
        spec = self._providers.get(self.provider_name) or {}
        return spec.get("api_key_env") or DEFAULT_KEY_ENV

    @property
    def resolved(self):
        """The full model selection for this session's operating mode.

        Recomputed rather than cached so a mode change between renders cannot
        leave a stale model id authorising a call for the wrong mode.
        """
        return self._router.resolve(self.mode)

    @property
    def model(self) -> str:
        """The exact model id this session will send.

        Resolved from the operating mode. Falls back to the provider entry's
        static `model:` only when the mode has no configured alias — the router
        owns that decision, so this property has one source, not two.
        """
        return self.resolved.model_id

    # ---------------------------------------------------------------- model

    def allowlist_entry(self, model: str) -> Optional[dict]:
        for entry in self._live.get("model_allowlist") or []:
            if isinstance(entry, dict) and entry.get("id") == model:
                return entry
        return None

    def _check_model(self, model: str) -> Optional[LiveCallOutcome]:
        # Refused classes first: Auto Router and free variants are rejected by
        # identity, before an allowlist can be mis-edited to include one.
        from engine.escalation.providers.openrouter_provider import OpenRouterProvider
        refusal = OpenRouterProvider.model_rejection(model)
        if refusal:
            return LiveCallOutcome(LiveDecision.BLOCKED_MODEL_REFUSED, refusal,
                                   model=model)

        entry = self.allowlist_entry(model)
        if entry is None:
            allowed = [e.get("id") for e in self._live.get("model_allowlist") or []
                       if isinstance(e, dict)]
            return LiveCallOutcome(
                LiveDecision.BLOCKED_MODEL_NOT_ALLOWLISTED,
                f"{model!r} is not on the allowlist {allowed}", model=model)

        # Vision support is a CHECKED declaration, not decoration. A text-only
        # model handed an image burns a call to return nothing useful.
        if entry.get("vision") is not True:
            return LiveCallOutcome(
                LiveDecision.BLOCKED_MODEL_NOT_VISION,
                f"{model!r} does not declare vision: true in its allowlist entry",
                model=model)
        return None

    # -------------------------------------------------------------- authorise

    def authorize(self, request: MultimodalRequest, *, model: Optional[str] = None,
                  page_id: str = "", doc_id: str = "") -> LiveCallOutcome:
        """Decide whether ONE paid call may be made. Never performs the call.

        Order matters: the cheapest and most categorical refusals run first, so a
        misconfigured run fails on "the path is off" rather than on a budget
        number that was never the real problem.
        """
        model = model or self.model
        fp = fingerprint(request, model)
        page = page_id or request.page_id
        doc = doc_id or request.doc_id
        base = {"fingerprint": fp, "field_name": request.field_name, "model": model,
                "doc_id": doc, "page_id": page}

        def no(decision: LiveDecision, reason: str) -> LiveCallOutcome:
            return LiveCallOutcome(decision, reason, **base)

        # 1-4. Switched on, and credentialed.
        if not bool(self._live.get("enabled", False)):
            return no(LiveDecision.BLOCKED_LIVE_PATH_DISABLED,
                      "live_provider.enabled is false in configs/multimodal_providers.yaml")

        adapter_on = (self._adapter_enabled_override
                      if self._adapter_enabled_override is not None
                      else self._flag(MULTIMODAL_ENABLED_ENV))
        if not adapter_on:
            return no(LiveDecision.BLOCKED_ADAPTER_DISABLED,
                      f"{MULTIMODAL_ENABLED_ENV} is not true")

        live_env = self._live.get("live_test_env", LIVE_TEST_ENV)
        if not self._flag(live_env):
            return no(LiveDecision.BLOCKED_LIVE_TEST_FLAG_UNSET,
                      f"{live_env} is not true")

        if not (self._getenv(self.key_env) or "").strip():
            return no(LiveDecision.BLOCKED_NO_API_KEY,
                      f"{self.key_env} is not set")

        # 5. Synthetic only.
        if not request.synthetic:
            return no(LiveDecision.BLOCKED_NOT_SYNTHETIC,
                      "request is not marked synthetic; the live path is "
                      "synthetic-data-only")

        # 6. A crop, provably. Same numbers the adapter's own gate uses, applied
        #    earlier so an unprovable image never reaches provider construction.
        crop_reject = self._check_crop(request)
        if crop_reject:
            return no(LiveDecision.BLOCKED_NOT_A_CROP, crop_reject)

        # 7. Model.
        model_reject = self._check_model(model)
        if model_reject is not None:
            model_reject.fingerprint = fp
            model_reject.field_name = request.field_name
            return model_reject

        # 8. Duplicates, before budgets: a repeat should be reported as reuse,
        #    not as a budget failure it never actually reached.
        if fp in self._results:
            billed, prior_id = self._results[fp]
            if self._live.get("duplicate_policy", {}).get("reuse_previous_result", True):
                self.paid_calls_avoided += 1
                self._projected_uncached += billed or 0.0
                return LiveCallOutcome(
                    LiveDecision.REUSED_CACHED_RESULT,
                    "identical request already answered this session; "
                    "reusing it instead of paying twice",
                    reused_from=prior_id, avoided_cost_usd=billed, **base)
            self.paid_calls_avoided += 1
            self._projected_uncached += billed or 0.0
            return LiveCallOutcome(
                LiveDecision.BLOCKED_DUPLICATE_REQUEST,
                "identical request already made this session and reuse is off",
                reused_from=prior_id, avoided_cost_usd=billed, **base)

        if not self.limits.allow_parallel_paid_calls and self._in_flight is not None:
            return no(LiveDecision.BLOCKED_PARALLEL_CALL,
                      "another paid call is already in flight and parallel paid "
                      "calls are disabled")

        # 9. Allowances. Counts first — they are exact — then money.
        #
        # Paid attempts are keyed by FIELD, not by fingerprint. A re-crop of the
        # same field is a new fingerprint and so escapes duplicate protection;
        # without a field-level cap it could be paid for repeatedly.
        c = self._counters
        field_key = (doc, page, request.field_name)
        if c.paid_attempts_per_field.get(field_key, 0) >= self.limits.max_paid_attempts_per_field:
            return no(LiveDecision.BLOCKED_FIELD_PAID_ATTEMPTS,
                      f"field already had {self.limits.max_paid_attempts_per_field} "
                      "billed attempt(s)")
        if c.per_field.get(field_key, 0) >= self.limits.max_calls_per_field:
            return no(LiveDecision.BLOCKED_FIELD_CALL_LIMIT,
                      f"max_calls_per_field={self.limits.max_calls_per_field} reached")
        if c.per_page.get((doc, page), 0) >= self.limits.max_calls_per_page:
            return no(LiveDecision.BLOCKED_PAGE_CALL_LIMIT,
                      f"max_calls_per_page={self.limits.max_calls_per_page} reached")
        if c.per_document.get(doc, 0) >= self.limits.max_calls_per_document:
            return no(LiveDecision.BLOCKED_DOCUMENT_CALL_LIMIT,
                      f"max_calls_per_document={self.limits.max_calls_per_document} reached")
        if c.batch_calls >= self.limits.max_calls_per_batch:
            return no(LiveDecision.BLOCKED_BATCH_CALL_LIMIT,
                      f"max_calls_per_batch={self.limits.max_calls_per_batch} reached")

        # "Remaining budget is positive" — checked before the call, because the
        # exact cost is not knowable until after it.
        if self.session_remaining_usd <= 0:
            return no(LiveDecision.BLOCKED_SESSION_BUDGET,
                      f"session spend ${c.session_spend:.6f} has reached the "
                      f"${self.limits.max_session_spend_usd:.4f} cap")
        if self.document_remaining_usd(doc) <= 0:
            return no(LiveDecision.BLOCKED_DOCUMENT_BUDGET,
                      f"document spend ${c.spend_per_document.get(doc, 0.0):.6f} has "
                      f"reached the ${self.limits.max_document_spend_usd:.4f} cap")

        self._in_flight = fp
        return LiveCallOutcome(LiveDecision.ALLOW, "all guardrails satisfied", **base)

    def preview_authorization(
            self, request: MultimodalRequest, *, model: Optional[str] = None,
            page_id: str = "", doc_id: str = "") -> LiveCallOutcome:
        """Run every live-policy check without reserving or charging a call.

        The UI uses this only to explain whether its action can be enabled. The
        real execution path must call :meth:`authorize` again immediately before
        transport. A deep copy prevents duplicate counters, cached-result
        accounting, and the in-flight marker from being changed by rendering.
        """
        probe = copy.deepcopy(self)
        return probe.authorize(
            request, model=model, page_id=page_id, doc_id=doc_id)

    def _check_crop(self, request: MultimodalRequest) -> str:
        """-> refusal reason, or "" when the image is a proven field crop."""
        policy = self._request_policy
        if not policy.get("crop_only", True):
            return ""
        fraction = request.crop.page_fraction
        if fraction is None:
            if policy.get("require_page_provenance", True):
                return ("no source page size recorded; the image cannot be "
                        "proven to be a field crop")
            return ""
        limit = float(policy.get("max_page_fraction", 0.25))
        if fraction > limit:
            return (f"image covers {fraction:.1%} of the page (limit {limit:.0%}); "
                    "full pages are never sent")
        return ""

    # ----------------------------------------------------------- accounting

    def record_call(self, outcome: LiveCallOutcome, result) -> None:
        """Book one completed paid call against every counter and budget.

        Called after the provider returns, whatever the outcome — a failed call
        still consumed an attempt and may still have been billed. The document
        and page it counts against come from the OUTCOME, so the authorisation
        and the accounting cannot disagree about which document was charged.
        """
        self._in_flight = None
        if not outcome.allowed:
            return

        fp = outcome.fingerprint
        billed = self._billed(result)
        doc, page = outcome.doc_id, outcome.page_id
        fkey = outcome.field_key

        c = self._counters
        c.per_field[fkey] = c.per_field.get(fkey, 0) + 1
        c.per_page[(doc, page)] = c.per_page.get((doc, page), 0) + 1
        c.per_document[doc] = c.per_document.get(doc, 0) + 1
        c.batch_calls += 1
        # A "paid attempt" is one that actually cost money. A call the provider
        # refused before billing consumes a call slot but not a paid attempt.
        if billed > 0:
            c.paid_attempts_per_field[fkey] = c.paid_attempts_per_field.get(fkey, 0) + 1
        c.spend_per_document[doc] = c.spend_per_document.get(doc, 0.0) + billed
        c.session_spend += billed

        self.calls_made += 1
        self._projected_uncached += billed
        self._results[fp] = (billed, getattr(result, "request_id", ""))

    def _billed(self, result) -> float:
        """Money to charge against the budget for one call.

        An UNKNOWN cost is charged as the entire remaining document allowance,
        not as zero. A provider that reports nothing must not be able to make
        unlimited calls simply because none of them appeared to cost anything.
        """
        cost = getattr(result, "cost", None)
        billed = getattr(cost, "billed_usd", None) if cost is not None else None
        if billed is not None:
            return float(billed)
        if not getattr(result, "called_provider", False):
            return 0.0                      # blocked before transport: no charge
        return max(0.0, self.limits.max_document_spend_usd)

    def release(self) -> None:
        """Clear the in-flight marker for a call that never happened."""
        self._in_flight = None

    # -------------------------------------------------------------- reporting

    @property
    def session_spend_usd(self) -> float:
        return self._counters.session_spend

    @property
    def session_remaining_usd(self) -> float:
        return self.limits.max_session_spend_usd - self._counters.session_spend

    def document_remaining_usd(self, doc_id: str) -> float:
        spent = self._counters.spend_per_document.get(doc_id, 0.0)
        return self.limits.max_document_spend_usd - spent

    def session_report(self) -> dict:
        """Spend, kept in three separate columns.

        `measured_incremental_usd` is what this run actually added. It is NOT
        reduced by cache hits, and `projected_uncached_usd` is NOT reported as
        zero because a hit occurred — the saving is stated as a saving, so the
        real cost of the work stays visible.
        """
        measured = round(self._counters.session_spend, 8)
        projected = round(self._projected_uncached, 8)
        return {
            "provider": self.provider_name,
            "model": self.model,
            "calls_made": self.calls_made,
            "paid_calls_avoided": self.paid_calls_avoided,
            "measured_incremental_usd": measured,
            "projected_uncached_usd": projected,
            "cache_savings_usd": round(projected - measured, 8),
            "session_spend_usd": measured,
            "session_remaining_usd": round(self.session_remaining_usd, 8),
            "limits": self.limits.to_dict(),
        }
