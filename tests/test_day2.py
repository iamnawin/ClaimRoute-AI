"""Day 2 tests: UB-04 integrity, degradation determinism, bbox-drift guardrail,
split integrity, frozen-manifest stability."""
import hashlib
import json
import random

import pytest
from PIL import Image

from data_factory.generator import validate_npi
from data_factory.generator_ub04 import generate_ub04, flatten_ub04
from data_factory.render_ub04 import render as render_ub04
from data_factory.render_cms1500 import render as render_cms1500
from data_factory.generator import generate_claim
from data_factory.degrade import degrade, rotate_with_bboxes, check_bbox_ink
from data_factory.make_dataset import build, split_claims, TIERS


def test_ub04_arithmetic_and_npis():
    claim = generate_ub04(99)
    total = sum(round(float(l["charges"]) * 100) for l in claim["revenue_lines"])
    assert claim["total_charges"] == f"{total // 100}.{total % 100:02d}"
    assert validate_npi(claim["provider_npi"]) and validate_npi(claim["attending_npi"])


def test_ub04_deterministic():
    assert generate_ub04(7) == generate_ub04(7)
    assert flatten_ub04(generate_ub04(7)) != flatten_ub04(generate_ub04(8))


def test_ub04_render_covers_all_fields():
    claim = generate_ub04(3)
    _, bboxes = render_ub04(claim)
    flat = flatten_ub04(claim)
    missing = [k for k, v in flat.items() if v and k not in bboxes]
    assert not missing, f"fields rendered without bbox: {missing}"


def test_degradation_deterministic():
    claim = generate_claim(11)
    img, bb = render_cms1500(claim)
    a, bba, _ = degrade(img, bb, "ugly", seed=1234)
    b, bbb, _ = degrade(img, bb, "ugly", seed=1234)
    assert hashlib.sha256(a.tobytes()).digest() == hashlib.sha256(b.tobytes()).digest()
    assert bba == bbb
    c, _, _ = degrade(img, bb, "ugly", seed=1235)
    assert hashlib.sha256(c.tobytes()).digest() != hashlib.sha256(a.tobytes()).digest()


@pytest.mark.parametrize("angle", [-11.0, -5.0, 4.0, 12.0])
def test_rotation_bboxes_still_cover_ink(angle):
    """The silent-assassin guardrail: after rotation, every transformed bbox
    must still contain the dark value ink it originally covered."""
    claim = generate_claim(21)
    img, bb = render_cms1500(claim)
    out, bb2 = rotate_with_bboxes(img, bb, angle)
    failures = check_bbox_ink(out, bb2, sample=0)
    assert not failures, f"bbox drift at angle {angle}: {failures}"


def test_all_tiers_pass_ink_guardrail():
    claim = generate_ub04(33)
    img, bb = render_ub04(claim)
    for tier in TIERS:
        out, bb2, _ = degrade(img, bb, tier, seed=777)
        assert not check_bbox_ink(out, bb2, sample=0), f"drift in tier {tier}"


def test_split_claim_level_no_overlap_and_frozen_hash_stable():
    manifest = {"docs": [{"doc_id": f"cms1500_1_{i:04d}", "form": "cms1500", "n_fields": 1}
                         for i in range(20)]
                + [{"doc_id": f"ub04_1_{i:04d}", "form": "ub04", "n_fields": 1}
                   for i in range(20)]}
    s1 = split_claims(manifest, seed=42)
    s2 = split_claims(manifest, seed=42)
    assert s1["test_sha256"] == s2["test_sha256"]          # frozen hash reproducible
    assert not set(s1["calibration"]) & set(s1["test"])     # disjoint
    assert len(s1["calibration"]) == 16 and len(s1["test"]) == 24  # 40/60 stratified


def test_build_small_dataset_end_to_end(tmp_path):
    manifest = build(n_per_form=2, seed=5, out=tmp_path)
    assert len(manifest["docs"]) == 4
    for form in ("cms1500", "ub04"):
        for tier in TIERS:
            imgs = list((tmp_path / form / tier / "images").glob("*.png"))
            gts = list((tmp_path / form / tier / "ground_truth").glob("*.json"))
            assert len(imgs) == 2 and len(gts) == 2
    # ugly-tier gt must carry rotation meta and transformed (float) bboxes
    gt = json.loads(next((tmp_path / "cms1500" / "ugly" / "ground_truth").glob("*.json"))
                    .read_text())
    assert "angle_deg" in gt["degradation"]
    assert gt["fields"]["patient_name"]["bbox"] is not None
