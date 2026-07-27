"""Render a synthetic claim as a UB-04 (CMS-1450)-style page image.

Same conventions as render_cms1500: red form ink, typewriter black values,
exact bbox emitted for every value. Programmatic replica, not pixel-identical.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from data_factory.render_cms1500 import W, H, RED, BLACK, MARGIN, _fonts


def render(claim: dict) -> tuple[Image.Image, dict]:
    img = Image.new("RGB", (W, H), (252, 250, 246))
    d = ImageDraw.Draw(img)
    f_label, f_value, f_title, f_small = _fonts()
    bboxes: dict[str, list] = {}

    def box(x, y, w, h, label, field=None, value="", vfont=None):
        d.rectangle([x, y, x + w, y + h], outline=RED, width=2)
        d.text((x + 6, y + 4), label.upper(), fill=RED, font=f_label)
        if field is not None and value:
            vf = vfont or f_value
            vx, vy = x + 10, y + 26
            d.text((vx, vy), str(value), fill=BLACK, font=vf)
            l, t, r, b = d.textbbox((vx, vy), str(value), font=vf)
            bboxes[field] = [l, t, r, b]

    d.text((MARGIN, 28), "UB-04  CMS-1450", fill=RED, font=f_title)
    d.text((W - 400, 36), "INSTITUTIONAL CLAIM (SYNTH)", fill=RED, font=f_label)

    y = 90
    box(MARGIN, y, 700, 70, "1. Provider Name", "provider_name", claim["provider_name"])
    box(MARGIN + 710, y, 300, 70, "3a. Pat. Cntl #", "patient_control_no", claim["patient_control_no"])
    box(MARGIN + 1020, y, 280, 70, "3b. Med. Rec. #", "medical_record_no", claim["medical_record_no"])
    box(MARGIN + 1310, y, W - 2 * MARGIN - 1310, 70, "4. Type of Bill", "type_of_bill", claim["type_of_bill"])

    y += 80
    box(MARGIN, y, 330, 70, "5. Fed. Tax No.", "federal_tax_no", claim["federal_tax_no"])
    box(MARGIN + 340, y, 330, 70, "6. Statement From", "statement_from", claim["statement_from"])
    box(MARGIN + 680, y, 330, 70, "Through", "statement_to", claim["statement_to"])
    box(MARGIN + 1020, y, W - 2 * MARGIN - 1020, 70, "12. Admission Date", "admission_date", claim["admission_date"])

    y += 80
    box(MARGIN, y, 640, 70, "8b. Patient Name", "patient_name", claim["patient_name"])
    box(MARGIN + 650, y, 540, 70, "9a. Patient Address", "patient_address", claim["patient_address"])
    box(MARGIN + 1200, y, 220, 70, "10. Birthdate", "patient_dob", claim["patient_dob"])
    box(MARGIN + 1430, y, W - 2 * MARGIN - 1430, 70, "11. Sex", "patient_sex", claim["patient_sex"])

    # Revenue lines (FL 42–47)
    y += 90
    cols = [("42. Rev. Cd.", "rev_code", 220), ("44. HCPCS/Rate", "hcpcs", 300),
            ("45. Serv. Date", "service_date", 300), ("46. Serv. Units", "units", 220),
            ("47. Total Charges", "charges", 320)]
    x = MARGIN
    for title_, _, w in cols:
        box(x, y, w, 40, title_)
        x += w
    y += 40
    for i, line in enumerate(claim["revenue_lines"], start=1):
        x = MARGIN
        for _, key, w in cols:
            box(x, y, w, 60, "", f"line{i}_{key}", line[key], vfont=f_small)
            x += w
        y += 60
    box(MARGIN + 1040, y, 320, 64, "Totals", "total_charges", claim["total_charges"])

    # Payer / insured / dx / physicians
    y += 88
    box(MARGIN, y, 500, 70, "50. Payer Name", "payer_name", claim["payer_name"])
    box(MARGIN + 510, y, 500, 70, "56. NPI", "provider_npi", claim["provider_npi"])
    box(MARGIN + 1020, y, W - 2 * MARGIN - 1020, 70, "58. Insured's Name", "insured_name", claim["insured_name"])

    y += 80
    box(MARGIN, y, 500, 70, "60. Insured's Unique ID", "insured_id", claim["insured_id"])
    box(MARGIN + 510, y, 400, 70, "67. Prin. Diag. Cd.", "principal_dx", claim["principal_dx"])
    box(MARGIN + 920, y, 500, 70, "76. Attending NPI", "attending_npi", claim["attending_npi"])

    return img, bboxes
