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
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import yaml
from PIL import Image, ImageFilter

from engine.fusion import fuse
from engine.layout.mapper import template_region
from engine.ocr import get_engine
from engine.schemas import Attempt, FieldResult, Verdict
from engine.validators import validate_field
from eval.official.normalization import classify_field

_PRICES = yaml.safe_load(open("configs/prices.yaml"))
VCPU_HOUR = _PRICES["compute"]["vcpu_hour_usd"]
AGREEMENT_BONUS = 0.10          # capped at 1.0 by fuse()'s clamp
CROP_PAD = 10

# The ladder is a cheap rung, not a search. Measured over 173 retried fields:
# rung 1 won 36 fields, rung 2 won 3, and rungs 3-4 won nothing at all while
# accounting for most of the extra OCR (388 calls against a baseline of 173).
# The budget is therefore two reads - the constrained crop, and the other
# engine on the same pixels - which is where all the measured value sits.
MAX_LADDER_ATTEMPTS = 2
# Text below this height is under-resolved for the engine; scale it up.
TARGET_CROP_HEIGHT = 64
# A candidate this good, with its validators passing, ends the ladder early.
EARLY_STOP_CONFIDENCE = 0.80
# Grey-level separation below which a crop is treated as washed out.
LOW_SEPARATION = 60.0
# The second opinion. Primary OCR runs one engine over the page; the retry rung
# runs the other over the box. Two engines agreeing on a value is the strongest
# free evidence available locally, and each reads what the other misses.
SECOND_ENGINE = "paddle"
# Two engines reading a box as empty is the end of the local road. Measured on
# the degraded corpus: of 42 fields whose first two rungs read nothing, the
# later rungs "recovered" 21 - every one of them noise off the surrounding form
# ("Dm Oe wrvnes"), rejected downstream. Those rungs were 22% of all ladder OCR.
ABANDON_AFTER_EMPTY_READS = 2

DIGITS = "0123456789"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class OcrProfile:
    """One way of asking the engine to read one kind of field."""

    name: str
    psm: int
    whitelist: str | None = None


def field_profiles(field_name: str) -> list[OcrProfile]:
    """Ordered OCR profiles for a field, most specific first.

    A profile encodes what the box can legally contain. Restricting the
    character set is what separates this rung from the primary pass: the same
    pixels, read under the constraint the form itself imposes.
    """
    from engine.ocr.tesseract_engine import TesseractEngine as _T

    name = field_name.lower()
    text = OcrProfile("text", _T.PSM_BLOCK)
    if name.endswith("_sex") or name in {"patient_sex", "sex"}:
        return [OcrProfile("char", _T.PSM_CHAR, f"{LETTERS} "), text]
    if name.endswith("_state") or name == "state":
        return [OcrProfile("state", _T.PSM_LINE, LETTERS), text]
    if name.endswith("_zip") or name == "zip":
        return [OcrProfile("digits", _T.PSM_LINE, f"{DIGITS}-"), text]
    family = classify_field(field_name)
    if family == "date":
        return [OcrProfile("date", _T.PSM_LINE, f"{DIGITS}/-"),
                OcrProfile("digits", _T.PSM_LINE, DIGITS), text]
    if family == "money":
        return [OcrProfile("money", _T.PSM_LINE, f"{DIGITS}.,$"),
                OcrProfile("digits", _T.PSM_LINE, f"{DIGITS}."), text]
    if family == "quantity":
        return [OcrProfile("digits", _T.PSM_LINE, DIGITS), text]
    if family == "code":
        return [OcrProfile("code", _T.PSM_LINE, f"{LETTERS}{DIGITS}.-"),
                OcrProfile("digits", _T.PSM_LINE, DIGITS), text]
    return [text]


