"""ClaimRoute-compatible local extraction for monochrome organiser scans.

The frozen red-ink router is intentionally untouched. This compatibility layer
uses the same OCR schema, layout templates, validators, confidence fusion and
governor, with a grayscale form extent for the organiser's 1-bit TIFFs.
"""
from __future__ import annotations

import re
import time

import cv2
import numpy as np
from PIL import Image

from engine.fusion import fuse
from engine.governor import apply
from engine.layout.mapper import load_template
from engine.layout.official_cms1500_registration import (
    load_official_template, official_field_region, official_mark_regions,
    register_official_cms1500,
)
from engine.layout.official_ub04_registration import (
    load_official_ub04_template, official_ub04_field_region,
    register_official_ub04,
)
from engine.ocr import get_engine
from engine.ocr.base import OcrWord
from engine.preprocess import preprocess_page
from engine.schemas import Attempt, FieldResult, FieldState, PageResult
from engine.validators import run_validators
from engine.validators import validate_field
from eval.official.normalization import classify_field
from eval.official.ocr_retry import (
    RetryCandidate, candidate_values, extract_profile, load_retry_profiles,
    select_best_candidate, should_stop_retry,
)


def local_ocr(image: Image.Image) -> tuple[list[OcrWord], str, float]:
    start = time.perf_counter()
    words = get_engine("tesseract").extract(image)
    return words, " ".join(word.text for word in words), (time.perf_counter() - start) * 1000


def grayscale_form_extent(image: Image.Image) -> list[int] | None:
    ink = np.asarray(image.convert("L")) < 210
    rows, cols = np.where(ink)
    if len(rows) < 100:
        return None
    return [int(np.quantile(cols, .002)), int(np.quantile(rows, .002)),
            int(np.quantile(cols, .998)), int(np.quantile(rows, .998))]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _words_in_region(words: list[OcrWord], region: list[float]) -> list[OcrWord]:
    x0, y0, x1, y1 = region
    hits = []
    for word in words:
        bx0, by0, bx1, by1 = word.bbox
        ox, oy = _overlap(bx0, bx1, x0, x1), _overlap(by0, by1, y0, y1)
        if ox <= 0 or oy <= 0:
            continue
        if oy / max(1, by1 - by0) >= .5 and (
                ox / max(1, bx1 - bx0) >= .5 or ox / max(1, x1 - x0) >= .5):
            hits.append(word)
    return sorted(hits, key=lambda word: (round(word.center[1] / 14), word.bbox[0]))


