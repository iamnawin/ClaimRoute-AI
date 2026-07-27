"""Render a synthetic claim as a CMS-1500-style page image (PIL, 200 DPI letter).

A programmatic replica of the CMS-1500 layout: red form ink (the real form is
printed in OCR-dropout red), typewriter-style black values. Not pixel-identical
to the official form — an official blank-PDF overlay is a drop-in swap later.

Crucially, the renderer emits an exact bbox for every value it draws, so the
ground truth contains both values AND coordinates (needed to score Tier-1
layout mapping, and to be transformed alongside any Tier-0 deskew).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

W, H = 1700, 2200          # 8.5x11in @ 200 DPI
RED = (192, 80, 70)        # form ink
BLACK = (25, 25, 30)       # value ink
MARGIN = 60

_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def _fonts():
    try:
        label = ImageFont.truetype(_FONT_DIR + "DejaVuSans.ttf", 16)
        value = ImageFont.truetype(_FONT_DIR + "DejaVuSansMono.ttf", 26)
        title = ImageFont.truetype(_FONT_DIR + "DejaVuSans-Bold.ttf", 30)
        small = ImageFont.truetype(_FONT_DIR + "DejaVuSansMono.ttf", 22)
    except OSError:                       # Windows / no DejaVu — degrade gracefully
        label = value = title = small = ImageFont.load_default()
    return label, value, title, small


def render(claim: dict) -> tuple[Image.Image, dict]:
    """Returns (page image, {field_name: bbox}) with bbox = [x0, y0, x1, y1]."""
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

    # Header
    d.text((MARGIN, 28), "HEALTH INSURANCE CLAIM FORM", fill=RED, font=f_title)
    d.text((W - 420, 36), "APPROVED CMS-1500 (SYNTH)", fill=RED, font=f_label)

    y = 90
    box(MARGIN, y, 1040, 70, "1a. Insured's I.D. Number", "insured_id", claim["insured_id"])
    box(MARGIN + 1050, y, W - 2 * MARGIN - 1050, 70, "11c. Insurance Plan Name",
        "insurance_plan_name", claim["insurance_plan_name"])

    y += 80
    box(MARGIN, y, 640, 70, "2. Patient's Name (Last, First)", "patient_name", claim["patient_name"])
    box(MARGIN + 650, y, 330, 70, "3. Patient's Birth Date", "patient_dob", claim["patient_dob"])
    box(MARGIN + 990, y, 140, 70, "Sex", "patient_sex", claim["patient_sex"])
    box(MARGIN + 1140, y, W - 2 * MARGIN - 1140, 70, "4. Insured's Name",
        "insured_name", claim["insured_name"])

    y += 80
    box(MARGIN, y, 640, 70, "5. Patient's Address", "patient_address", claim["patient_address"])
    box(MARGIN + 650, y, 330, 70, "City", "patient_city", claim["patient_city"])
    box(MARGIN + 990, y, 140, 70, "State", "patient_state", claim["patient_state"])
    box(MARGIN + 1140, y, 220, 70, "Zip Code", "patient_zip", claim["patient_zip"])
    box(MARGIN + 1370, y, W - 2 * MARGIN - 1370, 70, "6. Rel. to Insured",
        "patient_relationship", claim["patient_relationship"])

    # Diagnosis block
    y += 90
    box(MARGIN, y, W - 2 * MARGIN, 40, "21. Diagnosis or Nature of Illness (ICD-10)")
    y += 40
    dx_w = (W - 2 * MARGIN) // 4
    for i, letter in enumerate("abcd"):
        key = f"diagnosis_code_{letter}"
        box(MARGIN + i * dx_w, y, dx_w, 64, f"{letter.upper()}.", key, claim.get(key, ""))

    # Service line table (box 24)
    y += 84
    cols = [("24a. Dates of Service", "date_from", 240), ("To", "date_to", 240),
            ("B. POS", "place_of_service", 110), ("D. CPT/HCPCS", "cpt_code", 210),
            ("E. Dx Ptr", "diagnosis_pointer", 120), ("F. $ Charges", "charges", 220),
            ("G. Units", "units", 110), ("J. Rendering NPI", "rendering_npi", 320)]
    x = MARGIN
    for title_, _, w in cols:
        box(x, y, w, 40, title_)
        x += w
    y += 40
    for i, line in enumerate(claim["service_lines"], start=1):
        x = MARGIN
        for _, key, w in cols:
            box(x, y, w, 60, "", f"line{i}_{key}", line[key], vfont=f_small)
            x += w
        y += 60

    # Bottom block
    y += 24
    box(MARGIN, y, 360, 70, "25. Federal Tax I.D.", "federal_tax_id", claim["federal_tax_id"])
    box(MARGIN + 370, y, 360, 70, "26. Patient's Account No.",
        "patient_account_no", claim["patient_account_no"])
    box(MARGIN + 740, y, 280, 70, "28. Total Charge", "total_charge", claim["total_charge"])
    box(MARGIN + 1030, y, 280, 70, "29. Amount Paid", "amount_paid", claim["amount_paid"])
    box(MARGIN + 1320, y, W - 2 * MARGIN - 1320, 70, "17b. Referring NPI",
        "referring_provider_npi", claim["referring_provider_npi"])

    y += 80
    box(MARGIN, y, 730, 70, "33. Billing Provider",
        "billing_provider_name", claim["billing_provider_name"])
    box(MARGIN + 740, y, 570, 70, "33a. Billing NPI",
        "billing_provider_npi", claim["billing_provider_npi"])

    return img, bboxes
