"""Structural registration for monochrome official UB-04 CMS-1450 scans."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
import yaml

from engine.layout.official_cms1500_registration import (
    FormRegistration, _binary, _horizontal_rules,
)


TEMPLATE_PATH = Path(__file__).parent / "templates" / "official" / "ub04_cms1450.yaml"


def _candidate_registration(image: Image.Image) -> FormRegistration | None:
    binary = _binary(image)
    if binary is None:
        return None
    height, width = binary.shape
    long_rules = [rule for rule in _horizontal_rules(binary)
                  if rule[2] >= width * .70 and height * .005 < rule[1] < height * .96]
    if len(long_rules) < 18:
        return None

    centers = sorted(rule[1] + rule[3] / 2 for rule in long_rules)
    top, bottom = centers[0], centers[-1]
    span = (bottom - top) / height
    if not .84 <= span <= .94:
        return None

    x0s = np.asarray([x for x, _, _, _ in long_rules], dtype=float)
    x1s = np.asarray([x + w for x, _, w, _ in long_rules], dtype=float)
    x0, x1 = float(np.median(x0s)), float(np.median(x1s))
    if not .85 * width <= x1 - x0 <= .99 * width:
        return None

    normalized = [(center - top) / (bottom - top) for center in centers]
    gaps = [(b - a, a, b) for a, b in zip(normalized, normalized[1:])]
    _, grid_top, grid_bottom = max(gaps)
    # The 23-line revenue grid is the dominant vertical gap on a correctly
    # oriented CMS-1450. A 180-degree page puts it in the wrong half.
    layout_score = max(0.0, 1.0 - abs(grid_top - .27) / .18
                       - abs(grid_bottom - .62) / .18)
    if layout_score < .25:
        return None

    endpoint_spread = (float(np.median(np.abs(x0s - x0)))
                       + float(np.median(np.abs(x1s - x1)))) / width
    alignment_score = max(0.0, 1.0 - endpoint_spread / .035)
    rule_score = min(1.0, len(long_rules) / 24)
    span_score = max(0.0, 1.0 - abs(span - .91) / .05)
    confidence = round(.35 * rule_score + .25 * alignment_score
                       + .20 * span_score + .20 * layout_score, 3)
    if confidence < .70:
        return None

    edge = max(8, round(width * .012))
    warnings = []
    if max(float((binary[:, :edge] > 0).mean()),
           float((binary[:, -edge:] > 0).mean()),
           float((binary[:edge, :] > 0).mean()),
           float((binary[-edge:, :] > 0).mean())) > .08:
        warnings.append("page-edge dark artifact rejected")
    return FormRegistration(
        form_type="ub04", revision="CMS-1450", x0=x0, y0=top, x1=x1, y1=bottom,
        confidence=confidence, method="horizontal-rule-grid+revenue-band",
        anchors=["outer horizontal rule group", "23-line revenue grid",
                 "stable rule endpoints"], warnings=warnings,
    )


def normalize_official_ub04_page(image: Image.Image) -> tuple[Image.Image, FormRegistration] | None:
    """Correct cardinal orientation and return the registered page, or abstain."""
    candidates = []
    for angle in (0, 90, 180, 270):
        rotated = image.rotate(angle, expand=True) if angle else image.copy()
        registration = _candidate_registration(rotated)
        if registration is not None:
            candidates.append((registration.confidence, -angle, rotated, registration))
    if not candidates:
        return None
    _, _, normalized, registration = max(candidates, key=lambda row: (row[0], row[1]))
    return normalized, registration


def register_official_ub04(image: Image.Image) -> FormRegistration | None:
    """Register an already upright page; callers needing rotation use normalize."""
    return _candidate_registration(image)


@lru_cache(maxsize=1)
def load_official_ub04_template() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def official_ub04_field_region(image: Image.Image, field_name: str,
                               registration: FormRegistration | None = None) -> list[float] | None:
    registration = registration or register_official_ub04(image)
    field = load_official_ub04_template()["fields"].get(field_name)
    if registration is None or field is None:
        return None
    x0, y0, x1, y1 = registration.extent
    width, height = x1 - x0, y1 - y0
    nx0, nx1 = field["x_region"]
    ny0, ny1 = field["y_region"]
    left, top, right, bottom = field["padding_px"]
    return [max(0, x0 + nx0 * width - left),
            max(0, y0 + ny0 * height - top),
            min(image.width, x0 + nx1 * width + right),
            min(image.height, y0 + ny1 * height + bottom)]
