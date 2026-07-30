"""Cheap retry rung — crop-level re-OCR with the secondary engine.

Local compute only (priced from configs/prices.yaml, logged to the ledger):
near-zero incremental cost per field, but never free. Runs BEFORE any paid
model call, and its output re-enters validation exactly like any other
candidate — the multimodal rung is not the only thing that must earn trust.

Engine agreement is computed HERE and only here (v1.2: agreement is a
retry-rung signal, never a first-pass cost).
"""
from __future__ import annotations

import re
import time

import yaml
from PIL import Image

from engine.fusion import fuse
from engine.layout.mapper import template_region
from engine.ocr import get_engine
from engine.schemas import Attempt, FieldResult, Verdict
from engine.validators import validate_field

_PRICES = yaml.safe_load(open("configs/prices.yaml"))
VCPU_HOUR = _PRICES["compute"]["vcpu_hour_usd"]
AGREEMENT_BONUS = 0.10          # capped at 1.0 by fuse()'s clamp
CROP_PAD = 10


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def _cpu_cost(ms: float) -> float:
    return ms / 1000 / 3600 * VCPU_HOUR


def red_dropout(crop: Image.Image) -> Image.Image:
    """Whiten the red form grid before crop OCR — the same principle real
    claim scanners use (CMS forms are printed in OCR-dropout red). Without it
    a tight crop's label text and rule lines are read as garbage tokens.

    NB: uses a RAW red test, not router.red_mask — the router's connectivity
    filter deliberately keeps isolated red pixels (noise rejection for layout
    profiling), but for dropout we want every red pixel gone. Values are
    printed in black, so being aggressive here is safe.
    """
    import numpy as np
    arr = np.asarray(crop.convert("RGB")).copy().astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    arr[(r > 110) & (r - g > 20) & (r - b > 20)] = 255
    return Image.fromarray(arr.astype(np.uint8))


def retry_field(fr: FieldResult, img: Image.Image, form: str, variant: int,
                page_values: dict, quality: float, ledger,
                engine_name: str = "tesseract") -> dict:
    """Re-OCR one field's crop; revalidate; fuse with agreement. Mutates fr.

    Returns a small record for the funnel metrics.
    """
    bbox = list(fr.bbox) if fr.bbox else template_region(img, form, variant,
                                                         fr.field_name)
    if bbox is None:
        return {"field": fr.field_name, "retried": False, "reason": "no region"}

    x0, y0, x1, y1 = bbox
    crop = img.crop((max(0, int(x0) - CROP_PAD), max(0, int(y0) - CROP_PAD),
                     min(img.width, int(x1) + CROP_PAD),
                     min(img.height, int(y1) + CROP_PAD)))
    crop = red_dropout(crop)
    # Upscale small crops: OCR engines are trained near ~300 DPI text height.
    if crop.height < 60:
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)

    t0 = time.perf_counter()
    eng = get_engine(engine_name)
    # A field crop is one box, not a page. Ask for block segmentation where the
    # engine supports it; the default page mode drops lone characters entirely
    # (patient_sex, units, diagnosis_pointer) — precisely the fields the retry
    # rung exists to rescue.
    if engine_name == "tesseract":
        words = eng.extract(crop, psm=eng.PSM_BLOCK)
    else:
        words = eng.extract(crop)
    ms = (time.perf_counter() - t0) * 1000
    cost = _cpu_cost(ms)
    ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
               operation=f"retry_{engine_name}", cost_usd=cost, latency_ms=ms,
               meta={"rung": "retry_ocr"})

    words.sort(key=lambda w: (round((w.bbox[1] + w.bbox[3]) / 2 / 14), w.bbox[0]))
    cand = " ".join(w.text for w in words).strip()
    cand_conf = sum(w.conf for w in words) / len(words) if words else 0.0
    primary_value = fr.value

    # Revalidation — the retry candidate is evaluated on the same terms.
    ctx = {**page_values, fr.field_name: cand}
    cand_stamps = validate_field(fr.field_name, cand, ctx)
    cand_failed = any(s.verdict == Verdict.FAIL for s in cand_stamps)
    prim_failed = any(s.verdict == Verdict.FAIL for s in fr.stamps)

    agreement = _norm(cand) == _norm(primary_value) and bool(cand)
    vnames = [s.validator for s in cand_stamps]
    cand_fused = fuse(cand_conf, quality, len(words), cand, vnames)
    if agreement:
        cand_fused = min(1.0, cand_fused + AGREEMENT_BONUS)

    # Selection: validators decide, then confidence. Explainable, no ML.
    took_retry = False
    if agreement:
        fr.confidence = min(1.0, max(fr.confidence, cand_fused))
        decision = "agree"
    elif prim_failed and not cand_failed:
        fr.value, fr.stamps, fr.confidence = cand, cand_stamps, cand_fused
        took_retry, decision = True, "retry_passes_validators"
    elif not prim_failed and cand_failed:
        decision = "keep_primary_validators"
    elif cand_fused > fr.confidence + 0.05:
        fr.value, fr.stamps, fr.confidence = cand, cand_stamps, cand_fused
        took_retry, decision = True, "retry_higher_confidence"
    else:
        fr.confidence = min(fr.confidence, 0.6)   # disagreement is evidence of doubt
        decision = "disagree_unresolved"

    fr.attempts.append(Attempt(rung="retry_ocr", engine=engine_name,
                               value=cand or None, confidence=cand_fused,
                               cost_usd=cost, latency_ms=ms))
    return {"field": fr.field_name, "retried": True, "agreement": agreement,
            "decision": decision, "took_retry": took_retry,
            "cost_usd": cost, "ms": ms}
