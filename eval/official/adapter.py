"""TIFF ingestion primitives. Inputs are opened read-only and frames are copied."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def read_tiff_pages(source: str | Path | bytes) -> list[Image.Image]:
    if isinstance(source, bytes):
        stream = io.BytesIO(source)
        image = Image.open(stream)
    else:
        image = Image.open(Path(source))
    try:
        pages = []
        for index in range(image.n_frames):
            image.seek(index)
            pages.append(image.convert("RGB").copy())
        return pages
    finally:
        image.close()


def dataset_files(root: str | Path, group: str) -> tuple[list[Path], Path]:
    directory = Path(root) / group
    images = sorted(path for path in directory.iterdir() if path.suffix.lower() != ".txt")
    outputs = list(directory.glob("*.txt"))
    if len(outputs) != 1:
        raise ValueError(f"{group}: expected exactly one fixed-width output file")
    return images, outputs[0]

