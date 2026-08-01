"""Content-aware, localhost-safe document intake primitives."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PIL import Image

from eval.official.adapter import read_tiff_pages


class FileRole(str, Enum):
    CLAIM_DOCUMENT = "CLAIM_DOCUMENT"
    EXPECTED_OUTPUT = "EXPECTED_OUTPUT"
    SPECIFICATION = "SPECIFICATION"
    ATTACHMENT = "ATTACHMENT"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class IntakeError(ValueError):
    pass


@dataclass
class IntakeFile:
    filename: str
    safe_source_id: str
    source_format: str
    role: FileRole
    page_count: int | None
    size_bytes: int
    status: str = "READY"
    warning: str = ""
    group_key: str = "."
    relative_path: str = ""
    content: bytes = field(default=b"", repr=False)

    def public_dict(self) -> dict:
        """Metadata safe for UI exports: never includes bytes or an absolute path."""
        return {
            "filename": self.filename,
            "safe_source_id": self.safe_source_id,
            "source_format": self.source_format,
            "source_role": self.role.value,
            "page_count": self.page_count,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "warning": self.warning,
            "group": self.group_key,
        }


def _safe_id(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:12]


def detect_format(content: bytes) -> str:
    """Detect supported containers from content, independent of the filename."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if content.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if b"%PDF-" in content[:1024]:
        return "PDF"
    if content.startswith(b"PK\x03\x04"):
        return "ZIP"

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError:
            return "BINARY"
    stripped = text.strip()
    if not stripped:
        return "EMPTY"
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    widths = {len(line.encode("latin-1", errors="replace")) for line in lines}
    if widths == {320}:
        return "NSF320"
    if widths == {192}:
        return "UB192"
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return "JSON"
    except json.JSONDecodeError:
        pass
    return "TEXT"


def _is_specification(filename: str, text: str) -> bool:
    haystack = re.sub(r"[^A-Z0-9]+", " ", f"{filename} {text[:4096]}".upper())
    return any(marker in haystack for marker in (
        "NSF MATRIX", "NSF 320 SPEC", "UB92 FILE SPEC", "UB 92 FILE SPEC",
        "UB192 SPEC", "UB 192 SPEC", "FILE SPECIFICATION",
    ))


def classify_role(filename: str, content: bytes, source_format: str | None = None) -> FileRole:
    source_format = source_format or detect_format(content)
    lowered = filename.casefold()
    if source_format in {"PNG", "JPEG", "TIFF", "PDF"}:
        return (FileRole.ATTACHMENT if any(token in lowered for token in (
            "attachment", "fax_cover", "fax-cover", "cover_sheet", "cover-sheet"
        )) else FileRole.CLAIM_DOCUMENT)
    if source_format in {"NSF320", "UB192"}:
        return FileRole.EXPECTED_OUTPUT
    if source_format == "JSON":
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return FileRole.UNKNOWN
        if isinstance(payload, dict) and isinstance(payload.get("fields"), dict):
            return FileRole.EXPECTED_OUTPUT
        return FileRole.UNKNOWN
    if source_format == "TEXT":
        text = content.decode("latin-1", errors="ignore")
        return FileRole.SPECIFICATION if _is_specification(filename, text) else FileRole.UNKNOWN
    if source_format in {"ZIP", "BINARY"}:
        return FileRole.UNSUPPORTED
    return FileRole.UNKNOWN


