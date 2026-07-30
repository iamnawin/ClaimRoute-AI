"""Tesseract adapter (word granularity). License: Apache-2.0."""
from __future__ import annotations

import os
import shutil

import pytesseract
from PIL import Image

from engine.ocr.base import OcrEngine, OcrWord

# pytesseract is only a wrapper; the binary must be found. PATH first, then the
# standard Windows install locations, then an explicit override. Resolving here
# keeps the repo clone-and-run on a fresh machine instead of requiring the user
# to edit PATH before the pipeline works.
_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
)


def _resolve_binary() -> str | None:
    override = os.environ.get("TESSERACT_CMD")
    if override and os.path.exists(override):
        return override
    found = shutil.which("tesseract")
    if found:
        return found
    return next((p for p in _CANDIDATES if os.path.exists(p)), None)


_BINARY = _resolve_binary()
if _BINARY:
    pytesseract.pytesseract.tesseract_cmd = _BINARY


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