def map_monochrome_fields(words: list[OcrWord], image: Image.Image, form: str,
                          variant: int = 3, pad: float = 8.0) -> dict[str, dict]:
    regions = {}
    if form == "cms1500":
        registration = register_official_cms1500(image)
        for name in load_official_template()["fields"]:
            region = official_field_region(image, name, registration)
            if region is not None:
                regions[name] = region
    elif form == "ub04":
        registration = register_official_ub04(image)
        for name in load_official_ub04_template()["fields"]:
            region = official_ub04_field_region(image, name, registration)
            if region is not None:
                regions[name] = region
    else:
        extent = grayscale_form_extent(image)
        if extent is None:
            return {}
        ex0, ey0, ex1, ey1 = extent
        width, height = ex1 - ex0, ey1 - ey0
        regions = {
            name: [ex0 + region[0] * width - pad, ey0 + region[1] * height - pad,
                   ex0 + region[2] * width + pad, ey0 + region[3] * height + pad]
            for name, region in load_template(form, variant)["fields"].items()
        }
    output = {}
    for name, region in regions.items():
        x0, y0, x1, y1 = region
        hits = _words_in_region(words, region)
        output[name] = {
            "value": " ".join(word.text for word in hits),
            "conf": sum(word.conf for word in hits) / len(hits) if hits else 0.0,
            "bbox": [x0, y0, x1, y1],
            "n_spans": len(hits),
        }
    if form == "cms1500":
        for name, field in load_official_template()["fields"].items():
            if not field.get("mark_options") or name not in output:
                continue
            scores = {}
            for value, region in official_mark_regions(image, name, registration).items():
                crop = np.asarray(image.crop([round(v) for v in region]).convert("L"))
                if crop.size:
                    inner = crop[max(1, crop.shape[0] // 5):-max(1, crop.shape[0] // 5),
                                 max(1, crop.shape[1] // 5):-max(1, crop.shape[1] // 5)]
                    scores[value] = float((inner < 160).mean()) if inner.size else 0.0
            if scores:
                ranked = sorted(scores.items(), key=lambda row: row[1], reverse=True)
                value, score = ranked[0]
                margin = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
                output[name].update(value=value if margin >= .03 else "",
                                    conf=min(.99, .70 + margin), n_spans=1)
    return output


def _npi_check_digit(first_nine: str) -> str:
    digits = [int(char) for char in "80840" + first_nine]
    parity = (len(digits) + 1) % 2
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)


def _typed_retry_value(field_name: str, text: str) -> str:
    digits = "".join(char for char in text if char.isascii() and char.isdigit())
    family = classify_field(field_name)
    if family == "date":
        return digits[-8:]
    if family == "money":
        groups = re.findall(r"\d+", text.replace(",", ""))
        return f"{groups[0]}.{groups[-1][-2:]}" if len(groups) >= 2 else (
            f"{digits}.00" if digits else "")
    if family == "quantity":
        return digits or ("1" if "T" in text.upper() else "")
    if field_name in {"billing_provider_npi", "referring_provider_npi"}:
        return digits[:10]
    if field_name == "federal_tax_id":
        return digits[:9]
    return text.strip()


def _official_template(form: str) -> dict:
    return (load_official_ub04_template() if form == "ub04"
            else load_official_template())


def _official_region(image: Image.Image, field_name: str, form: str) -> list[float] | None:
    return (official_ub04_field_region(image, field_name) if form == "ub04"
            else official_field_region(image, field_name))


def official_retry_mode(field_name: str, form: str = "cms1500") -> str:
    field = _official_template(form)["fields"][field_name]
    if field.get("mark_options"):
        return "checkbox-mark-detection"
    return {
        "date": "date-digits-x-order",
        "money": "money-decimal-preserving",
        "quantity": "isolated-quantity",
        "identifier": "identifier-digits",
        "diagnosis_code": "diagnosis-code",
        "procedure_code": "procedure-code",
        "code": "isolated-code",
        "text": "field-text",
    }[field["field_type"]]


def _quantity_component_candidates(field_name: str, crop: Image.Image,
                                   attempt_index: int) -> list[RetryCandidate]:
    """Read a right-aligned digit even when it touches the printed box rule."""
    gray = np.asarray(crop.convert("L"))
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    height, width = ink.shape
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, width // 2), 1)),
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, height // 2))),
    )
    clean = ink.copy()
    clean[cv2.bitwise_or(horizontal, vertical) > 0] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        (clean > 0).astype(np.uint8), 8
    )
    parts = [row for row in stats[1:count] if row[4] >= 3 and row[3] >= height * .15]
    if not parts:
        return []
    x0, y0 = min(row[0] for row in parts), min(row[1] for row in parts)
    x1 = max(row[0] + row[2] for row in parts)
    y1 = max(row[1] + row[3] for row in parts)
    pad = 2
    tight = Image.fromarray(255 - clean[
        max(0, y0 - pad):min(height, y1 + pad),
        max(0, x0 - pad):min(width, x1 + pad),
    ])
    tight = tight.resize((tight.width * 8, tight.height * 8), Image.Resampling.LANCZOS)
    words = get_engine("tesseract").extract(tight, psm=13)
    return candidate_values(
        field_name, words, source="component_tesseract",
        attempt_index=attempt_index,
    )


