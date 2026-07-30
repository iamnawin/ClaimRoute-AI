"""Offline oracle — a DETERMINISTIC TEST DOUBLE, not a model.

WHY THIS EXISTS: the Tier-2 boundary (cropper, policy gate, cache, grounding,
revalidation, governor re-entry) is the part of the architecture worth proving.
Proving it needs a responder, not necessarily a paid one. This adapter answers
from ground truth with seeded, configurable failure injection so every branch of
the boundary is exercised: good answers, hallucinations, ungrounded answers,
prose instead of JSON, and blank reads.

HONESTY RULES (these numbers appear in a scored submission):
- Accuracy produced with this adapter is NOT evidence of any real model's
  accuracy. It is evidence that the *boundary* behaves correctly.
- Cost is MODELLED from token counts priced against configs/prices.yaml, and is
  reported as PROJECTED, never as measured API spend.
- Every ledger row it writes carries meta.simulated = true. A judge can grep it.

Seeding uses crc32 of a stable string (never Python's hash(), which is
randomised per process — a hard rule in this repo).
"""
from __future__ import annotations

import json
import random
import time
import zlib
from pathlib import Path

import yaml

from engine.vision.base import (PROMPT, VisionEngine, VisionResponse,
                                expectation_for, parse_response, price_call)

_PIPE = yaml.safe_load(open("configs/pipeline.yaml"))
_SIM = _PIPE["model_policy"].get("offline_oracle", {})

# Failure mix. Defaults are deliberately pessimistic-ish so the grounding check
# and the revalidation path are genuinely exercised rather than trivially passed.
P_WRONG = _SIM.get("p_wrong", 0.06)          # confidently wrong transcription
P_UNGROUNDED = _SIM.get("p_ungrounded", 0.04)  # value not present in visible_text
P_PROSE = _SIM.get("p_prose", 0.02)          # answers with prose, not JSON
P_BLANK = _SIM.get("p_blank", 0.03)          # claims the box is empty
MODEL_TAG = _SIM.get("price_as", "gpt-5-nano")   # price row used for projection

_GT_ROOT = Path(_SIM.get("ground_truth_root", "data/generated"))
_CACHE: dict = {}


def _gt_lookup(doc_id: str, field_name: str, tier: str) -> str | None:
    """Ground-truth value for one field. Cached per (doc, tier) file read."""
    form = doc_id.split("_")[0]
    key = (form, tier, doc_id)
    if key not in _CACHE:
        p = _GT_ROOT / form / tier / "ground_truth" / f"{doc_id}.json"
        _CACHE[key] = json.loads(p.read_text()) if p.exists() else {"fields": {}}
    f = _CACHE[key]["fields"].get(field_name)
    return (f or {}).get("value") if f else None


def _corrupt(value: str, rnd: random.Random) -> str:
    """A plausible OCR-grade error: swap one confusable glyph."""
    if not value:
        return "0"
    confusables = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5",
                   "8": "B", "B": "8", "2": "Z", "Z": "2"}
    chars = list(value)
    idxs = [i for i, c in enumerate(chars) if c.upper() in confusables]
    if not idxs:
        return value[:-1] if len(value) > 1 else value + "X"
    i = rnd.choice(idxs)
    chars[i] = confusables[chars[i].upper()]
    return "".join(chars)


class OfflineOracleEngine(VisionEngine):
    name = "offline-oracle"

    def read_field(self, crop, field_name: str, *, doc_id: str = "",
                   tier: str = "clean", crop_hash: str = "") -> VisionResponse:
        t0 = time.perf_counter()
        truth = _gt_lookup(doc_id, field_name, tier) or ""

        # Stable per-(doc, field) seed: same input -> same answer, every run.
        seed = zlib.crc32(f"{doc_id}|{field_name}|{tier}".encode())
        rnd = random.Random(seed)
        roll = rnd.random()

        if roll < P_PROSE:
            body = ("I can see this appears to be a claim form field. "
                    "The text seems to read something like " + (truth or "nothing") + ".")
        elif roll < P_PROSE + P_BLANK:
            body = json.dumps({"value": "", "visible_text": "",
                               "confidence": 0.55, "reason": "box appears empty"})
        elif roll < P_PROSE + P_BLANK + P_UNGROUNDED:
            # Hallucination signature: value not backed by what it claims to see.
            body = json.dumps({"value": _corrupt(truth, rnd) or "UNKNOWN",
                               "visible_text": truth,
                               "confidence": 0.91, "reason": "read from crop"})
        elif roll < P_PROSE + P_BLANK + P_UNGROUNDED + P_WRONG:
            bad = _corrupt(truth, rnd)
            body = json.dumps({"value": bad, "visible_text": bad,
                               "confidence": 0.88, "reason": "read from crop"})
        else:
            body = json.dumps({"value": truth, "visible_text": truth,
                               "confidence": round(rnd.uniform(0.90, 0.99), 2),
                               "reason": "single value visible in crop"})

        # Token model: image crops bill as a small fixed tile budget plus prompt.
        prompt_chars = len(PROMPT.format(field_name=field_name,
                                         expectation=expectation_for(field_name)))
        in_tok = _SIM.get("image_tokens", 260) + prompt_chars // 4
        out_tok = max(12, len(body) // 4)

        resp = parse_response(body, MODEL_TAG)
        resp.model = f"offline-oracle[priced as {MODEL_TAG}]"
        resp.input_tokens, resp.output_tokens = in_tok, out_tok
        resp.cost_usd = price_call(MODEL_TAG, in_tok, out_tok)
        resp.latency_ms = (time.perf_counter() - t0) * 1000
        return resp
