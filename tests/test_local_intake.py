"""Local workspace intake contracts use generated, no-PHI fixtures only."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.intake import (
    FileRole,
    IntakeError,
    classify_role,
    decode_pages,
    detect_format,
    inspect_content,
    scan_folder,
)


def _image_bytes(fmt: str, frames: int = 1) -> bytes:
    images = [Image.new("RGB", (32, 24), color=(index * 50, 30, 20))
              for index in range(frames)]
    stream = io.BytesIO()
    images[0].save(stream, format=fmt, save_all=frames > 1,
                   append_images=images[1:])
    return stream.getvalue()


@pytest.mark.parametrize(("fmt", "expected"), [
    ("PNG", "PNG"), ("JPEG", "JPEG"), ("TIFF", "TIFF"),
])
def test_raster_detection_uses_content_not_extension(fmt, expected):
    content = _image_bytes(fmt)
    assert detect_format(content) == expected
    assert inspect_content("misleading.bin", content).role == FileRole.CLAIM_DOCUMENT


def test_multipage_tiff_detection_and_numeric_extension():
    content = _image_bytes("TIFF", frames=3)
    item = inspect_content("synthetic.001", content)
    assert item.source_format == "TIFF"
    assert item.role == FileRole.CLAIM_DOCUMENT
    assert item.page_count == 3
    assert len(decode_pages(content)) == 3


def test_pdf_detection_and_page_decoding():
    content = _image_bytes("PDF", frames=2)
    item = inspect_content("synthetic.dat", content)
    assert item.source_format == "PDF"
    assert item.page_count == 2
    assert all(page.mode == "RGB" for page in decode_pages(content))


def test_pdf_page_limit_is_explicit():
    content = _image_bytes("PDF", frames=2)
    with pytest.raises(IntakeError, match="page limit"):
        decode_pages(content, max_pages=1)


def test_expected_output_text_classification():
    nsf = ("BA0" + " " * 317 + "\n").encode("ascii")
    assert detect_format(nsf) == "NSF320"
    assert classify_role("expected.txt", nsf) == FileRole.EXPECTED_OUTPUT


def test_specification_file_classification():
    content = b"UB92 File Specifications and record layout"
    assert classify_role("reference.doc.txt", content) == FileRole.SPECIFICATION


def test_unsupported_and_unknown_reporting():
    unsupported = inspect_content("archive.bin", b"PK\x03\x04payload")
    unknown = inspect_content("notes.txt", b"ordinary notes")
    assert (unsupported.role, unsupported.status) == (FileRole.UNSUPPORTED, "UNSUPPORTED")
    assert (unknown.role, unknown.status) == (FileRole.UNKNOWN, "UNKNOWN")


def test_mixed_folder_inventory_and_duplicate_hash(tmp_path):
    (tmp_path / "nested").mkdir()
    png = _image_bytes("PNG")
    (tmp_path / "claim.png").write_bytes(png)
    (tmp_path / "nested" / "copy.002").write_bytes(png)
    (tmp_path / "nested" / "expected.txt").write_bytes(
        ("BA0" + " " * 317 + "\n").encode("ascii"))
    (tmp_path / "unknown.bin").write_bytes(b"PK\x03\x04payload")

    items = scan_folder(tmp_path)

    assert [item.relative_path for item in items] == sorted(
        (item.relative_path for item in items), key=str.casefold)
    assert {item.role for item in items} >= {
        FileRole.CLAIM_DOCUMENT, FileRole.EXPECTED_OUTPUT, FileRole.UNSUPPORTED,
    }
    duplicates = [item for item in items if item.status == "DUPLICATE"]
    assert len(duplicates) == 1
    assert duplicates[0].safe_source_id == next(
        item.safe_source_id for item in items if item.filename == "claim.png")


def test_folder_validation_and_absolute_paths_excluded_from_exports(tmp_path):
    with pytest.raises(IntakeError, match="does not exist"):
        scan_folder(tmp_path / "missing")
    content = _image_bytes("PNG")
    path = tmp_path / "claim.png"
    path.write_bytes(content)
    exported = scan_folder(tmp_path)[0].public_dict()
    assert str(tmp_path) not in str(exported)
    assert "relative_path" not in exported and "content" not in exported


def test_symbolic_link_is_not_followed(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "claim.png").write_bytes(_image_bytes("PNG"))
    link = tmp_path / "loop"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are unavailable without Windows developer privileges")
    assert all(not item.relative_path.startswith("loop/") for item in scan_folder(tmp_path))
