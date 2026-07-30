"""Day 8 selective field-crop escalation evaluation.

Uses the synthetic calibration split only. The default ``offline-oracle`` is a
deterministic test double: its cost is projected, never measured API spend.

    python -m eval.day8_escalation --tiers clean --limit 2
    python -m eval.day8_escalation --tiers clean noisy ugly
    python -m eval.day8_escalation --tiers clean noisy ugly --summarize
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image

from engine.cropper import crop_field
from engine.escalate import escalate_field
from engine.extract import run_page
from engine.governor import apply, field_policy
from engine.ledger import CostLedger
from engine.preprocess import preprocess_page
from engine.router import route
from engine.schemas import Attempt, FieldResult, FieldState

DATA = Path("data/generated")
SPLIT = Path("eval/splits/split_v1.json")
RESULTS = Path("eval/results")
ROWS = RESULTS / "day8_escalation_rows.jsonl"
PAGES = RESULTS / "day8_escalation_pages.jsonl"
LEDGER_PATH = RESULTS / "day8_escalation_ledger.jsonl"
SUMMARY_JSON = RESULTS / "day8_escalation_summary.json"
SUMMARY_CSV = RESULTS / "day8_escalation_summary.csv"
TIERS = ("clean", "noisy", "ugly")
TERMINAL = {FieldState.ACCEPT.value, FieldState.ACCEPT_WITH_FLAG.value}

_PRICES = yaml.safe_load(Path("configs/prices.yaml").read_text())


def norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", nargs="+", choices=TIERS, default=list(TIERS))
    parser.add_argument("--limit", type=int, default=0,
                        help="maximum unfinished document-tier pages to process")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--provider", default="offline-oracle",
                        help="approved engine model (default: offline-oracle)")
    return parser


def provider_details(model: str) -> tuple[str, str]:
    if model == "offline-oracle":
        return "offline-oracle", "oracle"
    if model.startswith("gpt-"):
        return "openai", "live"
    if model.startswith("gemini-"):
        return "gemini", "live"
    return model, "live"


def run_id_for(model: str) -> str:
    return f"day8-calibration-{model}"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append_once(path: Path, record: dict, key_fields: tuple[str, ...],
                seen: set[tuple]) -> bool:
    key = tuple(record.get(field) for field in key_fields)
    if key in seen:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
    seen.add(key)
    return True


def iter_targets(docs: list[str], tiers: list[str], completed: set[tuple],
                 model: str, limit: int = 0):
    yielded = 0
    for doc_id in docs:
        for tier in tiers:
            if (doc_id, tier, model) in completed:
                continue
            if limit and yielded >= limit:
                return
            yield doc_id, tier
            yielded += 1


def _attempt(fr: FieldResult, rung: str):
    return next((attempt for attempt in fr.attempts if attempt.rung == rung), None)


def _call_meta(entries: list[dict], model: str) -> dict:
    operation = f"escalate_{model}"
    return next((entry.get("meta", {}) for entry in reversed(entries)
                 if entry.get("operation") == operation), {})


def cost_columns(model: str, call_meta: dict, attempt: Attempt | None) -> dict:
    """Keep measured live spend and oracle projection in disjoint columns."""
    _, mode = provider_details(model)
    total = float(attempt.cost_usd if attempt else 0.0)
    input_tokens = call_meta.get("input_tokens")
    output_tokens = call_meta.get("output_tokens")
    cached = bool(call_meta.get("cached"))
    if mode == "oracle":
        return {
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "total_api_cost_usd": 0.0,
            "projected_cost_usd": total,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "image_tokens": call_meta.get("image_tokens"),
        }

    prices = _PRICES["vision_models"].get(model, {})
    input_cost = 0.0 if cached or input_tokens is None else input_tokens / 1e6 * prices.get("input", 0)
    output_cost = 0.0 if cached or output_tokens is None else output_tokens / 1e6 * prices.get("output", 0)
    return {
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_api_cost_usd": total,
        "projected_cost_usd": 0.0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "image_tokens": call_meta.get("image_tokens"),
    }


def execute_escalation(fr: FieldResult, img, form: str, variant: int,
                       page_values: dict, quality: float, ledger: CostLedger,
                       model: str, tier: str) -> tuple[dict, str | None, list[dict]]:
    """Run one existing escalation transaction, then re-enter the governor."""
    before = len(ledger.entries())
    error = None
    try:
        rec = escalate_field(fr, img, form, variant, page_values, quality,
                             ledger, model, tier=tier, synthetic=True)
    except Exception as exc:  # provider construction/call must become a row, not abort the run
        error = f"{type(exc).__name__}: {exc}"
        fr.attempts.append(Attempt(rung="multimodal", engine=model, value=None,
                                   confidence=0.0, cost_usd=0.0, latency_ms=0.0))
        rec = {"field": fr.field_name, "model": model, "escalated": True,
               "cost_usd": 0.0, "cached": False, "rejects": [],
               "decision": "provider_error"}
    state, reason = apply(fr)
    rec["final_state"], rec["governor_reason"] = state.value, reason
    return rec, error, ledger.entries()[before:]


def _validation_rows(fr: FieldResult) -> list[dict]:
    return [{"validator": stamp.validator, "verdict": stamp.verdict.value,
             "detail": stamp.detail} for stamp in fr.stamps]


def make_field_row(*, run_id: str, doc_id: str, tier: str, fr: FieldResult,
                   expected: dict | None, model: str, rec: dict,
                   error: str | None, ledger_entries: list[dict], img) -> dict:
    primary = _attempt(fr, "primary_ocr")
    retry = _attempt(fr, "retry_ocr")
    escalation = next((a for a in reversed(fr.attempts)
                       if a.rung == "multimodal"), None)
    meta = _call_meta(ledger_entries, model)
    provider, mode = provider_details(model)
    try:
        crop_size = list(crop_field(img, fr.bbox).size)
    except Exception:
        crop_size = None
    truth = expected.get("value") if expected else None
    correctly = norm(fr.value) == norm(truth) if expected else fr.value in (None, "")
    path = [{"rung": attempt.rung, "engine": attempt.engine,
             "value": attempt.value, "confidence": attempt.confidence}
            for attempt in fr.attempts]
    return {
        "run_id": run_id,
        "document_id": doc_id,
        "tier": tier,
        "page": fr.page_id,
        "field_name": fr.field_name,
        "field_criticality": field_policy(fr.field_name).get("criticality"),
        "ground_truth": truth,
        "primary_candidate": primary.value if primary else None,
        "primary_confidence": primary.confidence if primary else None,
        "retry_candidate": retry.value if retry else None,
        "retry_confidence": retry.confidence if retry else None,
        "escalation_candidate": escalation.value if escalation else None,
        "escalation_confidence": escalation.confidence if escalation else None,
        "final_value": fr.value,
        "final_decision": fr.state.value,
        "resolved_correctly": correctly,
        "provider": provider,
        "model": model,
        "provider_mode": mode,
        **cost_columns(model, meta, escalation),
        "latency_ms": escalation.latency_ms if escalation else 0.0,
        "crop_dimensions": crop_size,
        "validation_results": _validation_rows(fr),
        "grounding_rejections": rec.get("rejects", []),
        "escalation_decision": rec.get("decision", ""),
        "cache_hit": bool(rec.get("cached")),
        "processing_path": path,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run(tiers: list[str], limit: int, model: str) -> int:
    run_id = run_id_for(model)
    docs = json.loads(SPLIT.read_text())["calibration"]
    existing_rows = read_jsonl(ROWS)
    existing_pages = read_jsonl(PAGES)
    row_keys = {(r["run_id"], r["document_id"], r["tier"], r["page"],
                 r["field_name"]) for r in existing_rows}
    page_keys = {(p["document_id"], p["tier"], p["model"])
                 for p in existing_pages}
    completed = set(page_keys)
    ledger = CostLedger(LEDGER_PATH)
    written_pages = 0

    for doc_id, tier in iter_targets(docs, tiers, completed, model, limit):
        form = doc_id.split("_")[0]
        gt_path = DATA / form / tier / "ground_truth" / f"{doc_id}.json"
        image_path = DATA / form / tier / "images" / f"{doc_id}.png"
        gt = json.loads(gt_path.read_text())
        img = Image.open(image_path)
        ledger_before = len(ledger.entries())
        page = run_page(img, doc_id, ledger, run_escalate=False, tier=tier)
        local_entries = ledger.entries()[ledger_before:]
        local_cost = sum(e["cost_usd"] for e in local_entries)
        local_latency = sum(e["latency_ms"] for e in local_entries)
        # Recreate the spine's processed coordinate space for the actual crop.
        # This is deterministic and deliberately excluded from cost evidence:
        # production run_page already performed and logged the same preprocessing.
        work = preprocess_page(img)["processed"]
        routing = route(work)

        primary_resolved = sum(decisions[0][0] in TERMINAL
                               for decisions in page.decisions.values())
        retry_routed = sum(decisions[0][0] == FieldState.RETRY.value
                           for decisions in page.decisions.values())
        escalated = [fr for fr in page.fields.values()
                     if fr.state == FieldState.ESCALATE]
        retry_resolved = sum(fr.attempts_used("retry_ocr") > 0 and
                             fr.state.value in TERMINAL for fr in page.fields.values())

        for fr in escalated:
            rec, error, entries = execute_escalation(
                fr, work, page.doc_type, routing["variant"],
                {k: v.value for k, v in page.fields.items()},
                page.quality_score, ledger, model, tier)
            page.escalations[fr.field_name] = rec
            page.decisions[fr.field_name].append(
                (rec["final_state"], rec["governor_reason"]))
            row = make_field_row(
                run_id=run_id, doc_id=doc_id, tier=tier, fr=fr,
                expected=gt["fields"].get(fr.field_name), model=model,
                rec=rec, error=error, ledger_entries=entries, img=work)
            append_once(ROWS, row,
                        ("run_id", "document_id", "tier", "page", "field_name"),
                        row_keys)

        correct = 0
        critical_correct = 0
        critical_total = 0
        for name, fr in page.fields.items():
            expected = gt["fields"].get(name)
            is_correct = (norm(fr.value) == norm(expected["value"])) if expected else fr.value in (None, "")
            correct += is_correct
            if field_policy(name).get("criticality") == "high":
                critical_total += 1
                critical_correct += is_correct

        page_record = {
            "run_id": run_id, "document_id": doc_id, "tier": tier,
            "page": page.page_id, "model": model,
            "total_fields": len(page.fields),
            "primary_resolved_fields": primary_resolved,
            "retry_routed_fields": retry_routed,
            "retry_resolved_fields": retry_resolved,
            "escalated_fields": len(escalated),
            "correct_fields": correct,
            "critical_fields": critical_total,
            "critical_correct_fields": critical_correct,
            "human_review_fields": sum(fr.state == FieldState.HUMAN_REVIEW
                                       for fr in page.fields.values()),
            "unresolved_fields": sum(fr.state.value not in TERMINAL
                                     for fr in page.fields.values()),
            "local_cost_usd": local_cost,
            "local_latency_ms": local_latency,
            "total_latency_ms": local_latency + sum(
                a.latency_ms for fr in escalated for a in fr.attempts
                if a.rung == "multimodal"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        append_once(PAGES, page_record, ("run_id", "document_id", "tier", "page"),
                    {(p["run_id"], p["document_id"], p["tier"], p["page"])
                     for p in existing_pages})
        existing_pages.append(page_record)
        written_pages += 1
        print(f"completed {doc_id}/{tier}: {len(escalated)} escalated fields")
    print(f"chunk done ({written_pages} pages)")
    return written_pages


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def aggregate(page_rows: list[dict], field_rows: list[dict]) -> dict:
    pages = len(page_rows)
    fields = sum(row["total_fields"] for row in page_rows)
    escalated = sum(row["escalated_fields"] for row in page_rows)
    resolved_escalated = sum(row["final_decision"] in TERMINAL for row in field_rows)
    correct_escalated = sum(bool(row["resolved_correctly"]) and
                            row["final_decision"] in TERMINAL for row in field_rows)
    api_cost = sum(row["total_api_cost_usd"] for row in field_rows)
    projected = sum(row["projected_cost_usd"] for row in field_rows)
    failures = Counter(row["field_name"] for row in field_rows
                       if not row["resolved_correctly"] or
                       row["final_decision"] not in TERMINAL)
    latency_ms = sum(row["total_latency_ms"] for row in page_rows)
    return {
        "documents_processed": len({row["document_id"] for row in page_rows}),
        "pages_processed": pages,
        "fields_processed": fields,
        "primary_resolution_rate": _ratio(sum(r["primary_resolved_fields"] for r in page_rows), fields),
        "retry_routing_rate": _ratio(sum(r["retry_routed_fields"] for r in page_rows), fields),
        "retry_resolution_rate": _ratio(sum(r["retry_resolved_fields"] for r in page_rows),
                                        sum(r["retry_routed_fields"] for r in page_rows)),
        "escalation_rate": _ratio(escalated, fields),
        "escalation_resolution_rate": _ratio(resolved_escalated, escalated),
        "grounding_rejection_rate": _ratio(
            sum(bool(r.get("grounding_rejections")) for r in field_rows), escalated),
        "cache_hit_rate": _ratio(sum(bool(r.get("cache_hit")) for r in field_rows), escalated),
        "unresolved_rate": _ratio(sum(r["unresolved_fields"] for r in page_rows), fields),
        "human_review_rate": _ratio(sum(r["human_review_fields"] for r in page_rows), fields),
        "field_accuracy": _ratio(sum(r["correct_fields"] for r in page_rows), fields),
        "critical_field_accuracy": _ratio(sum(r["critical_correct_fields"] for r in page_rows),
                                          sum(r["critical_fields"] for r in page_rows)),
        "average_latency_per_page_ms": _ratio(latency_ms, pages),
        "throughput_pages_per_minute": _ratio(pages * 60000, latency_ms),
        "local_cost_per_page_usd": _ratio(sum(r["local_cost_usd"] for r in page_rows), pages),
        "api_cost_per_page_usd": _ratio(api_cost, pages),
        "projected_api_cost_per_page_usd": _ratio(projected, pages),
        "total_automated_cost_per_page_usd": _ratio(
            sum(r["local_cost_usd"] for r in page_rows) + api_cost, pages),
        "projected_total_automated_cost_per_page_usd": _ratio(
            sum(r["local_cost_usd"] for r in page_rows) + projected, pages),
        "cost_per_correctly_resolved_escalated_field_usd": _ratio(api_cost, correct_escalated),
        "projected_cost_per_correctly_resolved_escalated_field_usd": _ratio(projected, correct_escalated),
        "failures_by_field_type": dict(sorted(failures.items())),
    }


def summarize(tiers: list[str], model: str) -> dict:
    run_id = run_id_for(model)
    pages = [row for row in read_jsonl(PAGES)
             if row.get("run_id") == run_id and row["tier"] in tiers]
    fields = [row for row in read_jsonl(ROWS)
              if row.get("run_id") == run_id and row["tier"] in tiers]
    per_tier = {}
    for tier in tiers:
        tier_pages = [row for row in pages if row["tier"] == tier]
        tier_fields = [row for row in fields if row["tier"] == tier]
        if tier_pages:
            per_tier[tier] = aggregate(tier_pages, tier_fields)

    expected_docs = set(json.loads(SPLIT.read_text())["calibration"])
    completed = {(row["document_id"], row["tier"]) for row in pages}
    expected = {(doc_id, tier) for doc_id in expected_docs for tier in tiers}
    complete = expected.issubset(completed)
    report = {
        "run_id": run_id,
        "provider": provider_details(model)[0],
        "model": model,
        "provider_mode": provider_details(model)[1],
        "selected_tiers": tiers,
        "selected_tiers_complete": complete,
        "per_tier": per_tier,
        "blended": aggregate(pages, fields) if complete else None,
        "cost_note": ("offline-oracle costs are projected; measured API cost is zero"
                      if model == "offline-oracle" else
                      "live provider API costs are measured from returned usage"),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as fh:
        metric_names = sorted({metric for values in per_tier.values()
                               for metric in values if metric != "failures_by_field_type"})
        writer = csv.DictWriter(fh, fieldnames=["scope", *metric_names])
        writer.writeheader()
        for scope, values in per_tier.items():
            writer.writerow({"scope": scope, **{
                key: value for key, value in values.items()
                if key != "failures_by_field_type"}})
        if report["blended"]:
            writer.writerow({"scope": "blended", **{
                key: value for key, value in report["blended"].items()
                if key != "failures_by_field_type"}})
    print(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    summarize(args.tiers, args.provider) if args.summarize else run(
        args.tiers, args.limit, args.provider)


if __name__ == "__main__":
    main()
