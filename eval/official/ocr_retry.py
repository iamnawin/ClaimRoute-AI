"""Deterministic, field-family OCR retry helpers for official CMS-1500 crops."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageOps
import yaml

from engine.ocr import get_engine
from engine.ocr.base import OcrWord
from engine.validators import validate_field
from eval.official.normalization import classify_field, normalize_value


PROFILE_PATH = Path(__file__).with_name("ocr_retry_profiles.yaml")


@dataclass(frozen=True)
class RetryCandidate:
    value: str
    confidence: float
    n_spans: int
    source: str
    attempt_index: int
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RankedCandidate:
    candidate: RetryCandidate
    stamps: list
    score: tuple


@lru_cache(maxsize=1)
def load_retry_profiles() -> dict:
    return yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))


def preprocess_crop(image: Image.Image, profile: dict) -> Image.Image:
    """Apply only the deterministic operations declared by one retry profile."""
    trim = int(profile.get("border_trim", 0))
    crop = image.crop((trim, trim, image.width - trim, image.height - trim)) if (
        trim and image.width > trim * 2 and image.height > trim * 2
    ) else image
    gray_image = crop.convert("L")
    if profile.get("contrast_normalization"):
        gray_image = ImageOps.autocontrast(gray_image)
    gray = np.asarray(gray_image).copy()
    if profile.get("remove_lines"):
        ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        horizontal = cv2.morphologyEx(
            ink, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, round(gray.shape[1] * .6)), 1)),
        )
        vertical = cv2.morphologyEx(
            ink, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, round(gray.shape[0] * .6)))),
        )
        gray[cv2.bitwise_or(horizontal, vertical) > 0] = 255
    scale = int(profile.get("scale", 1))
    if scale > 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    threshold = profile.get("threshold", "none")
    if threshold == "otsu":
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    elif threshold == "adaptive":
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
    if profile.get("invert"):
        gray = cv2.bitwise_not(gray)
    return Image.fromarray(gray)


def extract_profile(image: Image.Image, profile: dict) -> list[OcrWord]:
    prepared = preprocess_crop(image, profile)
    engine = get_engine(profile["engine"])
    if profile["engine"] == "tesseract":
        return engine.extract(prepared, psm=profile.get("psm"))
    return engine.extract(prepared)


def _mean_confidence(words: list[OcrWord]) -> float:
    return sum(word.conf for word in words) / len(words) if words else 0.0


def candidate_values(field_name: str, words: list[OcrWord], *, source: str = "crop",
                     attempt_index: int = 0, latency_ms: float = 0.0) -> list[RetryCandidate]:
    """Generate typed candidates without consulting expected or organiser values."""
    spans = [word for word in words if word.text.strip()]
    joined = " ".join(word.text.strip() for word in spans)
    mean = _mean_confidence(spans)
    raw: list[tuple[str, float, int]] = [
        (word.text.strip(), word.conf, 1) for word in spans
    ]
    if joined:
        raw.append((joined, mean, len(spans)))

    family = classify_field(field_name)
    if family == "date":
        digit_groups = [re.sub(r"\D", "", word.text) for word in spans]
        joined_digits = "".join(digit_groups)
        raw.extend((digits, mean, len(spans)) for digits in [*digit_groups, joined_digits]
                   if len(digits) in (6, 8))
    elif family == "money":
        groups = re.findall(r"\d+", joined.replace(",", ""))
        if groups:
            value = f"{groups[0]}.{groups[-1][-2:]}" if len(groups) >= 2 else f"{groups[0]}.00"
            raw.append((value, mean, len(spans)))
    elif family == "quantity":
        digits = re.sub(r"\D", "", joined)
        if digits:
            raw.append((digits, mean, len(spans)))
        elif "T" in joined.upper():
            raw.append(("1", mean, len(spans)))
    elif field_name.endswith("provider_npi"):
        digits = re.sub(r"\D", "", joined)
        raw.extend((digits[index:index + 10], mean, len(spans))
                   for index in range(max(0, len(digits) - 9)))
    elif field_name == "federal_tax_id":
        digits = re.sub(r"\D", "", joined)
        raw.extend((digits[index:index + 9], mean, len(spans))
                   for index in range(max(0, len(digits) - 8)))
    elif field_name.startswith("diagnosis_code_"):
        raw.extend((match, mean, len(spans)) for match in re.findall(
            r"[A-TV-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?", joined.upper()
        ))
    elif field_name.endswith("_cpt_code"):
        raw.extend((match, mean, len(spans))
                   for match in re.findall(r"(?<!\d)\d{5}(?!\d)", joined))
    elif field_name == "insured_id":
        raw.extend((match, mean, len(spans))
                   for match in re.findall(r"\b[A-Z0-9]{6,15}\b", joined.upper()))
    elif family == "code":
        raw.extend((match, mean, len(spans))
                   for match in re.findall(r"\b[A-Z0-9]{1,10}\b", joined.upper()))

    candidates, seen = [], set()
    for value, confidence, n_spans in raw:
        value = value.strip()
        key = normalize_value(field_name, value)
        if value and key and key not in seen:
            seen.add(key)
            candidates.append(RetryCandidate(
                value, confidence, n_spans, source, attempt_index, latency_ms
            ))
    return candidates


def select_best_candidate(field_name: str, candidates: list[RetryCandidate],
                          context: dict) -> RankedCandidate | None:
    if not candidates:
        return None
    agreements = Counter(normalize_value(field_name, row.value) for row in candidates)
    ranked = []
    for candidate in candidates:
        stamps = validate_field(field_name, candidate.value, {**context, field_name: candidate.value})
        failures = sum(stamp.verdict.value == "FAIL" for stamp in stamps)
        passes = sum(stamp.verdict.value == "PASS" for stamp in stamps)
        agreement = agreements[normalize_value(field_name, candidate.value)]
        score = (-failures, passes, agreement, candidate.confidence,
                 -candidate.attempt_index)
        ranked.append(RankedCandidate(candidate, stamps, score))
    return max(ranked, key=lambda row: row.score)


def should_stop_retry(ranked: RankedCandidate | None, minimum_confidence: float) -> bool:
    if ranked is None or ranked.candidate.confidence < minimum_confidence:
        return False
    return bool(ranked.stamps) and all(
        stamp.verdict.value != "FAIL" for stamp in ranked.stamps
    )
