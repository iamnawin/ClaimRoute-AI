"""PaddleOCR-family adapter: PP-OCR detection+recognition models executed via
ONNX Runtime (rapidocr-onnxruntime). Same model weights as PaddleOCR, far
lighter deployment — that trade-off is itself part of the cost story.
Licenses: RapidOCR Apache-2.0, ONNX Runtime MIT, PP-OCR models Apache-2.0.

Granularity note: PP-OCR emits LINE-level spans, not words; the shared schema
allows spans of any length, and field-region matching concatenates by position.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from engine.ocr.base import OcrEngine, OcrWord


class PaddleOnnxEngine(OcrEngine):
    name = "paddle"

    def __init__(self):
        super().__init__()
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()

    def extract(self, img: Image.Image) -> list[OcrWord]:
        result, _ = self._ocr(np.asarray(img.convert("RGB")))
        self.last_raw = result
        words = []
        for quad, text, score in (result or []):
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            text = str(text).strip()
            if text:
                words.append(OcrWord(text=text,
                                     bbox=[min(xs), min(ys), max(xs), max(ys)],
                                     conf=float(score)))
        return words
