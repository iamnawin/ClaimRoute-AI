"""Day 7 — resolution funnel on the calibration split.

Answers the question the architecture exists to answer: how many fields does
each rung resolve, and how many errors does the local-compute retry rung fix
BEFORE any paid model call?

    python -m eval.day7_funnel --tiers clean         # chunked, resumable
    python -m eval.day7_funnel --summarize
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
from engine.schemas import FieldState

DATA = Path("data/generated")
ROWS = Path("eval/results/day7_rows.jsonl")
LEDGER = CostLedger("eval/results/day7_ledger.jsonl")


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def run(tiers, limit, retry_on: bool):
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if ROWS.exists():
        done = {(r["doc_id"], r["tier"], r["retry"]) for r in map(json.loads, ROWS.open())}
    docs = json.loads(Path("eval/splits/split_v1.json").read_text())["calibration"]
    written = 0
    with ROWS.open("a", encoding="utf-8") as fh:
        for doc_id in docs:
            form = doc_id.split("_")[0]
            for tier in tiers:
                if (doc_id, tier, retry_on) in done:
                    continue
                gt = json.loads((DATA / form / tier / "ground_truth" / f"{doc_id}.json").read_text())
                img = Image.open(DATA / form / tier / "images" / f"{doc_id}.png")
                page = run_page(img, doc_id, LEDGER, run_retry=retry_on)
                fields = {}
                for name, fr in page.fields.items():
                    expected = gt["fields"].get(name)
                    retried = fr.attempts_used("retry_ocr") > 0
                    fields[name] = {
                        "state": fr.state.value,
                        "first_state": page.decisions[name][0][0],
                        "retried": retried,
                        "correct": (norm(fr.value) == norm(expected["value"]))
                                   if expected else (fr.value in (None, "")),
                        "in_gt": expected is not None,
                        "conf": fr.confidence,
                        "retry_cost": sum(a.cost_usd for a in fr.attempts
                                          if a.rung == "retry_ocr"),
                    }
                fh.write(json.dumps({"doc_id": doc_id, "tier": tier,
                                     "retry": retry_on, "fields": fields}) + "\n")
                fh.flush()
                written += 1
                if limit and written >= limit:
                    print(f"chunk done ({written})")
                    return
    print(f"chunk done ({written})")


def summarize():
    rows = [json.loads(l) for l in ROWS.open()]
    out = {}
    for retry_on in (True, False):
        sel = [r for r in rows if r["retry"] is retry_on]
        if not sel:
            continue
        per_tier = defaultdict(lambda: defaultdict(int))
        totals = defaultdict(int)
        retry_cost, retried_n, retry_fixed, retry_broke = 0.0, 0, 0, 0
        for r in sel:
            t = r["tier"]
            for name, f in r["fields"].items():
                per_tier[t][f["state"]] += 1
                totals[f["state"]] += 1
                per_tier[t]["_n"] += 1
                totals["_n"] += 1
                totals["_correct"] += f["correct"]
                per_tier[t]["_correct"] += f["correct"]
                if f["retried"]:
                    retried_n += 1
                    retry_cost += f["retry_cost"]
                    # first_state RETRY means primary was not acceptable
                    if f["correct"] and f["state"] in ("ACCEPT", "ACCEPT_WITH_FLAG"):
                        retry_fixed += 1
                    elif not f["correct"]:
                        retry_broke += 1
        key = "retry_on" if retry_on else "retry_off"
        out[key] = {
            "fields": totals["_n"],
            "accuracy": round(totals["_correct"] / totals["_n"], 4),
            "funnel_pct": {s: round(totals[s] / totals["_n"] * 100, 2)
                           for s in sorted(totals) if not s.startswith("_")},
            "per_tier_accuracy": {t: round(v["_correct"] / v["_n"], 4)
                                  for t, v in sorted(per_tier.items())},
            "retry_rung": {
                "fields_retried": retried_n,
                "retry_pct_of_fields": round(retried_n / totals["_n"] * 100, 2),
                "resolved_after_retry": retry_fixed,
                "still_wrong_after_retry": retry_broke,
                "total_retry_cost_usd": round(retry_cost, 8),
                "mean_retry_cost_per_retried_field_usd": round(
                    retry_cost / retried_n, 10) if retried_n else 0.0,
            },
        }
    # Headline ablation: what the local-compute rung buys before any paid call.
    if "retry_on" in out and "retry_off" in out:
        on, off = out["retry_on"], out["retry_off"]
        would_escalate = off["funnel_pct"].get("RETRY", 0.0)   # unresolved w/o rung
        do_escalate = on["funnel_pct"].get("ESCALATE", 0.0)
        rr = on["retry_rung"]
        out["retry_rung_ablation"] = {
            "fields_needing_more_evidence_pct": would_escalate,
            "fields_still_needing_a_paid_call_pct": do_escalate,
            "escalations_avoided_pct_of_all_fields": round(would_escalate - do_escalate, 2),
            "share_of_would_be_paid_calls_resolved_locally": round(
                rr["resolved_after_retry"] / rr["fields_retried"], 4)
            if rr["fields_retried"] else None,
            "cost_of_avoided_escalation_usd_per_field": rr[
                "mean_retry_cost_per_retried_field_usd"],
            "accuracy_off_vs_on": [off["accuracy"], on["accuracy"]],
        }

    report = {"funnel": out,
              "note": "calibration split only; local compute costed from "
                      "configs/prices.yaml (near-zero incremental, not free); "
                      "ESCALATE means 'would call a paid model' — Tier-2 not "
                      "implemented until Day 8"}
    Path("eval/results/day7_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", nargs="*", default=["clean", "noisy", "ugly"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    args = ap.parse_args()
    summarize() if args.summarize else run(args.tiers, args.limit, not args.no_retry)
