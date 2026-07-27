"""Degradation pipeline — clean / noisy / ugly tiers, with bbox transforms.

Design rule: only GEOMETRIC ops (rotation) move coordinates, and every geometric
op transforms the ground-truth bboxes in lockstep. Photometric ops (noise, blur,
JPEG, shadow, contrast, down-up scaling back to original size) leave geometry
untouched by construction. Bbox drift is the silent assassin in document-AI
benchmarks — `check_bbox_ink` is the guardrail that catches it.
"""
from __future__ import annotations

import io
import math
import random

import numpy as np
from PIL import Image, ImageFilter

PAPER = (252, 250, 246)


# ---------- geometric ----------

def rotate_with_bboxes(img: Image.Image, bboxes: dict, angle_deg: float
                       ) -> tuple[Image.Image, dict]:
    """Rotate CCW by angle_deg (expand=True) and transform all bboxes.

    A content point p maps to: p' = R(-angle) @ (p - c_old) + c_new
    in screen coordinates (y down); each bbox becomes the axis-aligned
    envelope of its four transformed corners.
    """
    w, h = img.size
    out = img.rotate(angle_deg, expand=True, resample=Image.BICUBIC, fillcolor=PAPER)
    w2, h2 = out.size
    cx, cy, cx2, cy2 = w / 2, h / 2, w2 / 2, h2 / 2
    th = math.radians(angle_deg)
    cos, sin = math.cos(th), math.sin(th)

    def tf(x, y):
        dx, dy = x - cx, y - cy
        # y-down screen coords: visual CCW rotation = math CW on raw coords
        return (dx * cos + dy * sin + cx2, -dx * sin + dy * cos + cy2)

    new = {}
    for k, (x0, y0, x1, y1) in bboxes.items():
        pts = [tf(x0, y0), tf(x1, y0), tf(x0, y1), tf(x1, y1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        new[k] = [min(xs), min(ys), max(xs), max(ys)]
    return out, new


# ---------- photometric (geometry-free) ----------

def add_gaussian_noise(img: Image.Image, rng: random.Random, sigma: float) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    noise_rng = np.random.default_rng(rng.getrandbits(32))
    arr += noise_rng.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def low_dpi(img: Image.Image, factor: float) -> Image.Image:
    """Downscale then upscale back to ORIGINAL size — blurry, geometry unchanged."""
    w, h = img.size
    small = img.resize((int(w * factor), int(h * factor)), Image.BILINEAR)
    return small.resize((w, h), Image.BILINEAR)


def shadow(img: Image.Image, rng: random.Random, strength: float) -> Image.Image:
    """Smooth diagonal illumination gradient (scanner shadow)."""
    w, h = img.size
    xx, yy = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    corner = rng.choice([(0, 0), (0, 1), (1, 0), (1, 1)])
    dist = np.sqrt((xx - corner[0]) ** 2 + (yy - corner[1]) ** 2) / math.sqrt(2)
    mask = (1.0 - strength * (1.0 - dist))[..., None]
    arr = np.asarray(img).astype(np.float32) * mask
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def contrast_fade(img: Image.Image, amount: float) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    arr = 128 + (arr - 128) * (1.0 - amount) + amount * 18
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------- tiers ----------

def degrade(img: Image.Image, bboxes: dict, tier: str, seed: int
            ) -> tuple[Image.Image, dict, dict]:
    """Apply a tier profile. Returns (image, transformed_bboxes, meta)."""
    rng = random.Random(seed)
    meta: dict = {"tier": tier, "seed": seed}
    if tier == "clean":
        return img, dict(bboxes), meta

    if tier == "noisy":
        out = img
        out = add_gaussian_noise(out, rng, sigma=rng.uniform(6, 11))
        out = out.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
        q = rng.randint(38, 55)
        out = jpeg_roundtrip(out, q)
        meta["jpeg_q"] = q
        return out, dict(bboxes), meta

    if tier == "ugly":
        angle = rng.uniform(4.0, 12.0) * rng.choice([-1, 1])
        out, bb = rotate_with_bboxes(img, bboxes, angle)
        out = low_dpi(out, rng.uniform(0.45, 0.6))
        out = shadow(out, rng, strength=rng.uniform(0.18, 0.32))
        out = contrast_fade(out, rng.uniform(0.10, 0.22))
        out = add_gaussian_noise(out, rng, sigma=rng.uniform(8, 14))
        q = rng.randint(30, 45)
        out = jpeg_roundtrip(out, q)
        meta.update({"angle_deg": round(angle, 3), "jpeg_q": q})
        return out, bb, meta

    raise ValueError(f"unknown tier: {tier}")


# ---------- guardrail ----------

def check_bbox_ink(img: Image.Image, bboxes: dict, sample: int = 8,
                   min_dark_fraction: float = 0.004, pad: int = 4) -> list[str]:
    """Verify stored bboxes still cover ink after degradation.

    Crops each sampled bbox (+pad) and requires a minimum fraction of dark
    pixels (value ink). Returns the list of FAILING field names (empty = OK).
    """
    gray = np.asarray(img.convert("L"))
    names = sorted(bboxes)[:sample] if sample else sorted(bboxes)
    failures = []
    for name in names:
        x0, y0, x1, y1 = bboxes[name]
        x0, y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
        x1, y1 = min(gray.shape[1], int(x1) + pad), min(gray.shape[0], int(y1) + pad)
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0 or (crop < 128).mean() < min_dark_fraction:
            failures.append(name)
    return failures
