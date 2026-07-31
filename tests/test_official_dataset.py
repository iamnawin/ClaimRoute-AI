"""Official organiser adapter contracts, using only synthetic/masked fixtures."""
from __future__ import annotations

import io
import json

from PIL import Image

from eval.official.adapter import read_tiff_pages
from eval.official.evaluator import compare_fields, phi_safe_document_row
from eval.official.linker import link_record
from eval.official.normalization import classify_field, normalize_value
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
    assert normalize_value("type_of_bill", "0117") == normalize_value(
        "type_of_bill", "117"
    )


def test_aliased_line_item_names_reach_their_typed_branch():
    """``claimroute_expected`` generates line{n}_* names; they must still classify.

    Regression guard for the defect where suffix-generated names fell through to
    the text branch and scored incorrect even when OCR was perfect.
    """
    assert classify_field("line1_date_from") == "date"
    assert classify_field("line3_date_to") == "date"
    assert classify_field("line2_charges") == "money"
    assert classify_field("line1_units") == "quantity"
    assert classify_field("line1_cpt_code") == "text"


def test_date_routing_survives_printed_component_order():
    # Records store YYYYMMDD; the form prints MM DD YYYY in separate boxes.
    assert normalize_value("line1_date_from", "20240315") == \
        normalize_value("line1_date_from", "03 15 2024")
    assert normalize_value("line4_date_to", "20241201") == \
        normalize_value("line4_date_to", "12/01/2024")


def test_date_routing_still_separates_different_days():
    assert normalize_value("line1_date_from", "20240315") != \
        normalize_value("line1_date_from", "03 16 2024")


def test_charge_routing_aligns_decimals_rather_than_stripping_them():
    # Stripping punctuation alone makes "1500" and "1500.00" disagree; the money
    # branch must compare decimal value, including when cents are not printed.
    assert normalize_value("line1_charges", "1500.00") == \
        normalize_value("line1_charges", "$1,500.00")
    assert normalize_value("line1_charges", "1500.00") == \
        normalize_value("line1_charges", "1500")
    assert normalize_value("line2_charges", "75.50") != \
        normalize_value("line2_charges", "75.05")


def test_quantity_routing_ignores_parser_decimal_scaling():
    # The NSF parser scales units to one decimal; the form prints an integer.
    assert normalize_value("line1_units", "1.0") == normalize_value("line1_units", "1")
    assert normalize_value("line1_units", "100.0") == normalize_value("line1_units", "100")
    assert normalize_value("line1_units", "2.0") != normalize_value("line1_units", "3")


def test_identifier_routing_normalizes_punctuation_but_not_digits():
    for field in ("billing_provider_npi", "referring_provider_npi"):
        assert normalize_value(field, "1234567893") == normalize_value(field, "1234-567 893")
        assert normalize_value(field, "1234567893") != normalize_value(field, "1234567894")
    assert normalize_value("diagnosis_code_a", "A123456") == \
        normalize_value("diagnosis_code_a", "a12.3456")
    assert normalize_value("line1_cpt_code", "99213") != \
        normalize_value("line1_cpt_code", "99214")


def test_unknown_fields_fall_through_to_text_rather_than_a_typed_branch():
    for unknown in ("mystery_field", "", "line1_", "date_from_prefix_only"):
        assert classify_field(unknown) == "text"
    # A bare 8-digit string in an unclassified field must not be reordered as a date.
    assert normalize_value("mystery_field", "03152024") == "03152024"
    assert normalize_value("mystery_field", None) == ""


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
