"""Tesseract adapter (word granularity). License: Apache-2.0."""
from __future__ import annotations

import pytesseract
from PIL import Image

from engine.ocr.base import OcrEngine, OcrWord


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def extract(self, img: Image.Image) -> list[OcrWord]:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        self.last_raw = data
        words = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:          # conf -1 = layout artifacts
                continue
            x, y, w, h = (data["left"][i], data["top"][i],
                          data["width"][i], data["height"][i])
            words.append(OcrWord(text=text, bbox=[x, y, x + w, y + h],
                                 conf=conf / 100.0))
        return words
