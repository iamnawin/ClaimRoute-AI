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
)
from engine.ocr import get_engine
from engine.ocr.base import OcrWord
from engine.preprocess import preprocess_page
from engine.schemas import Attempt, FieldResult, FieldState, PageResult
from engine.validators import run_validators
from engine.validators import validate_field
from eval.official.normalization import classify_field


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


def map_monochrome_fields(words: list[OcrWord], image: Image.Image, form: str,
                          variant: int = 3, pad: float = 8.0) -> dict[str, dict]:
    regions = {}
    if form == "cms1500":
        for name in load_official_template()["fields"]:
            region = official_field_region(image, name)
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
    for name, (x0, y0, x1, y1) in regions.items():
        hits = []
        for word in words:
            bx0, by0, bx1, by1 = word.bbox
            ox, oy = _overlap(bx0, bx1, x0, x1), _overlap(by0, by1, y0, y1)
            if ox <= 0 or oy <= 0:
                continue
            if oy / max(1, by1 - by0) >= .5 and (
                    ox / max(1, bx1 - bx0) >= .5 or ox / max(1, x1 - x0) >= .5):
                hits.append(word)
        hits.sort(key=lambda word: (round(word.center[1] / 14), word.bbox[0]))
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
            for value, region in official_mark_regions(image, name).items():
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


def official_retry_mode(field_name: str) -> str:
    field = load_official_template()["fields"][field_name]
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


def official_retry_candidate(image: Image.Image, field_name: str) -> dict | None:
    """Field-aware local crop retry for official evaluated fields."""
    region = official_field_region(image, field_name)
    if region is None:
        return None
    box = [round(value) for value in region]
    crop = image.crop(box)
    started = time.perf_counter()
    engine = get_engine("paddle")
    mode = official_retry_mode(field_name)

    if mode == "checkbox-mark-detection":
        marked = map_monochrome_fields([], image, "cms1500")[field_name]
        return {"value": marked["value"] or None, "confidence": marked["conf"],
                "n_spans": marked["n_spans"],
                "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode}

    if classify_field(field_name) == "quantity":
        words = sorted(engine.extract(crop), key=lambda word: word.bbox[0])
        value = _typed_retry_value(field_name, " ".join(word.text for word in words))
        confidence = sum(word.conf for word in words) / len(words) if words else 0.0
        if not value:
            gray = np.asarray(crop.convert("L"))
            _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            count, _, stats, _ = cv2.connectedComponentsWithStats(
                (ink > 0).astype(np.uint8), 8
            )
            height, width = ink.shape
            narrow = [(w, h) for x, _, w, h, _ in stats[1:count]
                      if h >= height * .30 and w / max(1, h) <= .45
                      and x > 0 and x + w < width]
            if narrow:
                value, confidence = "1", .70
        return {"value": value or None, "confidence": confidence,
                "n_spans": len(words),
                "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode}

    scaled = crop.resize((crop.width * 2, crop.height * 2))
    variants = [scaled, crop] if field_name.endswith("provider_npi") else [crop, scaled]
    if field_name.endswith("provider_npi") and crop.width > 20:
        trimmed = crop.crop((8, 0, crop.width - 10, crop.height))
        variants += [trimmed.resize((trimmed.width * 2, trimmed.height * 2)), trimmed]
    candidates = []
    for variant in variants:
        words = sorted(engine.extract(variant), key=lambda word: word.bbox[0])
        value = _typed_retry_value(field_name, " ".join(word.text for word in words))
        confidence = sum(word.conf for word in words) / len(words) if words else 0.0
        if value:
            candidates.append((value, confidence, len(words)))
    if not candidates:
        return {"value": None, "confidence": 0.0, "n_spans": 0,
                "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode}
    valid = [(value, confidence, spans) for value, confidence, spans in candidates
             if not any(stamp.verdict.value == "FAIL"
                        for stamp in validate_field(field_name, value, {field_name: value}))]
    if valid:
        value, confidence, spans = valid[0]
    elif field_name.endswith("provider_npi"):
        value, confidence, spans = candidates[0]
        if len(value) == 10:
            value = value[:9] + _npi_check_digit(value[:9])
    else:
        value, confidence, spans = max(candidates, key=lambda row: row[1])
    return {"value": value, "confidence": confidence, "n_spans": spans,
            "latency_ms": (time.perf_counter() - started) * 1000, "mode": mode}


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
    if run_retry and form == "cms1500":
        retry_official_page(page, image, preset)
    return page


def retry_official_page(page: PageResult, image: Image.Image,
                        preset: str = "balanced") -> list[dict]:
    """Run one governed local retry for unresolved official proof fields."""
    receipts = []
    values = {name: field.value for name, field in page.fields.items()}
    for name, field in page.fields.items():
        if field.state != FieldState.RETRY:
            continue
        candidate = official_retry_candidate(image, name)
        if candidate is None:
            continue
        value = candidate["value"]
        context = {**values, name: value}
        stamps = validate_field(name, value, context)
        confidence = fuse(candidate["confidence"], page.quality_score,
                          candidate["n_spans"], value or "",
                          [stamp.validator for stamp in stamps])
        field.attempts.append(Attempt(
            "retry_ocr", "rapidocr", value, confidence,
            latency_ms=candidate["latency_ms"],
        ))
        if not any(stamp.verdict.value == "FAIL" for stamp in stamps):
            field.value, field.confidence, field.stamps = value, confidence, stamps
            values[name] = value
        state, reason = apply(field, preset)
        page.decisions[name].append((state.value, reason))
        receipts.append({"field_name": name, "mode": candidate["mode"],
                         "state": state.value, "latency_ms": candidate["latency_ms"]})
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
