"""Official registration tests use generated ruled forms only."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from engine.layout.official_cms1500_registration import (
    load_official_template, official_field_region, register_official_cms1500,
)
from engine.router import form_extent


def _form(*, stripe: bool = False, broken: bool = False) -> Image.Image:
    page = np.full((1100, 850), 255, dtype=np.uint8)
    if stripe:
        page[:, :7] = 0
        page[:5, :] = 0
    x0, x1, y0, y1 = 35, 815, 120, 1040
    ys = np.array([120, 180, 240, 300, 360, 420, 480, 540, 600,
                   660, 720, 780, 840, 900, 990, 1040])
    for index, y in enumerate(ys):
        if broken and index % 4 == 1:
            cv2.line(page, (x0, y), (390, y), 0, 2)
            cv2.line(page, (410, y), (x1, y), 0, 2)
        else:
            cv2.line(page, (x0, y), (x1, y), 0, 2)
    for top, bottom in zip(ys, ys[1:]):
        for x in (x0, 300, 510, x1):
            cv2.line(page, (x, top + 5), (x, bottom - 5), 0, 2)
    return Image.fromarray(page)


def test_registration_rejects_page_edge_stripes_and_uses_grid_rules():
    result = register_official_cms1500(_form(stripe=True))
    assert result is not None
    assert abs(result.x0 - 35) < 4 and abs(result.x1 - 815) < 4
    assert abs(result.y0 - 120) < 4 and abs(result.y1 - 1040) < 4
    assert "page-edge dark artifact rejected" in result.warnings
    assert result.method == "horizontal-rules+band-local-vertical-rules"


def test_broken_horizontal_rules_remain_registerable():
    result = register_official_cms1500(_form(broken=True))
    assert result is not None and result.confidence >= .75


def test_registration_abstains_without_sufficient_grid_evidence():
    page = Image.new("L", (850, 1100), 255)
    assert register_official_cms1500(page) is None


def test_band_local_vertical_rules_do_not_require_full_height_lines():
    page = _form()
    array = np.asarray(page)
    assert max((array[:, x] < 128).mean() for x in range(array.shape[1])) < .80
    assert register_official_cms1500(page) is not None


def test_official_template_is_separate_from_synthetic_red_extent():
    page = _form()
    assert form_extent(page.convert("RGB")) is None
    assert register_official_cms1500(page) is not None


def test_official_regions_are_bounded_and_have_explicit_padding():
    template = load_official_template()
    assert len(template["fields"]) == 41
    for name, field in template["fields"].items():
        assert len(field["padding_px"]) == 4 and all(p >= 0 for p in field["padding_px"])
        assert all(0 <= value <= 1 for value in field["x_region"])
        assert all(0 <= value <= 1 for value in field["y_region"])
        assert field["x_region"][0] < field["x_region"][1]
        assert field["y_region"][0] < field["y_region"][1]
        x0, y0, x1, y1 = official_field_region(_form(), name)
        assert 0 <= x0 < x1 <= 850 and 0 <= y0 < y1 <= 1100