def official_retry_candidate(image: Image.Image, field_name: str,
                             shared_words: list[OcrWord] | None = None,
                             region: list[float] | None = None,
                             form: str = "cms1500") -> dict | None:
    """Field-aware local crop retry for official evaluated fields."""
    region = region or _official_region(image, field_name, form)
    if region is None:
        return None
    box = [round(value) for value in region]
    crop = image.crop(box)
    started = time.perf_counter()
    mode = official_retry_mode(field_name, form)

    if mode == "checkbox-mark-detection":
        marked = map_monochrome_fields([], image, form)[field_name]
        return {"value": marked["value"] or None, "confidence": marked["conf"],
                "n_spans": marked["n_spans"],
                "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode}

    profiles = load_retry_profiles()
    family = _official_template(form)["fields"][field_name]["field_type"]
    family_profile = profiles["field_families"].get(
        family, profiles["field_families"]["text"]
    )
    candidates: list[RetryCandidate] = []
    ranked = None

    if shared_words is not None:
        hits = _words_in_region(shared_words, region)
        candidates.extend(candidate_values(
            field_name, hits, source="shared_page", attempt_index=0
        ))
        ranked = select_best_candidate(field_name, candidates, {})

    attempts_used = 0
    if not should_stop_retry(ranked, .50):
        for index, profile in enumerate(
                family_profile["attempts"][:family_profile["max_attempts"]], start=1):
            attempt_started = time.perf_counter()
            words = sorted(extract_profile(crop, profile), key=lambda word: word.bbox[0])
            latency_ms = (time.perf_counter() - attempt_started) * 1000
            attempts_used += 1
            candidates.extend(candidate_values(
                field_name, words, source=f"crop_{profile['engine']}",
                attempt_index=index, latency_ms=latency_ms,
            ))
            ranked = select_best_candidate(field_name, candidates, {})
            if should_stop_retry(ranked, .50):
                break

    if classify_field(field_name) == "quantity" and not candidates:
        candidates.extend(_quantity_component_candidates(field_name, crop, attempts_used))
        ranked = select_best_candidate(field_name, candidates, {})

    if classify_field(field_name) == "quantity" and not candidates:
        gray = np.asarray(crop.convert("L"))
        _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        count, _, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), 8)
        height, width = ink.shape
        narrow = [(w, h) for x, _, w, h, _ in stats[1:count]
                  if h >= height * .30 and w / max(1, h) <= .45
                  and x > 0 and x + w < width]
        if narrow:
            candidates.append(RetryCandidate("1", .70, 1, "component", attempts_used))
            ranked = select_best_candidate(field_name, candidates, {})

    if ranked is None:
        return {"value": None, "confidence": 0.0, "n_spans": 0,
                "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode,
                "attempts_used": attempts_used, "source": "none"}
    selected = ranked.candidate
    return {"value": selected.value, "confidence": selected.confidence,
            "n_spans": selected.n_spans,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "mode": mode, "attempts_used": attempts_used,
            "source": selected.source}


def structured_page(image: Image.Image, words: list[OcrWord], form: str,
                    doc_id: str, preset: str = "balanced",
                    run_retry: bool = False) -> PageResult:
    quality = preprocess_page(image)["quality_before"]["quality_score"]
    page = PageResult(doc_id, "p1", form, quality_score=quality)
    mapped = map_monochrome_fields(words, image, form)
    raw_values = {name: row["value"] for name, row in mapped.items()}
    stamps = run_validators(raw_values)
    for name, row in mapped.items():
        vnames = [stamp.validator for stamp in stamps.get(name, [])]
        confidence = fuse(row["conf"], quality, row["n_spans"], row["value"], vnames)
        field = FieldResult(doc_id, "p1", name, row["value"] or None,
                            confidence=confidence,
                            bbox=tuple(row["bbox"]) if row["bbox"] else None)
        field.stamps = stamps.get(name, [])
        field.attempts = [Attempt("primary_ocr", "tesseract", field.value, confidence)]
        state, reason = apply(field, preset)
        page.fields[name] = field
        page.decisions[name] = [(state.value, reason)]
    if run_retry and form in {"cms1500", "ub04"}:
        retry_official_page(page, image, preset)
    return page


