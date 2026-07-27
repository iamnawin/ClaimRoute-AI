"""Day 5 tests: template completeness, spine end-to-end, provenance, ledger."""
import json
import re
from pathlib import Path

from PIL import Image

from engine.extract import run_page
from engine.ledger import CostLedger
from engine.layout.mapper import load_template
from engine.schemas import AUTOMATED_STATES


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def test_templates_cover_all_variant_fields():
    assert len(load_template("cms1500", 3)["fields"]) >= 44
    assert len(load_template("ub04", 3)["fields"]) >= 32


def test_spine_end_to_end_clean_page(tmp_path):
    led = CostLedger(tmp_path / "l.jsonl")
    doc = "cms1500_42_0000"
    img = Image.open(f"data/generated/cms1500/clean/images/{doc}.png")
    gt = json.loads(Path(f"data/generated/cms1500/clean/ground_truth/{doc}.json").read_text())
    page = run_page(img, doc, led)
    assert page.doc_type == "cms1500"
    ok = sum(norm(page.fields[k].value) == norm(v["value"])
             for k, v in gt["fields"].items() if k in page.fields)
    assert ok / len(gt["fields"]) >= 0.9
    # provenance + automated-state discipline
    fr = next(iter(page.fields.values()))
    assert fr.attempts and fr.attempts[0].rung == "primary_ocr"
    # Since Day 7 the governor assigns the state; it must be an automated one,
    # and every field must carry a recorded, human-readable decision trail.
    assert fr.state in AUTOMATED_STATES
    assert page.decisions[fr.field_name][0][1]
    # every stage logged to the ledger
    ops = {e["operation"] for e in led.entries()}
    assert {"preprocess", "route", "ocr_paddle"} <= ops
