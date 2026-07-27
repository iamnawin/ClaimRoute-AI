"""Layout mapper: assign OCR spans to template field regions.

Region matching is OVERLAP-based, not center-in-box: PP-OCR emits line spans
that can merge a value with its neighbor; overlap + horizontal clipping keeps
the parts that belong to the field (the Day-4 bake-off's center-matching
under-measured exactly this case).
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.ocr.base import OcrWord
from engine.router import form_extent

TDIR = Path(__file__).parent / "templates"
_CACHE: dict = {}


def load_template(form: str, variant: int) -> dict:
    key = (form, variant)
    if key not in _CACHE:
        _CACHE[key] = json.loads((TDIR / f"{form}_v{variant}.json").read_text())
    return _CACHE[key]


def _overlap_1d(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def template_region(img, form: str, variant: int, field: str) -> list | None:
    """Absolute page bbox of a field's template region — the retry rung's
    fallback when the primary pass produced no bbox (empty field)."""
    ext = form_extent(img)
    r = load_template(form, variant)["fields"].get(field)
    if ext is None or r is None:
        return None
    x0e, y0e, x1e, y1e = ext
    w, h = x1e - x0e, y1e - y0e
    return [x0e + r[0] * w, y0e + r[1] * h, x0e + r[2] * w, y0e + r[3] * h]


def map_fields(words: list[OcrWord], img, form: str, variant: int,
               pad: float = 8.0) -> dict:
    """-> {field: {value, conf, bbox, n_spans}} in page coordinates."""
    ext = form_extent(img)
    if ext is None:
        return {}
    x0e, y0e, x1e, y1e = ext
    w, h = x1e - x0e, y1e - y0e
    tpl = load_template(form, variant)
    out = {}
    for name, r in tpl["fields"].items():
        fx0, fy0 = x0e + r[0] * w - pad, y0e + r[1] * h - pad
        fx1, fy1 = x0e + r[2] * w + pad, y0e + r[3] * h + pad
        hits = []
        for wd in words:
            bx0, by0, bx1, by1 = wd.bbox
            ov_y = _overlap_1d(by0, by1, fy0, fy1)
            ov_x = _overlap_1d(bx0, bx1, fx0, fx1)
            if ov_y <= 0 or ov_x <= 0:
                continue
            span_h = max(1.0, by1 - by0)
            span_w = max(1.0, bx1 - bx0)
            if ov_y / span_h >= 0.5 and (ov_x / span_w >= 0.5 or ov_x / (fx1 - fx0) >= 0.5):
                hits.append(wd)
        hits.sort(key=lambda t: (round((t.bbox[1] + t.bbox[3]) / 2 / 14), t.bbox[0]))
        if hits:
            out[name] = {
                "value": " ".join(t.text for t in hits).strip(),
                "conf": round(sum(t.conf for t in hits) / len(hits), 4),
                "bbox": [min(t.bbox[0] for t in hits), min(t.bbox[1] for t in hits),
                         max(t.bbox[2] for t in hits), max(t.bbox[3] for t in hits)],
                "n_spans": len(hits),
            }
        else:
            out[name] = {"value": "", "conf": 0.0, "bbox": None, "n_spans": 0}
    return out
