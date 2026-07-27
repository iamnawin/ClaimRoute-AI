"""Day 5 spine evaluation on the calibration split, chunked + resumable.

    python -m eval.day5_eval                  # prep on (default), repeat until done
    python -m eval.day5_eval --no-prep        # ablation arm (decision #6)
    python -m eval.day5_eval --summarize
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

DATA = Path("data/generated")
ROWS = Path("eval/results/day5_rows.jsonl")
LEDGER = CostLedger("eval/results/day5_ledger.jsonl")
TIERS = ["clean", "noisy", "ugly"]


def norm(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def run(prep: bool, limit: int, tiers=None) -> None:
    tiers = tiers or TIERS
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if ROWS.exists():
        done = {(r["doc_id"], r["tier"], r["prep"]) for r in map(json.loads, ROWS.open())}
    docs = json.loads(Path("eval/splits/split_v1.json").read_text())["calibration"]
    written = 0
    with ROWS.open("a", encoding="utf-8") as fh:
        for doc_id in docs:
            form = doc_id.split("_")[0]
            for tier in tiers:
                if (doc_id, tier, prep) in done:
                    continue
                gt = json.loads((DATA / form / tier / "ground_truth" / f"{doc_id}.json")
                                .read_text())
                img = Image.open(DATA / form / tier / "images" / f"{doc_id}.png")
                page = run_page(img, doc_id, LEDGER, prep=prep)
                per = {}
                for k, v in gt["fields"].items():
                    got = page.fields.get(k)
                    per[k] = norm(got.value if got else "") == norm(v["value"])
                fh.write(json.dumps({
                    "doc_id": doc_id, "form": form, "tier": tier, "prep": prep,
                    "routed": page.doc_type, "acc": round(sum(per.values()) / len(per), 4),
                    "per_field": per,
                }) + "\n")
                fh.flush()
                written += 1
                if limit and written >= limit:
                    print(f"chunk done ({written})")
                    return
    print(f"chunk done ({written})")


def summarize() -> None:
    rows = [json.loads(l) for l in ROWS.open()]
    agg = defaultdict(list)
    for r in rows:
        agg[(r["prep"], r["tier"])].append(r["acc"])
    out = {f"{'prep' if p else 'raw'}|{t}":
           {"field_acc": round(sum(v) / len(v), 4), "pages": len(v)}
           for (p, t), v in sorted(agg.items())}
    # field-level worst offenders (prep arm) for Day-6 validator targeting
    misses = defaultdict(int)
    for r in rows:
        if r["prep"]:
            for f, ok in r["per_field"].items():
                if not ok:
                    misses[f] += 1
    report = {"spine_field_acc": out,
              "top_missed_fields_prep": dict(sorted(misses.items(),
                                                    key=lambda kv: -kv[1])[:12]),
              "note": "calibration split; primary=paddle; mapper=overlap-based"}
    Path("eval/results/day5_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-prep", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tiers", nargs="*", default=None)
    ap.add_argument("--summarize", action="store_true")
    args = ap.parse_args()
    summarize() if args.summarize else run(not args.no_prep, args.limit, args.tiers)
