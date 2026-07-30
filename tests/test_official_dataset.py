"""Official organiser adapter contracts, using only synthetic/masked fixtures."""
from __future__ import annotations

import io
import json

from PIL import Image

from eval.official.adapter import read_tiff_pages
from eval.official.evaluator import compare_fields, phi_safe_document_row
from eval.official.linker import link_record
from eval.official.normalization import normalize_value
from eval.official.pages import select_claim_pages
from eval.official.parsers import parse_nsf_bytes, parse_ub_bytes


def _fixed(width: int, record_type: str, fields: list[tuple[int, int, str]]) -> bytes:
    row = list(record_type.ljust(width))
    for start, end, value in fields:
        row[start - 1:end] = list(value.ljust(end - start + 1)[:end - start + 1])
    return "".join(row).encode("ascii")


def test_tiff_reader_decodes_all_frames_without_retaining_file_handle():
    frames = [Image.new("1", (20, 12), color=i % 2) for i in range(3)]
    stream = io.BytesIO()
    frames[0].save(stream, format="TIFF", save_all=True, append_images=frames[1:])
    pages = read_tiff_pages(stream.getvalue())
    assert len(pages) == 3
    assert all(page.mode == "RGB" and page.size == (20, 12) for page in pages)


def test_nsf_parser_uses_one_based_inclusive_spec_positions():
    rows = [
        _fixed(320, "BA0", [(48, 62, "1234567890")]),
        _fixed(320, "CA0", [(6, 22, "MASKED-CONTROL-01"),
                              (23, 42, "EXAMPLE"), (43, 54, "PATIENT"),
                              (59, 66, "20010102")]),
        _fixed(320, "EA0", [(174, 180, "A123456")]),
        _fixed(320, "FA0", [(40, 47, "20260701"), (60, 64, "99213"),
                              (71, 77, "0012345")]),
        _fixed(320, "XA0", [(78, 84, "0012345")]),
    ]
    claims = parse_nsf_bytes(b"\r\n".join(rows) + b"\r\n")
    assert len(claims) == 1
    assert claims[0].fields["patient_name"] == "EXAMPLE, PATIENT"
    assert claims[0].fields["patient_dob"] == "20010102"
    assert claims[0].fields["diagnosis_1"] == "A123456"
    assert claims[0].fields["total_charge"] == "123.45"
    assert claims[0].service_lines[0]["procedure_code"] == "99213"


def test_ub_parser_keeps_ub_semantics_and_sums_spec_totals():
    rows = [
        _fixed(192, "10", [(8, 17, "123456789"), (97, 121, "MASKED HOSPITAL")]),
        _fixed(192, "20", [(5, 24, "MASKED-CONTROL"), (25, 44, "EXAMPLE"),
                            (45, 53, "PATIENT"), (56, 63, "20010102")]),
        _fixed(192, "40", [(25, 27, "111")]),
        _fixed(192, "60", [(25, 28, "0450"), (29, 33, "99213"),
                            (38, 44, "0000010"), (45, 54, "0000002500")]),
        _fixed(192, "70", [(25, 31, "A123456")]),
        _fixed(192, "90", [(43, 52, "0000001000"), (63, 72, "0000002500")]),
    ]
    claims = parse_ub_bytes(b"\r\n".join(rows) + b"\r\n")
    assert len(claims) == 1
    assert claims[0].format_name == "UB192"
    assert claims[0].fields["type_of_bill"] == "111"
    assert claims[0].fields["principal_dx"] == "A123456"
    assert claims[0].fields["total_charges"] == "35.00"
    assert claims[0].service_lines[0]["revenue_code"] == "0450"


def test_linker_requires_unique_score_and_reports_no_values():
    records = parse_nsf_bytes(b"\r\n".join([
        _fixed(320, "BA0", []),
        _fixed(320, "CA0", [(23, 42, "ALPHA"), (43, 54, "PERSON")]),
        _fixed(320, "BA0", []),
        _fixed(320, "CA0", [(23, 42, "BRAVO"), (43, 54, "PERSON")]),
    ]))
    linked = link_record("ALPHA PERSON", records)
    assert linked.status == "deterministic" and linked.record_ordinal == 1
    assert "ALPHA" not in json.dumps(linked.safe_receipt())

    ambiguous_records = parse_nsf_bytes(b"\r\n".join([
        _fixed(320, "BA0", []),
        _fixed(320, "CA0", [(6, 22, "CONTROL-ONE"), (23, 42, "COMMON"),
                              (43, 54, "PERSON")]),
        _fixed(320, "BA0", []),
        _fixed(320, "CA0", [(6, 22, "CONTROL-TWO"), (23, 42, "COMMON"),
                              (43, 54, "PERSON")]),
    ]))
    ambiguous = link_record("COMMON PERSON", ambiguous_records)
    assert ambiguous.status == "ambiguous" and ambiguous.record_ordinal is None
    missing = link_record("NO OCR MATCH", records)
    assert missing.status == "no_match"


def test_normalization_is_field_aware():
    assert normalize_value("patient_name", " Example,  Patient ") == "EXAMPLEPATIENT"
    assert normalize_value("patient_dob", "01/02/2001") == "20010102"
    assert normalize_value("total_charge", "$1,234.50") == "1234.50"
    assert normalize_value("diagnosis_1", "A12.3456") == "A123456"


def test_tier_b_selection_separates_claim_and_attachments():
    texts = ["fax cover sheet", "HEALTH INSURANCE CLAIM FORM CMS-1500 patient insured",
             "clinical attachment"]
    selected = select_claim_pages(texts, tier="B")
    assert selected.claim_pages == [1]
    assert selected.attachment_pages == [0, 2]
    assert selected.status == "deterministic"


def test_page_selection_refuses_ties():
    texts = ["CMS-1500 patient insured", "CMS-1500 patient insured"]
    selected = select_claim_pages(texts, tier="B")
    assert selected.status == "ambiguous"
    assert selected.claim_pages == []


def test_comparison_and_report_do_not_emit_phi_values():
    comparisons = compare_fields(
        {"patient_name": "MASKED PERSON", "total_charge": "12.30"},
        {"patient_name": "MASKED PERSON", "total_charge": "12.31"},
    )
    row = phi_safe_document_row(
        source_id="opaque-1", tier="A", page_count=1, linkage={"status": "deterministic"},
        comparisons=comparisons, latency_ms=12.0, cost_usd=0.0,
    )
    rendered = json.dumps(row)
    assert row["correct_fields"] == 1 and row["evaluated_fields"] == 2
    assert "MASKED PERSON" not in rendered
    assert "12.30" not in rendered and "12.31" not in rendered
