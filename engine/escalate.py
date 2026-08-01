"""Tier-2 escalation rung — the controlled boundary where money is spent.

This is not an agent framework. It is one bounded transaction, gated by policy,
whose output must earn its place against the OCR candidates:

    policy gate -> crop (bounded) -> cache -> model call -> grounding
                -> revalidation -> explainable selection -> governor re-entry

Every precondition is checked BEFORE the request, in this order, and the order
is load-bearing: policy dominates the cache, because a cached answer for a field
that policy forbids must never be served.

    1. field allows external processing        (configs/field_policy.yaml)
    2. provider is approved                    (configs/pipeline.yaml)
    3. attempt budget remains                  (attempt history on the field)
    4. crops only, never full pages            (engine/cropper.py, structural)
    5. cache hit?                              (no call, no spend, still logged)
    6. estimated cost logged BEFORE execution  (so a crash still leaves a trace)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from engine.cropper import CropPolicyError, crop_field, crop_hash
from engine.fusion import fuse
from engine.governor import BUDGET, field_policy
from engine.grounding import check as ground_check
from engine.layout.mapper import template_region
from engine.schemas import Attempt, FieldResult, Verdict
from engine.validators import validate_field
from engine.vision.base import get_vision_engine

_PIPE = yaml.safe_load(open("configs/pipeline.yaml"))
_MP = _PIPE["model_policy"]

CACHE_PATH = Path(_MP.get("cache_path", "eval/results/vision_cache.jsonl"))
_CACHE: dict | None = None


class PolicyViolation(RuntimeError):
    """A precondition failed. The call is NOT made."""


# ---------------------------------------------------------------- cache

def _load_cache() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        if CACHE_PATH.exists():
            for line in CACHE_PATH.open(encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    _CACHE[r["key"]] = r["response"]
    return _CACHE


def cache_key(model: str, field_name: str, chash: str) -> str:
    """Identical pixels + identical field + identical model = identical answer.
    Re-running an eval must not re-bill; that is a real operational saving, and
    it is reported separately so it never inflates the per-page cost claim."""
    return f"{model}|{field_name}|{chash}"


def _cache_put(key: str, resp) -> None:
    _load_cache()[key] = {
        "value": resp.value, "visible_text": resp.visible_text,
        "confidence": resp.confidence, "reason": resp.reason,
        "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
        "cost_usd": resp.cost_usd, "parse_error": resp.parse_error,
        "raw_sha256": resp.raw_sha256, "error_type": resp.error_type,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "response": _CACHE[key]}) + "\n")


def _cache_get(key: str):
    d = _load_cache().get(key)
    if d is None:
        return None
    from engine.vision.base import VisionErrorType, VisionResponse
    r = VisionResponse(d["value"], d["visible_text"], d["confidence"],
                       reason=d.get("reason", ""))
    r.input_tokens, r.output_tokens = d["input_tokens"], d["output_tokens"]
    r.parse_error = d.get("parse_error", "")
    r.raw_sha256 = d.get("raw_sha256", "")
    r.error_type = VisionErrorType(d["error_type"]) if d.get("error_type") else None
    r.cost_usd = 0.0          # a cache hit costs nothing to serve
    r.cached = True
    return r


# ---------------------------------------------------------------- policy

def check_policy(fr: FieldResult, model: str) -> None:
    """Raises PolicyViolation if this call must not happen. No side effects."""
    p = field_policy(fr.field_name)
    if not p.get("external_model_allowed", True):
        raise PolicyViolation(
            f"field {fr.field_name!r} is not permitted to leave the trust boundary")

    approved = _MP.get("approved_providers") or []
    if model not in approved:
        raise PolicyViolation(
            f"model {model!r} is not in model_policy.approved_providers {approved}")

    if fr.attempts_used("multimodal") >= BUDGET["multimodal"]:
        raise PolicyViolation(
            f"multimodal attempt budget exhausted for {fr.field_name!r}")

    if _MP.get("send_full_pages_externally", False):
        raise PolicyViolation("send_full_pages_externally must be false")


# ---------------------------------------------------------------- rung

def escalate_field(fr: FieldResult, img, form: str, variant: int,
                   page_values: dict, quality: float, ledger,
                   model: str, *, tier: str = "clean",
                   synthetic: bool = True) -> dict:
    """One governed escalation. Mutates fr. Returns a record for the funnel."""
    rec = {"field": fr.field_name, "model": model, "escalated": False,
           "cost_usd": 0.0, "cached": False, "rejects": [], "decision": ""}

    try:
        check_policy(fr, model)
    except PolicyViolation as e:
        rec["decision"] = f"blocked: {e}"
        ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
                   operation="escalate_blocked", cost_usd=0.0, latency_ms=0.0,
                   meta={"rung": "multimodal", "reason": str(e), "model": model})
        return rec

    bbox = list(fr.bbox) if fr.bbox else template_region(img, form, variant,
                                                         fr.field_name)
    try:
        crop = crop_field(img, bbox)
    except CropPolicyError as e:
        rec["decision"] = f"blocked: {e}"
        ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
                   operation="escalate_blocked", cost_usd=0.0, latency_ms=0.0,
                   meta={"rung": "multimodal", "reason": str(e), "model": model})
        return rec

    chash = crop_hash(crop)
    key = cache_key(model, fr.field_name, chash)
    resp = _cache_get(key)

    if resp is None:
        # Estimated cost is logged BEFORE the call: if the process dies mid-flight
        # the ledger still shows that money was committed. Under-reporting spend
        # because of a crash would be the wrong kind of optimism.
        ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
                   operation="escalate_intent", cost_usd=0.0, latency_ms=0.0,
                   meta={"rung": "multimodal", "model": model, "crop_sha": chash,
                         "crop_px": [crop.width, crop.height],
                         "zero_retention_required": _MP.get("require_zero_retention"),
                         "synthetic_data": synthetic})
        eng = get_vision_engine(model)
        t0 = time.perf_counter()
        resp = eng.read_field(crop, fr.field_name, doc_id=fr.doc_id, tier=tier,
                              crop_hash=chash)
        resp.latency_ms = resp.latency_ms or (time.perf_counter() - t0) * 1000
        _cache_put(key, resp)
    rec["cached"] = resp.cached

    ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
               operation=f"escalate_{model}", cost_usd=resp.cost_usd,
               latency_ms=resp.latency_ms,
               meta={"rung": "multimodal", "model": model, "crop_sha": chash,
                     "input_tokens": resp.input_tokens,
                     "output_tokens": resp.output_tokens,
                     "response_sha256": resp.raw_sha256,
                     "error_type": resp.error_type,
                     "cached": resp.cached, "synthetic_data": synthetic,
                     "simulated": model == "offline-oracle"})
    rec["cost_usd"] = resp.cost_usd
    rec["escalated"] = True

    # ---- Grounding: the answer must be evidence-backed before it competes.
    rejects = ground_check(resp, fr.field_name)
    resp.rejects = rejects
    rec["rejects"] = rejects

    fr.attempts.append(Attempt(rung="multimodal", engine=model,
                               value=resp.value, confidence=resp.confidence,
                               cost_usd=resp.cost_usd, latency_ms=resp.latency_ms))

    if rejects:
        # Rejected: we paid, we learned nothing usable, and we say so. The field
        # keeps its OCR candidate and the governor will route it onward.
        rec["decision"] = "rejected_by_grounding"
        return rec

    # ---- Revalidation: same terms as every other candidate.
    cand = resp.value or ""
    ctx = {**page_values, fr.field_name: cand}
    cand_stamps = validate_field(fr.field_name, cand, ctx)
    cand_failed = any(s.verdict == Verdict.FAIL for s in cand_stamps)
    prim_failed = any(s.verdict == Verdict.FAIL for s in fr.stamps)

    cand_fused = fuse(resp.confidence, quality, 1, cand,
                      [s.validator for s in cand_stamps])

    # ---- Selection: validators first, then confidence. Explainable, no ML.
    if cand_failed and not prim_failed:
        rec["decision"] = "keep_primary_validators"
    elif prim_failed and not cand_failed:
        fr.value, fr.stamps, fr.confidence = cand, cand_stamps, cand_fused
        rec["decision"] = "escalation_passes_validators"
    elif cand_failed and prim_failed:
        rec["decision"] = "both_fail_validators"
    elif cand_fused > fr.confidence:
        fr.value, fr.stamps, fr.confidence = cand, cand_stamps, cand_fused
        rec["decision"] = "escalation_higher_confidence"
    else:
        rec["decision"] = "keep_primary_confidence"
    return rec
