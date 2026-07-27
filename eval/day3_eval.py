"""Day 3 evaluation over the generated dataset: preprocessing integrity,
quality bands, router accuracy. Chunkable (--forms/--tiers) for short shells.

    python -m eval.day3_eval --tiers clean noisy       # appends rows
    python -m eval.day3_eval --summarize               # report from rows
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image

from data_factory.degrade import check_bbox_ink
from engine.preprocess import preprocess_page, transform_bboxes
from engine.router import route

DATA = Path("data/generated")
ROWS = Path("eval/results/day3_rows.jsonl")


def run(forms: list[str], tiers: list[str], limit: int = 0) -> None:
    written = 0
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if ROWS.exists():
        done = {(r["doc_id"], r["tier"]) for r in map(json.loads, ROWS.open())}
    with ROWS.open("a", encoding="utf-8") as fh:
        for form in forms:
            for tier in tiers:
                for gt_path in sorted((DATA / form / tier / "ground_truth").glob("*.json")):
                    gt = json.loads(gt_path.read_text())
                    if (gt["doc_id"], tier) in done:
                        continue
                    img = Image.open(DATA / form / tier / "images" / f"{gt['doc_id']}.png")
                    t0 = time.perf_counter()
                    res = preprocess_page(img)
                    bb = {k: v["bbox"] for k, v in gt["fields"].items()}
                    bb_proc = transform_bboxes(bb, res["transform_history"])
                    ink_fail = check_bbox_ink(res["processed"], bb_proc, sample=0)
                    r = route(res["processed"])
                    fh.write(json.dumps({
                        "doc_id": gt["doc_id"], "form": form, "tier": tier,
                        "routed": r["document_type"], "route_conf": r["confidence"],
                        "ops": [s["operation"] for s in res["transform_history"]],
                        "q_before": res["quality_before"]["quality_score"],
                        "q_after": res["quality_after"]["quality_score"],
                        "band_before": res["quality_before"]["quality_band"],
                        "ink_failures": ink_fail,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                    }) + "\n")
                    fh.flush()          # survive hard-killed shells
                    written += 1
                    if limit and written >= limit:
                        print(f"chunk done ({written} rows, limit)")
                        return
    print(f"chunk done ({written} rows)")


def summarize() -> None:
    rows = [json.loads(l) for l in ROWS.open()]
    n = len(rows)
    router_ok = sum(r["routed"] == r["form"] for r in rows)
    ink_bad = [r for r in rows if r["ink_failures"]]
    clean_touched = [r for r in rows if r["tier"] == "clean" and r["ops"]]
    q = defaultdict(lambda: {"before": [], "after": []})
    for r in rows:
        q[r["tier"]]["before"].append(r["q_before"])
        q[r["tier"]]["after"].append(r["q_after"])
    report = {
        "pages": n,
        "router_accuracy": round(router_ok / n, 4),
        "router_errors": [{"doc": r["doc_id"], "tier": r["tier"], "routed": r["routed"]}
                          for r in rows if r["routed"] != r["form"]],
        "bbox_ink_failures": len(ink_bad),
        "clean_pages_modified": len(clean_touched),
        "quality_mean": {t: {"before": round(sum(v["before"]) / len(v["before"]), 3),
                             "after": round(sum(v["after"]) / len(v["after"]), 3)}
                         for t, v in sorted(q.items())},
        "mean_ms_per_page": round(sum(r["ms"] for r in rows) / n, 1),
    }
    out = Path("eval/results/day3_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--forms", nargs="*", default=["cms1500", "ub04"])
    ap.add_argument("--tiers", nargs="*", default=["clean", "noisy", "ugly"])
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    summarize() if args.summarize else run(args.forms, args.tiers, args.limit)