def retry_official_page(page: PageResult, image: Image.Image,
                        preset: str = "balanced") -> list[dict]:
    """Run one governed local retry for unresolved official proof fields."""
    receipts = []
    values = {name: field.value for name, field in page.fields.items()}
    if not any(field.state == FieldState.RETRY for field in page.fields.values()):
        return receipts
    shared_started = time.perf_counter()
    shared_words = extract_profile(image, load_retry_profiles()["shared_page"])
    shared_latency_ms = (time.perf_counter() - shared_started) * 1000
    for name, field in page.fields.items():
        if field.state != FieldState.RETRY:
            continue
        candidate = official_retry_candidate(
            image, name, shared_words=shared_words,
            region=list(field.bbox) if field.bbox else None,
            form=page.doc_type,
        )
        if candidate is None:
            continue
        value = candidate["value"]
        context = {**values, name: value}
        stamps = validate_field(name, value, context)
        confidence = fuse(candidate["confidence"], page.quality_score,
                          candidate["n_spans"], value or "",
                          [stamp.validator for stamp in stamps])
        field.attempts.append(Attempt(
            "retry_ocr", candidate.get("source", "local_profile"), value, confidence,
            latency_ms=candidate["latency_ms"],
        ))
        primary = RetryCandidate(
            field.value or "", field.confidence, 1 if field.value else 0, "primary", -1
        )
        retry = RetryCandidate(
            value or "", candidate["confidence"], candidate["n_spans"],
            candidate.get("source", "retry"), 0,
        )
        selected = select_best_candidate(name, [primary, retry], values)
        if selected and selected.candidate.source != "primary":
            field.value, field.confidence, field.stamps = value, confidence, stamps
            values[name] = value
        state, reason = apply(field, preset)
        page.decisions[name].append((state.value, reason))
        receipts.append({"field_name": name, "mode": candidate["mode"],
                         "source": candidate.get("source"),
                         "attempts_used": candidate.get("attempts_used", 0),
                         "state": state.value, "latency_ms": candidate["latency_ms"],
                         "shared_page_latency_ms": shared_latency_ms})
    return receipts


_DATE = r"(?:\d{1,2}[/.-]){2}\d{2,4}|\d{8}"
_MONEY = r"\$?\s*[0-9][0-9,]*\.\d{2}"


def unstructured_fields(text: str) -> dict[str, str]:
    """Conservative label-driven Tier-D extraction. No unlabeled value guessing."""
    patterns = {
        "patient_name": r"(?:PATIENT|MEMBER)\s+NAME\s*[:#-]?\s*([A-Z][A-Z ,.'-]{3,45})",
        "patient_dob": rf"(?:DOB|DATE OF BIRTH)\s*[:#-]?\s*({_DATE})",
        "patient_account_no": r"(?:PATIENT ACCOUNT|CLAIM)\s*(?:NO|NUMBER|#)?\s*[:#-]?\s*([A-Z0-9-]{5,25})",
        "total_charge": rf"(?:TOTAL (?:CHARGE|CHARGES|BILLED))\s*[:$#-]?\s*({_MONEY})",
        "provider_npi": r"(?:PROVIDER\s+)?NPI\s*[:#-]?\s*(\d{10})",
        "diagnosis_1": r"(?:DIAGNOSIS|ICD(?:-10)?)\s*(?:CODE)?\s*[:#-]?\s*([A-Z][0-9A-Z.]{2,7})",
    }
    normalized = re.sub(r"\s+", " ", text.upper())
    output = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, normalized)
        if match:
            output[name] = match.group(1).strip()
    return output