def _norm(s) -> str:
    """Compare two reads on what they say, not on how they punctuate it.

    Two engines that return ``02/23/26`` and ``022326`` have agreed about the
    date; one that returns ``022325`` has not. Separators differ constantly
    between engines and carry no information the validators do not already
    check, so they are removed before the agreement test.
    """
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _norm_numeric(s) -> str:
    """Agreement for amounts, where punctuation is not decoration.

    Only characters that cannot change an amount are removed: whitespace,
    currency symbols and thousands separators. The decimal point stays, so
    ``100.00`` and ``10000`` remain two different readings — and any leftover
    junk character (``00°0``) keeps the value distinct from a clean one instead
    of being normalised into false agreement with it.
    """
    return re.sub(r"[\s$,]", "", str(s or ""))


def _looks_like_an_amount(s) -> bool:
    """Digits plus a decimal or thousands mark, and no letters.

    Decided on the value rather than the field name: the frozen field
    classifier calls ``amount_paid`` a text field, and that is exactly the box
    where a lost decimal point changes what was paid.
    """
    text = str(s or "")
    return (any(c.isdigit() for c in text) and not any(c.isalpha() for c in text)
            and any(c in ".,$" for c in text))


def values_agree(field_name: str, a, b) -> bool:
    """Did two reads of this field say the same thing?

    Separators are noise on a date and on a name, and signal on an amount, so
    the comparison follows the kind of value rather than one global rule.
    """
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    if classify_field(field_name) == "date":
        return _norm(a) == _norm(b)
    if (classify_field(field_name) == "money" or _looks_like_an_amount(a)
            or _looks_like_an_amount(b)):
        return _norm_numeric(a) == _norm_numeric(b)
    return _norm(a) == _norm(b)


class RetryOutcome(NamedTuple):
    decision: str
    take_candidate: bool


def decide_retry(*, agreement: bool, prim_failed: bool, candidate,
                 cand_failed: bool, cand_fused: float,
                 primary_confidence: float, abandoned: bool = False
                 ) -> RetryOutcome:
    """Choose between the primary read and the ladder's best candidate.

    Validators outrank agreement. Agreement means two reads saw the same marks;
    it says nothing about whether the value is legal, so it must not be allowed
    to pin a field to a primary value that failed validation while a passing
    candidate is sitting right there. Getting this order wrong cost coverage on
    the degraded tiers, because a punctuation-blind match kept the bad read.
    """
    if not candidate:
        # No text is no candidate, whatever a validator makes of an empty
        # string. Decided before any validator branch below.
        return RetryOutcome("abandoned_empty" if abandoned else "no_candidate",
                            False)
    if prim_failed and not cand_failed:
        return RetryOutcome("retry_passes_validators", True)
    if agreement:
        return RetryOutcome("agree", False)
    if cand_failed:
        return RetryOutcome("keep_primary_validators", False)
    if cand_fused > primary_confidence + 0.05:
        return RetryOutcome("retry_higher_confidence", True)
    return RetryOutcome("disagree_unresolved", False)


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


def _upscaled(crop: Image.Image) -> Image.Image:
    """OCR engines are trained near ~300 DPI text height."""
    if crop.height >= TARGET_CROP_HEIGHT or crop.height == 0:
        return crop
    scale = min(4, max(2, round(TARGET_CROP_HEIGHT / crop.height)))
    return crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)


def _normalized(crop: Image.Image) -> Image.Image:
    """Crop-local contrast normalisation.

    Doing this to a whole page destroys the red-grid registration the layout
    mapper depends on, and amplifies page noise. Inside one field box there is
    no grid left to protect and only one line of ink to stretch, so the same
    operation that fails page-wide is the right one here.
    """
    gray = np.asarray(crop.convert("L"), dtype=np.float32)
    lo, hi = float(np.percentile(gray, 5)), float(np.percentile(gray, 95))
    if hi - lo < 12:
        return crop
    stretched = np.clip((gray - lo) * (255.0 / (hi - lo)), 0, 255)
    return Image.fromarray(stretched.astype(np.uint8)).convert("RGB")


