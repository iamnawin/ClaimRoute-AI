"""Day 3 tests: skew recovery, bbox survival through preprocessing, clean-page
non-degradation, quality ordering, router accuracy + evidence."""
import numpy as np
from PIL import Image

from data_factory.generator import generate_claim
from data_factory.generator_ub04 import generate_ub04
from data_factory.render_cms1500 import render as render_cms1500
from data_factory.render_ub04 import render as render_ub04
from data_factory.degrade import degrade, rotate_with_bboxes, check_bbox_ink
from engine.preprocess import preprocess_page, transform_bboxes, estimate_skew
from engine.router import route


def test_skew_estimate_recovers_known_rotation():
    img, _ = render_cms1500(generate_claim(60))
    for true_angle in (-9.0, -4.5, 5.0, 11.0):
        rot, _ = rotate_with_bboxes(img, {}, true_angle)
        est = estimate_skew(rot)
        assert abs(est + true_angle) <= 0.7, f"true {true_angle}, est {est}"


def test_bboxes_survive_preprocessing_on_ugly():
    claim = generate_ub04(61)
    img, bb = render_ub04(claim)
    ugly, bb_ugly, _ = degrade(img, bb, "ugly", seed=99)
    res = preprocess_page(ugly)
    bb_proc = transform_bboxes(bb_ugly, res["transform_history"])
    failures = check_bbox_ink(res["processed"], bb_proc, sample=0)
    assert not failures, f"bbox drift after preprocessing: {failures}"


def test_clean_pages_pass_through_untouched():
    img, _ = render_cms1500(generate_claim(62))
    res = preprocess_page(img)
    assert res["transform_history"] == [], "clean page must not be 'improved'"
    assert np.array_equal(np.asarray(res["processed"]), np.asarray(img))


def test_quality_ordering_and_structure():
    claim = generate_claim(63)
    img, bb = render_cms1500(claim)
    q = {}
    for tier in ("clean", "noisy", "ugly"):
        d, _, _ = degrade(img, bb, tier, seed=5)
        q[tier] = preprocess_page(d)["quality_before"]
    assert q["clean"]["quality_score"] > q["noisy"]["quality_score"] > q["ugly"]["quality_score"]
    assert set(q["ugly"]["signals"]) == {"blur", "contrast", "noise",
                                         "skew_degrees", "text_density"}
    assert q["clean"]["quality_band"] == "good"


def test_preprocessing_measurably_repairs_ugly_pages():
    """Assert the REAL measurable repairs: skew residual collapses and (when the
    shadow gate fires) the paper white point is restored. The composite quality
    score is a scan-condition signal for routing, NOT a processing-benefit
    metric — resampling lowers its blur term even as geometry is fixed. The
    accuracy value of preprocessing is proven by the Day-4 OCR ablation.
    (See docs/assumptions.md decision #6.)"""
    import numpy as np
    from engine.preprocess import _gray
    for i in range(5):
        img, bb = render_ub04(generate_ub04(64 + i))
        ugly, _, meta = degrade(img, bb, "ugly", seed=6 + i)
        res = preprocess_page(ugly)
        ops = [s["operation"] for s in res["transform_history"]]
        assert "rotate" in ops
        residual = abs(res["quality_after"]["signals"]["skew_degrees"])
        assert residual <= 1.0, f"deskew left {residual} deg (true {meta['angle_deg']})"
        if "illumination_flatten" in ops or "contrast_stretch" in ops:
            white = float(np.percentile(_gray(res["processed"]), 98))
            assert white >= 235, f"white point not restored: {white}"


def test_router_labels_and_evidence():
    c_img, _ = render_cms1500(generate_claim(65))
    u_img, _ = render_ub04(generate_ub04(66))
    r1, r2 = route(c_img), route(u_img)
    assert r1["document_type"] == "cms1500" and r2["document_type"] == "ub04"
    assert r1["confidence"] > 0.85 and r2["confidence"] > 0.85
    assert any("layout-profile" in e for e in r1["evidence"])
    blank = Image.new("RGB", (1700, 2200), (250, 250, 248))
    assert route(blank)["document_type"] == "unstructured"


def test_router_on_preprocessed_ugly():
    img, bb = render_cms1500(generate_claim(67))
    ugly, _, _ = degrade(img, bb, "ugly", seed=7)
    res = preprocess_page(ugly)
    assert route(res["processed"])["document_type"] == "cms1500"
