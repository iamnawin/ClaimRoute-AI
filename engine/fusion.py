"""Confidence fusion — explainable weighted rule, no learned model.

Inputs (v1.2): OCR confidence + layout evidence (span sanity) + page quality +
charset/type fit. Validator VERDICTS are deliberately excluded — they reach the
governor as separate decision signals.
"""
from __future__ import annotations

import re

_CHARSET = {  # validator name -> expected charset regex for the whole value
    "npi_checksum": r"[\d ]+", "cpt_format": r"[\d ]+", "numeric_format": r"[\d ]+",
    "currency_format": r"[\d.,$ ]+", "zip_format": r"[\d\- ]+",
    "tax_id_format": r"[\d\- ]+", "date_valid": r"[\d/\- ]+",
    "icd10_format": r"[A-Za-z0-9. ]+", "id_format": r"[A-Za-z0-9 ]+",
    "name_format": r"[A-Za-z .,'\-]+", "revenue_code_format": r"[\d ]+",
}

W_OCR, W_QUALITY, W_SPANS, W_CHARSET = 0.55, 0.15, 0.15, 0.15


def charset_fit(value: str, validator_names: list[str]) -> float:
    """Fraction-of-1 fit of the value against the expected charset (cheap
    pattern prior — NOT the semantic validator itself)."""
    pats = [_CHARSET[n] for n in validator_names if n in _CHARSET]
    if not value or not pats:
        return 0.5                      # no prior either way
    return max(float(re.fullmatch(p, value) is not None) for p in pats)


def span_sanity(n_spans: int) -> float:
    """1 span is ideal; a few is fine (multi-word names); many suggests the
    mapper swept up neighbours (the Day-5 merged-names failure class)."""
    if n_spans == 0:
        return 0.0
    if n_spans <= 3:
        return 1.0
    return max(0.2, 1.0 - 0.15 * (n_spans - 3))


def fuse(ocr_conf: float, quality_score: float, n_spans: int,
         value: str, validator_names: list[str]) -> float:
    q = max(0.0, min(1.0, quality_score))
    score = (W_OCR * max(0.0, min(1.0, ocr_conf))
             + W_QUALITY * q
             + W_SPANS * span_sanity(n_spans)
             + W_CHARSET * charset_fit(value or "", validator_names))
    return round(max(0.0, min(1.0, score)), 4)
