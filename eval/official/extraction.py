"""ClaimRoute-compatible local extraction for monochrome organiser scans.

The frozen red-ink router is intentionally untouched. This compatibility layer
uses the same OCR schema, layout templates, validators, confidence fusion and
governor, with a grayscale form extent for the organiser's 1-bit TIFFs.
"""
from __future__ import annotations

import re
import time

import numpy as np
from PIL import Image

from engine.fusion import fuse
from engine.governor import apply
from engine.layout.mapper import load_template
from engine.ocr import get_engine
from engine.ocr.base import OcrWord
from engine.preprocess import preprocess_page
from engine.schemas import Attempt, FieldResult, PageResult
from engine.validators import run_validators


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
    extent = grayscale_form_extent(image)
    if extent is None:
        return {}
    ex0, ey0, ex1, ey1 = extent
    width, height = ex1 - ex0, ey1 - ey0
    output = {}
    for name, region in load_template(form, variant)["fields"].items():
        x0, y0 = ex0 + region[0] * width - pad, ey0 + region[1] * height - pad
        x1, y1 = ex0 + region[2] * width + pad, ey0 + region[3] * height + pad
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
            "bbox": ([min(word.bbox[0] for word in hits), min(word.bbox[1] for word in hits),
                      max(word.bbox[2] for word in hits), max(word.bbox[3] for word in hits)]
                     if hits else None),
            "n_spans": len(hits),
        }
    return output


def structured_page(image: Image.Image, words: list[OcrWord], form: str,
                    doc_id: str, preset: str = "balanced") -> PageResult:
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
    return page


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

