"""Structural registration for monochrome official CMS-1500 (02-12) scans."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import yaml


TEMPLATE_PATH = Path(__file__).parent / "templates" / "official" / "cms1500_02_12.yaml"


@dataclass(frozen=True)
class FormRegistration:
    form_type: str
    revision: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float
    method: str
    anchors: list[str]
    warnings: list[str]

    @property
    def extent(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


def _binary(image: Image.Image) -> np.ndarray | None:
    gray = np.asarray(image.convert("L"))
    if int(gray.max()) - int(gray.min()) < 30:
        return None
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _horizontal_rules(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    height, width = binary.shape
    opened = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, width // 8), 1)),
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats((opened > 0).astype(np.uint8), 8)
    rules = []
    for x, y, w, h, _ in stats[1:count]:
        edge_border = x <= width * .01 and x + w >= width * .98
        if w >= width * .35 and h <= 12 and not edge_border:
            rules.append((int(x), int(y), int(w), int(h)))
    return sorted(rules, key=lambda row: row[1])


def _band_verticals(binary: np.ndarray, rules: list[tuple[int, int, int, int]],
                    left_prior: float, right_prior: float) -> tuple[list[float], list[float]]:
    height, width = binary.shape
    ys = sorted({y + h / 2 for _, y, _, h in rules
                 if height * .08 < y + h / 2 < height * .94})
    left, right = [], []
    for top, bottom in zip(ys, ys[1:]):
        if bottom - top < 35:
            continue
        y0, y1 = int(top + 6), int(bottom - 6)
        band = binary[y0:y1]
        opened = cv2.morphologyEx(
            band, cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (1, max(12, band.shape[0] * 2 // 3))
            ),
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            (opened > 0).astype(np.uint8), 8
        )
        xs = [x + w / 2 for x, _, w, h, _ in stats[1:count]
              if h >= band.shape[0] * .55 and w <= 12
              and width * .02 < x < width * .98]
        if xs:
            lmatch = min(xs, key=lambda x: abs(x - left_prior))
            rmatch = min(xs, key=lambda x: abs(x - right_prior))
            if abs(lmatch - left_prior) <= width * .04:
                left.append(float(lmatch))
            if abs(rmatch - right_prior) <= width * .04:
                right.append(float(rmatch))
    return left, right


def register_official_cms1500(image: Image.Image) -> FormRegistration | None:
    """Register the printed grid; abstain when its ruled structure is insufficient."""
    binary = _binary(image)
    if binary is None:
        return None
    height, width = binary.shape
    rules = _horizontal_rules(binary)
    long_rules = [rule for rule in rules if rule[2] >= width * .70
                  and height * .05 < rule[1] < height * .95]
    if len(long_rules) < 8:
        return None

    top = min(rule[1] + rule[3] / 2 for rule in long_rules)
    bottom = max(rule[1] + rule[3] / 2 for rule in long_rules)
    if not (.60 * height <= bottom - top <= .90 * height):
        return None

    left_prior = float(np.median([x for x, _, _, _ in long_rules]))
    right_prior = float(np.median([x + w for x, _, w, _ in long_rules]))
    left_votes, right_votes = _band_verticals(binary, rules, left_prior, right_prior)
    if len(left_votes) < 3 or len(right_votes) < 3:
        return None
    x0, x1 = float(np.median(left_votes)), float(np.median(right_votes))
    if not (.70 * width <= x1 - x0 <= .98 * width):
        return None

    rule_score = min(1.0, len(long_rules) / 15)
    vote_score = min(1.0, min(len(left_votes), len(right_votes)) / 8)
    alignment = max(0.0, 1.0 - (
        abs(x0 - left_prior) + abs(x1 - right_prior)
    ) / (width * .04))
    confidence = round(.45 * rule_score + .35 * vote_score + .20 * alignment, 3)
    edge = max(8, round(width * .012))
    warnings = []
    if max(float((binary[:, :edge] > 0).mean()),
           float((binary[:, -edge:] > 0).mean()),
           float((binary[:edge, :] > 0).mean())) > .08:
        warnings.append("page-edge dark artifact rejected")
    return FormRegistration(
        form_type="cms1500", revision="02-12", x0=x0, y0=top, x1=x1, y1=bottom,
        confidence=confidence, method="horizontal-rules+band-local-vertical-rules",
        anchors=["outer horizontal rule group", "band-local left border",
                 "band-local right border"], warnings=warnings,
    )


def _semantic_bands(binary: np.ndarray, registration: FormRegistration) -> dict[str, tuple[float, float]] | None:
    rules = _horizontal_rules(binary)
    centers = []
    for _, y, _, h in rules:
        center = y + h / 2
        if registration.y0 - 3 <= center <= registration.y1 + 3:
            if not centers or center - centers[-1] > 6:
                centers.append(center)
            else:
                centers[-1] = (centers[-1] + center) / 2

    runs, current = [], []
    for center in centers:
        if current and not 45 <= center - current[-1] <= 82:
            if len(current) >= 2:
                runs.append(current)
            current = []
        current.append(center)
    if len(current) >= 2:
        runs.append(current)
    service_candidates = [run for run in runs if len(run) >= 9
                          and registration.y0 + .5 * (registration.y1 - registration.y0) < run[-1]
                          < registration.y0 + .95 * (registration.y1 - registration.y0)]
    if not service_candidates:
        return None
    service = max(service_candidates, key=lambda run: run[-1])[-9:]
    step = float(np.median(np.diff(service)))

    patient_top_candidates = [center for center in centers if center > registration.y0 + 25]
    if not patient_top_candidates:
        return None
    patient_top = patient_top_candidates[0]
    patient_bottom = min(
        (center for center in centers if center > patient_top + step * .65),
        default=patient_top + step,
    )
    if patient_bottom - patient_top > step * 1.45:
        patient_bottom = patient_top + step

    footer_split = min(
        (center for center in centers if center > service[-1] + 20), default=None
    )
    if footer_split is None or footer_split >= registration.y1 - 10:
        return None
    return {
        "patient_row": (patient_top, patient_bottom),
        "service_line1": (service[1], service[2]),
        "footer_upper": (service[-2], service[-1]),
        "footer_lower": (footer_split, registration.y1),
    }


@lru_cache(maxsize=1)
def load_official_template() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def official_field_region(image: Image.Image, field_name: str) -> list[float] | None:
    registration = register_official_cms1500(image)
    field = load_official_template()["fields"].get(field_name)
    if registration is None or field is None:
        return None
    binary = _binary(image)
    bands = _semantic_bands(binary, registration) if binary is not None else None
    if bands is None or field["row_band"] not in bands:
        return None
    x0, y0, x1, y1 = registration.extent
    width = x1 - x0
    nx0, nx1 = field["x_region"]
    band_top, band_bottom = bands[field["row_band"]]
    fy0, fy1 = field["y_fraction"]
    left, top, right, bottom = field["padding_px"]
    return [max(0, x0 + nx0 * width - left),
            max(0, band_top + fy0 * (band_bottom - band_top) - top),
            min(image.width, x0 + nx1 * width + right),
            min(image.height, band_top + fy1 * (band_bottom - band_top) + bottom)]