def _crop_at(img: Image.Image, bbox, pad: int) -> Image.Image:
    x0, y0, x1, y1 = bbox
    return img.crop((max(0, int(x0) - pad), max(0, int(y0) - pad),
                     min(img.width, int(x1) + pad), min(img.height, int(y1) + pad)))


def _ink_separation(crop: Image.Image) -> float:
    """Paper-to-ink distance in grey levels. Low means a washed-out box."""
    gray = np.asarray(crop.convert("L"), dtype=np.float32)
    return float(np.percentile(gray, 95) - np.percentile(gray, 5))


def crop_renditions(img: Image.Image, bbox,
                    limit: int = MAX_LADDER_ATTEMPTS) -> list[tuple[str, Image.Image]]:
    """The ordered ladder of ways to present one field box to the engine.

    The order is measured, not assumed. On the generated corpus a hard Otsu
    threshold merged strokes on faint crops and read empty where the plain
    dropout crop still read text, so it is not a rung. Contrast normalisation
    only earns its place on a box whose ink is genuinely washed out, so it is
    gated on the measured separation rather than applied to every field.
    """
    base = red_dropout(_crop_at(img, bbox, CROP_PAD))
    rungs = [("dropout", _upscaled(base))]
    if len(rungs) >= limit:              # no point rendering what nothing reads
        return rungs
    if _ink_separation(base) < LOW_SEPARATION:
        rungs.append(("normalized", _upscaled(_normalized(base))))
    if len(rungs) >= limit:
        return rungs
    expanded = red_dropout(_crop_at(img, bbox, CROP_PAD * 3))
    rungs.append(("expanded", _upscaled(expanded.filter(ImageFilter.MedianFilter(3)))))
    return rungs[:limit]


def _read(eng, crop: Image.Image, profile: OcrProfile, engine_name: str):
    if engine_name != "tesseract":
        return eng.extract(crop)
    return eng.extract(crop, psm=profile.psm, whitelist=profile.whitelist)


