"""Day 6: validator coverage on calibration — do the free validators actually
flag the spine's errors, and how often do they cry wolf on correct fields?

    python -m eval.day6_eval --tiers clean ugly     # chunked, resumable
    python -m eval.day6_eval --summarize
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image

from engine.extract import run_page
from engine.ledger import CostLedger
from engine.schemas import Verdict

DATA = Path("data/generated")
ROWS = Path("eval/results/day6_rows.jsonl")
LEDGER = CostLedger("eval/results/day6_ledger.jsonl")


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def run(tiers, limit):
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if ROWS.exists():
        done = {(r["doc_id"], r["tier"]) for r in map(json.loads, ROWS.open())}
    docs = json.loads(Path("eval/splits/split_v1.json").read_text())["calibration"]
    written = 0
    with ROWS.open("a", encoding="utf-8") as fh:
        for doc_id in docs:
            form = doc_id.split("_")[0]
            for tier in tiers:
                if (doc_id, tier) in done:
                    continue
                gt = json.loads((DATA / form / tier / "ground_truth" / f"{doc_id}.json").read_text())
                img = Image.open(DATA / form / tier / "images" / f"{doc_id}.png")
                page = run_page(img, doc_id, LEDGER)
                fields = {}
                for k, v in gt["fields"].items():
                    fr = page.fields.get(k)
                    if fr is None:
                        continue
                    fields[k] = {
                        "correct": norm(fr.value) == norm(v["value"]),
                        "flagged": any(s.verdict == Verdict.FAIL for s in fr.stamps),
                        "has_validators": bool(fr.stamps),
                        "conf": fr.confidence,
                    }
                fh.write(json.dumps({"doc_id": doc_id, "tier": tier,
                                     "fields": fields}) + "\n")
                fh.flush()
                written += 1
                if limit and written >= limit:
                    print(f"chunk done ({written})")
                    return
    print(f"chunk done ({written})")


def summarize():
    rows = [json.loads(l) for l in ROWS.open()]
    agg = defaultdict(lambda: {"err": 0, "err_flagged": 0, "ok": 0, "ok_flagged": 0,
                               "conf_err": [], "conf_ok": []})
    for r in rows:
        for k, f in r["fields"].items():
            if not f["has_validators"]:
                continue
            a = agg[r["tier"]]
            if f["correct"]:
                a["ok"] += 1
                a["ok_flagged"] += f["flagged"]
                a["conf_ok"].append(f["conf"])
            else:
                a["err"] += 1
                a["err_flagged"] += f["flagged"]
                a["conf_err"].append(f["conf"])
    out = {}
    for tier, a in sorted(agg.items()):
        out[tier] = {
            "errors": a["err"],
            "validator_catch_rate": round(a["err_flagged"] / a["err"], 4) if a["err"] else None,
            "false_alarm_rate": round(a["ok_flagged"] / a["ok"], 4) if a["ok"] else None,
            "mean_conf_correct": round(sum(a["conf_ok"]) / len(a["conf_ok"]), 3),
            "mean_conf_errors": round(sum(a["conf_err"]) / len(a["conf_err"]), 3) if a["conf_err"] else None,
            "validated_fields": a["ok"] + a["err"],
        }
    report = {"validator_coverage": out,
              "note": "catch = spine error with >=1 FAIL stamp; false alarm = "
                      "correct field with a FAIL stamp; calibration split"}
    Path("eval/results/day6_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", nargs="*", default=["clean", "ugly"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--summarize", action="store_true")
    args = ap.parse_args()
    summarize() if args.summarize else run(args.tiers, args.limit)
