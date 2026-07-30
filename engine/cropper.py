"""Field cropper — the PHI trust boundary.

Nothing leaves this process except through crop_field(). The crops-only rule
(`model_policy.send_full_pages_externally: false`) is enforced HERE, structurally:
a crop that covers too much of the page raises rather than being sent. A config
flag that some caller might forget to check is a promise; a boundary that refuses
to emit the wrong thing is a guarantee.

Margins are bounded because both directions cost accuracy: too tight clips
glyph ascenders/descenders, too loose pulls in neighbouring boxes' values and
invites the model to answer from the wrong field.
"""
from __future__ import annotations

import base64
import hashlib
import io

import yaml
from PIL import Image

from engine.retry_rung import red_dropout

_PIPE = yaml.safe_load(open("configs/pipeline.yaml"))
_MP = _PIPE["model_policy"]

MARGIN_PX = _MP.get("crop_margin_px", 12)
MAX_PAGE_FRACTION = _MP.get("max_crop_page_fraction", 0.25)
MIN_CROP_PX = 8
UPSCALE_TO_H = 96          # small boxes: vision models see few pixels otherwise


class CropPolicyError(RuntimeError):
    """Raised when a crop would violate the PHI boundary. Never caught silently."""


def crop_field(img: Image.Image, bbox, *, dropout: bool = True) -> Image.Image:
    """Bounded, policy-checked field crop. Raises CropPolicyError on violation."""
    if bbox is None:
        raise CropPolicyError("no bbox: refusing to fall back to the full page")

    x0, y0, x1, y1 = (float(v) for v in bbox)
    x0 = max(0, int(x0) - MARGIN_PX)
    y0 = max(0, int(y0) - MARGIN_PX)
    x1 = min(img.width, int(x1) + MARGIN_PX)
    y1 = min(img.height, int(y1) + MARGIN_PX)
    if x1 - x0 < MIN_CROP_PX or y1 - y0 < MIN_CROP_PX:
        raise CropPolicyError(f"degenerate crop {(x0, y0, x1, y1)}")

    fraction = ((x1 - x0) * (y1 - y0)) / float(img.width * img.height)
    if fraction > MAX_PAGE_FRACTION:
        raise CropPolicyError(
            f"crop covers {fraction:.1%} of the page (limit {MAX_PAGE_FRACTION:.0%}); "
            "send_full_pages_externally is false"
        )

    crop = img.crop((x0, y0, x1, y1))
    if dropout:
        crop = red_dropout(crop)          # form ink is not evidence; drop it
    if crop.height < UPSCALE_TO_H:
        scale = max(1, round(UPSCALE_TO_H / crop.height))
        if scale > 1:
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    return crop


def crop_png_bytes(crop: Image.Image) -> bytes:
    buf = io.BytesIO()
    crop.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def crop_b64(crop: Image.Image) -> str:
    return base64.b64encode(crop_png_bytes(crop)).decode("ascii")


def crop_hash(crop: Image.Image) -> str:
    """Content hash of the exact pixels sent. The cache key's image half, and
    the audit record's proof of *what* crossed the boundary."""
    return hashlib.sha256(crop_png_bytes(crop)).hexdigest()[:16]