def decode_pages(content: bytes, source_format: str | None = None,
                 *, max_pages: int = 100, pdf_scale: float = 2.0) -> list[Image.Image]:
    """Decode supported content to copied RGB pages; PDFs are always rasterized."""
    source_format = source_format or detect_format(content)
    if source_format == "TIFF":
        pages = read_tiff_pages(content)
    elif source_format in {"PNG", "JPEG"}:
        with Image.open(io.BytesIO(content)) as image:
            pages = [image.convert("RGB").copy()]
    elif source_format == "PDF":
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - deployment configuration guard
            raise IntakeError("PDF support requires the pinned pypdfium2 dependency.") from exc
        try:
            pdf = pdfium.PdfDocument(content)
            try:
                if len(pdf) > max_pages:
                    raise IntakeError(
                        f"Document page limit is {max_pages}; received {len(pdf)} pages.")
                pages = []
                for index in range(len(pdf)):
                    page = pdf[index]
                    try:
                        bitmap = page.render(scale=pdf_scale)
                        try:
                            pages.append(bitmap.to_pil().convert("RGB").copy())
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
            finally:
                pdf.close()
        except IntakeError:
            raise
        except Exception as exc:
            raise IntakeError("The PDF could not be decoded safely.") from exc
    else:
        raise IntakeError(f"Unsupported document content: {source_format}.")
    if len(pages) > max_pages:
        raise IntakeError(f"Document page limit is {max_pages}; received {len(pages)} pages.")
    if not pages:
        raise IntakeError("The document contains no decodable pages.")
    return pages


def inspect_content(filename: str, content: bytes, *, relative_path: str = "",
                    group_key: str = ".", max_pages: int = 100) -> IntakeFile:
    source_format = detect_format(content)
    role = classify_role(filename, content, source_format)
    item = IntakeFile(
        filename=Path(filename).name,
        safe_source_id=_safe_id(content),
        source_format=source_format,
        role=role,
        page_count=None,
        size_bytes=len(content),
        group_key=group_key,
        relative_path=relative_path,
        content=content,
    )
    if role in {FileRole.CLAIM_DOCUMENT, FileRole.ATTACHMENT}:
        try:
            item.page_count = len(decode_pages(content, source_format, max_pages=max_pages))
        except IntakeError as exc:
            item.status = "ERROR"
            item.warning = str(exc)
    elif role == FileRole.UNSUPPORTED:
        item.status = "UNSUPPORTED"
        item.warning = f"Detected {source_format}; no decoder is available."
    elif role == FileRole.UNKNOWN:
        item.status = "UNKNOWN"
        item.warning = "File role or content format is not recognized."
    return item


def scan_folder(folder: str | Path, *, max_pages: int = 100) -> list[IntakeFile]:
    """Recursively inventory regular files without following symbolic links."""
    base = Path(folder).expanduser()
    if not base.exists():
        raise IntakeError("Local dataset path does not exist.")
    if not base.is_dir():
        raise IntakeError("Local dataset path must be a folder.")
    base = base.resolve()
    items = []
    for root, dirs, files in os.walk(base, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(
            (name for name in dirs if not (root_path / name).is_symlink()),
            key=str.casefold,
        )
        for name in sorted(files, key=str.casefold):
            path = root_path / name
            relative = path.relative_to(base).as_posix()
            group = path.parent.relative_to(base).as_posix() or "."
            if path.is_symlink():
                items.append(IntakeFile(
                    filename=name,
                    safe_source_id=hashlib.sha256(relative.encode()).hexdigest()[:12],
                    source_format="SYMLINK",
                    role=FileRole.UNSUPPORTED,
                    page_count=None,
                    size_bytes=0,
                    status="UNSUPPORTED",
                    warning="Symbolic links are not followed.",
                    group_key=group,
                    relative_path=relative,
                ))
                continue
            try:
                content = path.read_bytes()
                items.append(inspect_content(
                    name, content, relative_path=relative, group_key=group,
                    max_pages=max_pages,
                ))
            except OSError:
                items.append(IntakeFile(
                    filename=name,
                    safe_source_id=hashlib.sha256(relative.encode()).hexdigest()[:12],
                    source_format="UNREADABLE",
                    role=FileRole.UNKNOWN,
                    page_count=None,
                    size_bytes=0,
                    status="ERROR",
                    warning="File could not be read.",
                    group_key=group,
                    relative_path=relative,
                ))
    items.sort(key=lambda item: (item.relative_path.casefold(), item.safe_source_id))
    first_by_hash: dict[str, str] = {}
    for item in items:
        if not item.content:
            continue
        first = first_by_hash.get(item.safe_source_id)
        if first is None:
            first_by_hash[item.safe_source_id] = item.filename
        else:
            item.status = "DUPLICATE"
            item.warning = f"Duplicate content; first seen as {first}."
    return items