def retry_field(fr: FieldResult, img: Image.Image, form: str, variant: int,
                page_values: dict, quality: float, ledger,
                engine_name: str = "tesseract") -> dict:
    """Walk the local retry ladder for one field. Mutates fr.

    Each rung is a genuinely different presentation of the same box - a
    different rendition, a different engine, or a different character
    constraint - rather than a repeat of the primary pass. The ladder stops at
    the first candidate that both passes its validators and is confident, so an
    easy field costs one OCR call and only a hard field pays for the full three
    or four.

    Returns a record of every rung tried, for the funnel and the audit trail.
    """
    bbox = list(fr.bbox) if fr.bbox else template_region(img, form, variant,
                                                         fr.field_name)
    if bbox is None:
        return {"field": fr.field_name, "retried": False, "reason": "no region",
                "attempts": [], "selected": "primary"}

    profiles = field_profiles(fr.field_name)
    # One slot of the budget goes to the second engine on the first rendition.
    cross_engine = engine_name != SECOND_ENGINE
    renditions = crop_renditions(
        img, bbox, max(1, MAX_LADDER_ATTEMPTS - (1 if cross_engine else 0)))
    primary_value = fr.value
    prim_failed = any(s.verdict == Verdict.FAIL for s in fr.stamps)

    # Rung order: the constrained read of the tight crop, then the other engine
    # on the same pixels, then the wider frame. Later rungs fall back to the
    # least constrained profile - if a restricted read has not worked by then,
    # the constraint is the suspect. Leading with the *unconstrained* read was
    # measured instead and lost noisy-tier coverage (CMS-1500 +2.8pp -> +1.9pp,
    # UB-04 +8.4pp -> +5.8pp) without recovering anything on the ugly tiers.
    plans = [(rendition, crop, engine_name, profiles[min(index, len(profiles) - 1)])
             for index, (rendition, crop) in enumerate(renditions)]
    if engine_name != SECOND_ENGINE:
        plans.insert(1, (f"{renditions[0][0]}:{SECOND_ENGINE}", renditions[0][1],
                         SECOND_ENGINE, profiles[0]))
    plans = plans[:MAX_LADDER_ATTEMPTS]

    attempts: list[dict] = []
    candidates: list[dict] = []
    total_cost, total_ms = 0.0, 0.0
    empty_reads, abandoned = 0, False

    for rendition, crop, rung_engine, profile in plans:
        eng = get_engine(rung_engine)
        t0 = time.perf_counter()
        words = _read(eng, crop, profile, rung_engine)
        ms = (time.perf_counter() - t0) * 1000
        cost = _cpu_cost(ms)
        total_cost, total_ms = total_cost + cost, total_ms + ms
        ledger.log(doc_id=fr.doc_id, page_id=fr.page_id, field_name=fr.field_name,
                   operation=f"retry_{rung_engine}", cost_usd=cost, latency_ms=ms,
                   meta={"rung": "retry_ocr", "rendition": rendition,
                         "profile": profile.name})

        words.sort(key=lambda w: (round((w.bbox[1] + w.bbox[3]) / 2 / 14), w.bbox[0]))
        value = " ".join(w.text for w in words).strip()
        conf = sum(w.conf for w in words) / len(words) if words else 0.0
        stamps = validate_field(fr.field_name, value,
                                {**page_values, fr.field_name: value})
        failed = any(s.verdict == Verdict.FAIL for s in stamps)
        fused = fuse(conf, quality, len(words),
                     value, [s.validator for s in stamps])
        if values_agree(fr.field_name, value, primary_value):
            fused = min(1.0, fused + AGREEMENT_BONUS)
        attempts.append({"rendition": rendition, "profile": profile.name,
                         "engine": rung_engine, "value": value or None,
                         "confidence": round(fused, 4),
                         "validators_passed": bool(value) and not failed})
        candidates.append({"rendition": rendition, "engine": rung_engine,
                           "value": value, "stamps": stamps, "failed": failed,
                           "fused": fused, "words": len(words)})
        if value and not failed and fused >= EARLY_STOP_CONFIDENCE:
            break
        empty_reads = empty_reads + 1 if not value else 0
        if empty_reads >= ABANDON_AFTER_EMPTY_READS:
            abandoned = True
            break

    # Selection: validators first, then confidence. Explainable, no ML.
    passing = [row for row in candidates if row["value"] and not row["failed"]]
    best = max(passing or candidates, key=lambda row: row["fused"])
    cand, cand_stamps = best["value"], best["stamps"]
    cand_failed, cand_fused = best["failed"], best["fused"]

    # Agreement is a property of the ladder, not of its winner: a rung that
    # confirms the primary read is evidence even when a different rung scored
    # higher. Testing only the winner threw that evidence away and let a lone
    # disagreeing rung cast doubt on a value two reads had already agreed on.
    agreement = any(values_agree(fr.field_name, row["value"], primary_value)
                    for row in candidates)
    decision, took_retry = decide_retry(
        agreement=agreement, prim_failed=prim_failed, candidate=cand,
        cand_failed=cand_failed, cand_fused=cand_fused,
        primary_confidence=fr.confidence, abandoned=abandoned)
    if took_retry:
        fr.value, fr.stamps, fr.confidence = cand, cand_stamps, cand_fused
    elif decision == "agree":
        fr.confidence = min(1.0, max(fr.confidence, cand_fused))
    elif decision == "disagree_unresolved":
        fr.confidence = min(fr.confidence, 0.6)   # disagreement is evidence of doubt

    # One logical rung, one recorded attempt, whatever the ladder cost inside.
    fr.attempts.append(Attempt(rung="retry_ocr", engine=best.get("engine", engine_name),
                               value=cand or None, confidence=cand_fused,
                               cost_usd=total_cost, latency_ms=total_ms))
    return {"field": fr.field_name, "retried": True, "agreement": agreement,
            "decision": decision, "reason": decision, "took_retry": took_retry,
            "cost_usd": total_cost, "ms": total_ms, "attempts": attempts,
            "selected": best["rendition"] if took_retry or agreement else "primary"}
