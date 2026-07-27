"""Generate layout templates from the renderers themselves.

For each (form, line-count variant): render reference claims, express every
field's value bbox in coordinates NORMALIZED to the red-grid extent
(engine.router.form_extent). Union over seeds so optional fields (dx b-d,
line 3) all acquire a region. Templates are committed JSON — data, not code.

    python -m engine.layout.build_templates
"""
from __future__ import annotations

import json
from pathlib import Path

from data_factory.generator import generate_claim, flatten_ground_truth
from data_factory.render_cms1500 import render as r1500
from data_factory.generator_ub04 import generate_ub04, flatten_ub04
from data_factory.render_ub04 import render as rub
from engine.router import form_extent

OUT = Path(__file__).parent / "templates"
FORMS = {
    "cms1500": (generate_claim, flatten_ground_truth, r1500, "service_lines", (1, 2, 3)),
    "ub04": (generate_ub04, flatten_ub04, rub, "revenue_lines", (2, 3)),
}


def norm_region(bbox, ext):
    x0, y0, x1, y1 = ext
    w, h = x1 - x0, y1 - y0
    return [round((bbox[0] - x0) / w, 4), round((bbox[1] - y0) / h, 4),
            round((bbox[2] - x0) / w, 4), round((bbox[3] - y0) / h, 4)]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for form, (gen, flatten, render, line_key, variants) in FORMS.items():
        for n in variants:
            fields: dict = {}
            stale = 0
            for seed in range(400):
                claim = gen(seed)
                if len(claim[line_key]) != n:
                    continue
                flat = flatten(claim)
                img, bboxes = render(claim)
                ext = form_extent(img)
                grew = False
                for k, v in flat.items():
                    if v and k in bboxes and k not in fields:
                        fields[k] = norm_region(bboxes[k], ext)
                        grew = True
                stale = 0 if grew else stale + 1
                if stale >= 20:        # union converged: no new fields in 20 renders
                    break
            path = OUT / f"{form}_v{n}.json"
            path.write_text(json.dumps(
                {"form": form, "variant": n, "coord_frame": "red-grid extent",
                 "fields": fields}, indent=2), encoding="utf-8")
            print(f"{path.name}: {len(fields)} field regions")


if __name__ == "__main__":
    main()
