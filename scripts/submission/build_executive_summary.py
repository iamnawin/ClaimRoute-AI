"""Generate submission/final/01_Executive_Summary.pdf from committed frozen evidence.

Run:  python scripts/submission/build_executive_summary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evidence import EVIDENCE, NOT_REPORTED  # noqa: E402
from pdf_kit import (  # noqa: E402
    CONTENT_W,
    BarChartFlowable,
    CalloutBox,
    FlowDiagram,
    KeepTogether,
    MetricStrip,
    Rule,
    Spacer,
    build,
    mm,
    para,
    table,
)

OUT = Path(__file__).resolve().parents[2] / "submission" / "final" / "01_Executive_Summary.pdf"


def story() -> list:
    b = EVIDENCE.blended
    counts = EVIDENCE.precision_recall()
    t = EVIDENCE.throughput
    s: list = []

    # -- cover block ---------------------------------------------------------
    s.append(para("ClaimRoute AI", "title"))
    s.append(para("Executive Summary: Datamatics AI Engineering Hackathon 2026", "subtitle"))
    s.append(Rule(CONTENT_W))
    s.append(Spacer(1, 5 * mm))
    s.append(para(
        "<b>ClaimRoute AI is a cost-governed healthcare claims extraction platform in which "
        "every field takes the cheapest reliable path.</b>", "pull"))
    s.append(Spacer(1, 2 * mm))
    s.append(MetricStrip([
        (f"{b['field_accuracy']:.2%}", "Exact field accuracy (frozen synthetic)"),
        (f"{b['critical_field_accuracy']:.2%}", "Critical-field accuracy"),
        (f"${b['projected_total_automated_cost_per_page_usd']:.6f}", "Projected automated cost per page"),
        (f"{b['primary_local_resolution_rate']:.1%}", "Resolved at the cheapest local rung"),
    ], CONTENT_W))
    s.append(Spacer(1, 5 * mm))

    # -- 1 problem -----------------------------------------------------------
    s.append(para("1. Problem Understanding", "h1"))
    s.append(para(
        "Healthcare mailrooms receive millions of scanned pages: CMS-1500 and UB-04 claim forms, "
        "separator sheets, cover pages and supporting attachments. Traditional OCR handles most "
        "boxes well but fails on cramped layouts and degraded scans. Large multimodal models fix "
        "those failures and multiply the cost of every page they touch."))
    s.append(para(
        "<b>The real problem is not extracting text. It is deciding which fields deserve additional "
        "computation.</b> A system that sends every page to a premium model pays for certainty it "
        "already had; a system that never escalates ships errors on precisely the fields that matter "
        "most. At 100 million pages a year, the difference between those two policies is the "
        "difference between a viable product and an unaffordable one."))

    # -- 2 solution ----------------------------------------------------------
    s.append(para("2. Solution Overview", "h1"))
    s.append(para(
        "ClaimRoute processes each page through a ladder of stages ordered cheapest-first. After "
        "every stage the candidate re-enters validation and a Cost Governor, which decides whether "
        "the field is finished or deserves one more, more expensive attempt."))
    s.append(Spacer(1, 1.5 * mm))
    s.append(FlowDiagram([
        "Document intake", "Preprocessing", "Document classification",
        "Primary local OCR", "Layout mapping", "Healthcare validation",
        "Cost Governor", "Local retry", "Selective multimodal escalation",
        "Grounding + revalidation", "Human review", "JSON / CSV output",
    ], CONTENT_W, note="Every retry or model answer returns to validation and the governor before it can be accepted.",
        columns=3))
    s.append(Spacer(1, 3 * mm))
    s.append(para(
        "The governor's automated decisions are ACCEPT, ACCEPT_WITH_FLAG, RETRY, ESCALATE and "
        "HUMAN_REVIEW. A sixth state, ACCEPT_WITH_OVERRIDE, is unreachable from automated code and "
        "is produced only by an audited human correction. Attempt budgets are enforced, so no field "
        "can loop indefinitely: an exhausted budget routes to review rather than spending again."))

    # -- 3 innovations -------------------------------------------------------
    s.append(para("3. Key Innovations", "h1"))
    s.append(table([
        ["Innovation", "What it does", "Why it matters"],
        ["Field-level Cost Governor",
         "Decides per field from fused confidence, validator verdicts, field policy and attempt history.",
         "Budget is spent on uncertain fields, not on whole pages."],
        ["Validators kept out of fusion",
         "Healthcare verdicts reach the governor as a separate, orthogonal input rather than being blended into a confidence score.",
         "A confident wrong answer that fails an NPI checksum is still caught."],
        ["Local retry before any paid call",
         "Crops the field, re-OCRs with a secondary engine, revalidates and fuses with an agreement bonus.",
         f"Resolved {b['local_retry_resolution_rate']:.1%} of retried fields at local-compute cost."],
        ["Crop-only escalation boundary",
         "engine/cropper.py raises rather than returns if a crop exceeds the configured page fraction.",
         "PHI minimisation is structural, not a config flag a caller might forget."],
        ["Grounding before acceptance",
         "A model answer must be structured, typed, grounded in its own visible_text and short enough to fit the box.",
         "A paid answer is never treated as an oracle."],
        ["Measured cost ledger",
         "Every stage appends to a per-operation ledger; cost claims are queries over it.",
         "No cost number in this submission is hand-calculated."],
    ], [40 * mm, 68 * mm, 68 * mm]))

    # -- 4 results -----------------------------------------------------------
    s.append(para("4. Results Summary", "h1"))
    s.append(para(
        f"Frozen synthetic test split at commit <font face='Courier' size='8'>{EVIDENCE.frozen_commit[:12]}</font>: "
        f"{b['documents']} documents rendered clean, noisy and ugly = {b['pages']} pages and "
        f"{b['evaluated_fields']:,} evaluated fields. Calibration and test splits are disjoint; "
        "thresholds were never tuned on the test split.", "small"))
    s.append(table([
        ["Metric", "Result", "Evidence classification"],
        ["Exact field accuracy", f"{b['field_accuracy']:.3%}", "MEASURED, SYNTHETIC"],
        ["Critical-field accuracy", f"{b['critical_field_accuracy']:.3%}", "MEASURED, SYNTHETIC"],
        ["Precision", f"{counts.precision:.3%}", "MEASURED, SYNTHETIC (derived TP/FP)"],
        ["Recall", f"{counts.recall:.3%}", "MEASURED, SYNTHETIC (derived TP/FN)"],
        ["Automated exact-match rate", f"{b['automated_exact_match_rate']:.3%}", "MEASURED, SYNTHETIC"],
        ["Human-review rate", f"{b['human_review_rate']:.3%}", "MEASURED, SYNTHETIC"],
        ["Measured external API spend", f"${b['measured_external_api_spend_usd']:.2f}", "MEASURED; zero paid calls"],
    ], [56 * mm, 40 * mm, 80 * mm], align={1: "right"}))

    # -- 5 accuracy ----------------------------------------------------------
    s.append(para("5. Accuracy", "h1"))
    s.append(para(
        "Synthetic and official results are reported separately and are never combined into one "
        "percentage. Tier support genuinely differs, and a blended figure would hide that."))
    s.append(table([
        ["Scope", "Documents / pages", "Result", "Boundary"],
        ["Synthetic frozen benchmark",
         f"{b['documents']} / {b['pages']}",
         f"{b['field_accuracy']:.3%} field, {b['critical_field_accuracy']:.3%} critical",
         "MEASURED, SYNTHETIC. Real-claim generalization is unverified."],
        ["Official Tier B (routing)", "5 / 21", "4/4 claim pages selected, 15/15 attachments rejected",
         "MEASURED, OFFICIAL. Page selection proven; field accuracy not separately frozen."],
        ["Official Tier C (UB-04)", "3 / 3", "36/42 primary normalized (85.714%), 16/18 critical",
         "MEASURED, OFFICIAL. Provisional denominator, consumed once. Not a universal UB-04 score."],
        ["Official Tier A (CMS-1500)", "3 development", NOT_REPORTED,
         "Development proof only; the Tier A holdout remains unopened."],
        ["Official Tier D (unstructured)", "7 / 13", NOT_REPORTED,
         "Routing exists; layout-free extraction is unproven. No Tier D capability is claimed."],
    ], [37 * mm, 25 * mm, 47 * mm, 67 * mm]))

    # -- 6 cost --------------------------------------------------------------
    s.append(para("6. Cost per Page", "h1"))
    s.append(para(
        "Local stages are <b>local compute only, near-zero incremental cost</b>, never free. "
        "They burn CPU, that CPU is priced in configs/prices.yaml, and every stage is logged."))
    s.append(table([
        ["Component", "USD / page", "Evidence classification"],
        ["Local preprocessing, routing, OCR, validation, retry",
         f"${b['measured_local_cost_per_page_usd']:.7f}", "MEASURED usage at ASSUMED compute rate"],
        ["External API invoice", f"${b['measured_external_api_spend_usd']:.7f}", "MEASURED; zero paid calls made"],
        ["Selective AI equivalent", f"${b['projected_api_cost_per_page_usd']:.7f}", "PROJECTED from offline-oracle token counts"],
        ["<b>Total automated processing</b>", f"<b>${b['projected_total_automated_cost_per_page_usd']:.7f}</b>",
         "<b>PROJECTED</b> local + selective AI"],
        ["Human review", "$0.03 / reviewed field", "ASSUMED illustrative rate; reported separately"],
    ], [66 * mm, 30 * mm, 80 * mm], align={1: "right"}))
    s.append(Spacer(1, 3 * mm))
    projections = {int(p["pages"]): p for p in EVIDENCE.cost_projection()}
    million = projections.get(1000000)
    if million:
        s.append(BarChartFlowable([
            ("Local compute", float(million["measured_local_compute_projection_usd"]),
             f"${float(million['measured_local_compute_projection_usd']):,.0f}"),
            ("Selective AI (projected)", float(million["projected_api_cost_usd"]),
             f"${float(million['projected_api_cost_usd']):,.0f}"),
            ("Automated total", float(million["projected_total_automated_cost_usd"]),
             f"${float(million['projected_total_automated_cost_usd']):,.0f}"),
        ], CONTENT_W, height=32 * mm,
            title="Projected automated cost at 1,000,000 pages (linear extrapolation)"))
        s.append(para(
            "Volume figures are linear projections, not invoices or capacity guarantees. They exclude "
            "storage, orchestration, redundancy, observability, networking, support and tax. The "
            "human-review assumption is reported separately and is not included in these bars.", "small"))

    # -- 7 throughput --------------------------------------------------------
    s.append(para("7. Throughput and Latency", "h1"))
    s.append(table([
        ["Metric", "Measured", "Context"],
        ["Pages processed", f"{t['pages']}", "Frozen synthetic test run"],
        ["Total processing time", f"{t['total_elapsed_ms'] / 1000:.1f} s", "First page retained; no warm-up exclusion"],
        ["Throughput", f"{t['pages_per_minute']:.2f} pages/min ({t['pages_per_hour']:.0f}/hr)", "Single worker, one process"],
        ["Average latency", f"{t['average_latency_per_page_ms']:.0f} ms/page", "Development workstation"],
        ["P50 / P95 latency", f"{t['p50_latency_ms']:.0f} ms / {t['p95_latency_ms']:.0f} ms", "Same run"],
    ], [40 * mm, 58 * mm, 78 * mm]))
    s.append(para(
        "This is a single-worker measurement on a development workstation, not a production SLA. "
        "Throughput at enterprise scale is an architectural projection based on stateless workers "
        "behind a durable queue, described in the Architecture document.", "small"))

    # -- 8 enterprise value --------------------------------------------------
    s.append(para("8. Enterprise Value", "h1"))
    s.append(para(
        "The pipeline is page-oriented with append-only receipts, which gives a clean horizontal "
        "worker boundary. Three operating presets (Economy, Balanced, Accuracy) move along a "
        "calibrated accuracy-cost frontier without changing code: they are configuration, not three "
        "separate pipelines. Every accepted field carries its decision path, so an auditor can ask "
        "why any value was accepted and get a mechanical answer rather than a model's opinion."))

    # -- 9 why win -----------------------------------------------------------
    s.append(para("9. Why ClaimRoute Should Win", "h1"))
    s.append(para(
        "Most systems improve accuracy by spending more on AI. ClaimRoute improves <b>verified "
        "accuracy per dollar</b>: it resolves easy fields locally, validates them with healthcare "
        "rules, retries uncertain fields cheaply, and purchases model intelligence only when the "
        "expected gain justifies the cost.", "pull"))
    s.append(table([
        ["Judging criterion", "How ClaimRoute answers it"],
        ["Extraction accuracy (35%)",
         f"{b['field_accuracy']:.3%} field and {b['critical_field_accuracy']:.3%} critical accuracy with "
         f"{b['human_review_rate']:.2%} human review; validators are an independent check, not a blended score."],
        ["Cost per page (35%)",
         f"{b['primary_local_resolution_rate']:.1%} of fields never leave the cheapest rung; only "
         f"{b['escalation_rate']:.2%} reach a model call. Costs come from a measured ledger."],
        ["Innovation (10%)",
         "AI is budgeted per field rather than per page: confidence-driven routing, crop-only escalation, grounding, and explainable decisions."],
        ["Scalability (10%)",
         "Stateless page pipeline, resumable receipts, model-agnostic adapters; production topology is labelled roadmap, not claimed as deployed."],
        ["Simplicity (10%)",
         "One extraction spine, policy in YAML rather than code, 500 passing tests, PHI-safe evidence."],
    ], [40 * mm, 136 * mm]))

    # -- 10 limitations ------------------------------------------------------
    s.append(para("10. Honest Limitations", "h1"))
    s.append(CalloutBox("What this submission does NOT claim", [
        "The headline accuracy is synthetic. Real-claim generalization is unverified.",
        "No paid provider call was ever made. External spend is measured at $0, and the selective AI",
        "cost is projected from token counts, never an invoice.",
        "The offline oracle is a deterministic test double for the escalation boundary. Its resolution",
        "rate is not evidence about any real model's accuracy or latency.",
        "Official Tier C used a provisional denominator on three documents and is consumed; Tier A has",
        "development evidence only; Tier D extraction is not claimed.",
        "Throughput is a single-worker workstation measurement, not a production SLA.",
        "Security controls are PHI-minimizing prototype controls. This is not a HIPAA compliance claim.",
        "The enterprise topology is designed and documented, not deployed infrastructure.",
    ], CONTENT_W))

    return s


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build(
        OUT,
        title="ClaimRoute AI - Executive Summary",
        subject="Datamatics AI Engineering Hackathon 2026",
        story=story(),
        footer_left=f"ClaimRoute AI - Executive Summary - evidence frozen at {EVIDENCE.frozen_commit[:12]}",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
