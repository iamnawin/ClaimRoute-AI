"""Tier 0 preprocessing — signal-gated, transform-history-carrying. PIL + numpy only.

Rules (v1.2 + Day 3 spec):
- Every op fires ONLY when its measured signal crosses a threshold; clean pages
  pass through untouched (empty transform history is the proof).
- Every geometric op is appended to transform_history so ground-truth bboxes can
  be replayed through the SAME math (data_factory.degrade.rotate_with_bboxes).
- Quality score is explainable arithmetic over named signals — no ML.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from data_factory.degrade import rotate_with_bboxes

# thresholds (tuned on the generated dataset; all explainable)
SKEW_APPLY_DEG = 0.8
NOISE_APPLY = 0.30
FADE_P98_APPLY = 238.0   # paper white point below this = faded scan
ILLUM_APPLY = 0.075      # background nonuniformity above this = scanner shadow
                         # (measured: clean/noisy pages <= 0.063, shadowed ugly >= 0.094)


# ---------- signals ----------

def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _background(gray: np.ndarray) -> np.ndarray:
    """Low-frequency illumination estimate: downsample hard, blur, upsample.
    Text/grid vanish at 1/32 scale; only lighting gradients survive."""
    h, w = gray.shape
    small = Image.fromarray(gray.astype(np.uint8)).resize((max(1, w // 32), max(1, h // 32)),
                                                          Image.BOX)
    small = small.filter(ImageFilter.GaussianBlur(2))
    return np.asarray(small.resize((w, h), Image.BILINEAR), dtype=np.float32)


def signal_blur(gray: np.ndarray) -> float:
    """Laplacian variance, squashed to 0..1 (1 = sharp)."""
    lap = (gray[1:-1, 2:] + gray[1:-1, :-2] + gray[2:, 1:-1] + gray[:-2, 1:-1]
           - 4 * gray[1:-1, 1:-1])
    return float(min(1.0, np.var(lap) / 900.0))


def signal_contrast(gray: np.ndarray) -> float:
    return float(min(1.0, np.std(gray) / 64.0))


def signal_noise(gray: np.ndarray) -> float:
    """High-frequency residual vs 3x3 median (0 = clean, 1 = very noisy)."""
    med = np.asarray(Image.fromarray(gray.astype(np.uint8))
                     .filter(ImageFilter.MedianFilter(3)), dtype=np.float32)
    return float(min(1.0, np.mean(np.abs(gray - med)) / 12.0))


def signal_text_density(gray: np.ndarray) -> float:
    return float((gray < 128).mean())


def estimate_skew(img: Image.Image, max_angle: float = 15.0) -> float:
    """Projection-profile skew estimate: the correction angle that maximizes
    row-sum variance of the ink mask. Coarse 1° sweep then 0.1° refinement,
    on a 4x-downsampled page. Returns degrees to pass to Image.rotate()."""
    small = img.convert("L").resize((img.width // 4, img.height // 4), Image.BILINEAR)
    ink = (np.asarray(small) < 170).astype(np.uint8) * 255
    ink_img = Image.fromarray(ink)

    def score(angle: float) -> float:
        r = ink_img.rotate(angle, expand=False, fillcolor=0)
        rows = np.asarray(r, dtype=np.float32).sum(axis=1)
        return float(np.var(rows))

    coarse = np.arange(-max_angle, max_angle + 0.5, 1.0)
    best = max(coarse, key=score)
    fine = np.arange(best - 0.9, best + 0.95, 0.1)
    return float(round(max(fine, key=score), 2))


# ---------- pipeline ----------

def compute_quality(gray: np.ndarray, skew_deg: float) -> dict:
    blur = signal_blur(gray)
    contrast = signal_contrast(gray)
    noise = signal_noise(gray)
    density = signal_text_density(gray)
    density_ok = 1.0 if 0.003 <= density <= 0.30 else 0.0
    skew_pen = min(1.0, abs(skew_deg) / 12.0)
    score = max(0.0, min(1.0,
                0.30 * blur + 0.25 * contrast + 0.25 * (1 - noise)
                + 0.10 * (1 - skew_pen) + 0.10 * density_ok))
    band = "good" if score >= 0.72 else ("fair" if score >= 0.55 else "ugly")
    return {"quality_score": round(score, 3), "quality_band": band,
            "signals": {"blur": round(blur, 3), "contrast": round(contrast, 3),
                        "noise": round(noise, 3), "skew_degrees": skew_deg,
                        "text_density": round(density, 4)}}


def preprocess_page(img: Image.Image) -> dict:
    """Returns {processed, transform_history, quality_before, quality_after}.

    page-split note: inputs here are single-page images; PDF page splitting
    happens upstream at ingestion (one image in -> one page out, by contract).
    """
    history: list[dict] = []
    gray0 = _gray(img)
    skew0 = estimate_skew(img)
    q_before = compute_quality(gray0, skew0)
    out = img

    if abs(skew0) >= SKEW_APPLY_DEG:                       # signal-gated deskew
        pre = out.size
        out, _ = rotate_with_bboxes(out, {}, skew0)         # same math as factory
        history.append({"operation": "rotate", "angle_deg": skew0,
                        "pre_size": list(pre), "post_size": list(out.size)})

    g = _gray(out)
    bg = _background(g)
    nonuni = float((np.percentile(bg, 95) - np.percentile(bg, 5)) / 255.0)
    if nonuni >= ILLUM_APPLY:                               # signal-gated flatten
        arr = np.asarray(out, dtype=np.float32)
        gain = np.clip(245.0 / np.maximum(bg, 40.0), 0.5, 3.0)[..., None]
        out = Image.fromarray(np.clip(arr * gain, 0, 255).astype(np.uint8))
        history.append({"operation": "illumination_flatten",
                        "nonuniformity": round(nonuni, 3)})

    g = _gray(out)
    if signal_noise(g) >= NOISE_APPLY:                      # signal-gated denoise
        out = out.filter(ImageFilter.MedianFilter(3))
        history.append({"operation": "median_denoise", "kernel": 3})

    g = _gray(out)
    # Fade gate: documents are mostly paper, so std is useless here — faded paper
    # shows up as a depressed white point (p98 well below true white).
    paper_white = float(np.percentile(g, 98))
    if paper_white < FADE_P98_APPLY:                        # signal-gated stretch
        arr = np.asarray(out, dtype=np.float32)
        lo, hi = np.percentile(arr, 2), np.percentile(arr, 98)
        if hi - lo > 10:
            arr = (arr - lo) * (255.0 / (hi - lo))
            out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
            history.append({"operation": "contrast_stretch",
                            "p2": round(float(lo), 1), "p98": round(float(hi), 1)})

    g = _gray(out)
    q_after = compute_quality(g, estimate_skew(out) if history else skew0)
    return {"processed": out, "transform_history": history,
            "quality_before": q_before, "quality_after": q_after}


def transform_bboxes(bboxes: dict, history: list[dict]) -> dict:
    """Replay the ACTUAL applied geometric transforms onto ground-truth bboxes.
    Photometric ops are geometry-free by construction and are skipped."""
    out = dict(bboxes)
    for step in history:
        if step["operation"] == "rotate":
            w, h = step["pre_size"]
            dummy = Image.new("RGB", (w, h))   # RGB: fillcolor in degrade is a tuple
            _, out = rotate_with_bboxes(dummy, out, step["angle_deg"])
    return out
