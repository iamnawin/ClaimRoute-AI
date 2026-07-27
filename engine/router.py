"""Document Intelligence Router — free, deterministic, evidence-returning.

No OCR, no API calls. Claim forms are printed in red dropout ink, so the red
layout mask is a strong OCR-free fingerprint: row/column profiles of the red
form grid are correlated against reference profiles rendered once per form.
Runs AFTER Tier-0 preprocessing (deskewed input assumed).

Returns: {"document_type", "confidence", "evidence": [...]}
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image

PROFILE_LEN = 200
RED_FRACTION_MIN = 0.0015     # below this: no form grid at all -> unstructured
ACCEPT_CORR = 0.75            # min winning correlation to claim a form type
MARGIN = 0.05                 # winner must beat runner-up by this much
W_ROWS, W_COLS = 0.45, 0.55   # columns are the robust signal on degraded scans:
                              # row profiles absorb residual-skew smear AND
                              # variable table length; vertical grid lines don't


def red_mask(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > 110) & (r - g > 20) & (r - b > 20)
    # Noise rejection: keep a pixel only if >=2 of its 4 neighbors are also red.
    # Form grid lines are connected; JPEG/Gaussian noise speckle is not.
    n = np.zeros_like(m, dtype=np.int8)
    n[1:, :] += m[:-1, :]; n[:-1, :] += m[1:, :]
    n[:, 1:] += m[:, :-1]; n[:, :-1] += m[:, 1:]
    return m & (n >= 2)


def _profiles(img: Image.Image) -> tuple[np.ndarray, np.ndarray, float]:
    m = red_mask(img)
    frac = float(m.mean())
    # Crop to the form's ink extent: preprocessing's expand-rotate adds paper
    # margins that would otherwise dilute/shift the profiles.
    # Mass-based extent (0.5%..99.5% of red mass), NOT any-pixel extent: a single
    # noise speckle in a margin must not stretch the crop to the page edge.
    def mass_extent(mass: np.ndarray) -> tuple[int, int]:
        c = np.cumsum(mass, dtype=np.float64)
        total = c[-1]
        lo = int(np.searchsorted(c, 0.005 * total))
        hi = int(np.searchsorted(c, 0.995 * total))
        return lo, max(hi, lo + 1)

    if m.sum() > 100:
        r0, r1 = mass_extent(m.sum(axis=1))
        c0, c1 = mass_extent(m.sum(axis=0))
        m = m[r0:r1 + 1, c0:c1 + 1]
    # Area-averaged binning (BOX resize), NOT point sampling: thin grid lines
    # alias out of point-sampled profiles and kill correlation.
    binned = np.asarray(
        Image.fromarray((m * 255).astype(np.uint8))
             .resize((PROFILE_LEN, PROFILE_LEN), Image.BOX), dtype=np.float32)
    rows, cols = binned.sum(axis=1), binned.sum(axis=0)

    def norm(v: np.ndarray) -> np.ndarray:
        v = np.convolve(v, np.ones(5) / 5, mode="same")   # tolerate line widening
        s = v.std()
        return (v - v.mean()) / s if s > 1e-6 else v * 0

    return norm(rows), norm(cols), frac


def _shift_corr(a: np.ndarray, b: np.ndarray, max_shift: int = 4) -> float:
    """Max Pearson correlation over small circular shifts — tolerates the bin
    misalignment left by sub-degree residual skew after deskew."""
    return max(float(np.corrcoef(a, np.roll(b, s))[0, 1])
               for s in range(-max_shift, max_shift + 1))


@lru_cache(maxsize=1)
def _references() -> dict:
    """Reference profiles per (form, table-line-count) variant — forms with
    variable-length tables shift their lower layout, so one reference per form
    under-matches. Deterministic, rendered in-memory once."""
    from data_factory.generator import generate_claim
    from data_factory.render_cms1500 import render as r1500
    from data_factory.generator_ub04 import generate_ub04
    from data_factory.render_ub04 import render as rub

    def collect(gen, render, line_key, wanted):
        out, seed = {}, 0
        while wanted - set(out) and seed < 200:
            claim = gen(seed)
            n = len(claim[line_key])
            if n not in out:
                out[n] = _profiles(render(claim)[0])[:2]
            seed += 1
        return list(out.values())

    return {
        "cms1500": collect(generate_claim, r1500, "service_lines", {1, 2, 3}),
        "ub04": collect(generate_ub04, rub, "revenue_lines", {2, 3}),
    }


def route(img: Image.Image) -> dict:
    rows, cols, frac = _profiles(img)
    evidence = [f"red-form-ink-fraction: {frac:.4f}"]

    if frac < RED_FRACTION_MIN:
        evidence.append(f"no form grid detected (< {RED_FRACTION_MIN})")
        return {"document_type": "unstructured", "confidence": 0.85,
                "evidence": evidence}

    scores = {}
    for form, variants in _references().items():
        corr = max(W_ROWS * _shift_corr(rows, rrows) + W_COLS * _shift_corr(cols, rcols)
                   for rrows, rcols in variants)
        scores[form] = corr
        evidence.append(f"layout-profile corr {form} (best variant): {corr:.3f}")

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (win, wscore), (_, second) = ranked[0], ranked[1]
    if wscore >= ACCEPT_CORR and wscore - second >= MARGIN:
        conf = round(min(0.99, 0.5 + wscore / 2), 3)
        evidence.append(f"winner margin: {wscore - second:.3f}")
        return {"document_type": win, "confidence": conf, "evidence": evidence}

    evidence.append("no profile above threshold/margin")
    return {"document_type": "unknown", "confidence": round(max(0.0, wscore), 3),
            "evidence": evidence}
