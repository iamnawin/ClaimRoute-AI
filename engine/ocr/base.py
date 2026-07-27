"""Shared OCR schema — every engine speaks (text, confidence, bbox) or it
doesn't play. Raw engine output is preserved on the adapter for debugging.
"""
from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image

# OCR engines emit CJK/full-width punctuation for ASCII glyphs (PP-OCR's
# multilingual head does this with commas and colons). Normalizing at the
# shared-schema boundary keeps every downstream validator ASCII-only.
_PUNCT_MAP = str.maketrans({
    "，": ",", "。": ".", "：": ":", "；": ";", "（": "(", "）": ")",
    "－": "-", "—": "-", "–": "-", "＄": "$", "／": "/", "＇": "'",
    "‘": "'", "’": "'", "“": '"', "”": '"', "　": " ",
})


def normalize_text(s: str) -> str:
    """NFKC + explicit punctuation folding. Applied to every engine's output."""
    return unicodedata.normalize("NFKC", str(s)).translate(_PUNCT_MAP).strip()


@dataclass
class OcrWord:
    """One recognized text span. bbox = [x0, y0, x1, y1] in image coords.
    conf normalized to 0..1 regardless of engine convention.
    Text is Unicode-normalized on construction (shared schema guarantee)."""
    text: str
    bbox: list
    conf: float

    def __post_init__(self):
        self.text = normalize_text(self.text)

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)


class OcrEngine(ABC):
    name: str = "base"

    def __init__(self):
        self.last_raw = None      # raw engine output of the most recent extract()

    @abstractmethod
    def extract(self, img: Image.Image) -> list[OcrWord]:
        ...


_REGISTRY: dict = {}


def get_engine(name: str) -> OcrEngine:
    """Lazy singleton per engine (model loads are expensive)."""
    if name not in _REGISTRY:
        if name == "tesseract":
            from engine.ocr.tesseract_engine import TesseractEngine
            _REGISTRY[name] = TesseractEngine()
        elif name == "paddle":
            from engine.ocr.paddle_engine import PaddleOnnxEngine
            _REGISTRY[name] = PaddleOnnxEngine()
        else:
            raise ValueError(f"unknown OCR engine: {name}")
    return _REGISTRY[name]
