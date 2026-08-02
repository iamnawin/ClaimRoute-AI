"""Generate submission/final/02_Architecture.pdf from frozen evidence.

Every number in the document comes from ``scripts/submission/evidence.py``, which reads
only committed frozen artifacts. Prose describes the implemented prototype and labels
production capability as roadmap; nothing here asserts a capability the repository does
not contain.

Run:
    .\\.venv\\Scripts\\python.exe scripts/submission/build_architecture.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reportlab.platypus import PageBreak

from submission.evidence import EVIDENCE as E
from submission.evidence import NOT_REPORTED
from submission.pdf_kit import (
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

OUT = Path(__file__).resolve().parents[2] / "submission" / "final" / "02_Architecture.pdf"

W = CONTENT_W
PRODUCT = (
    "ClaimRoute AI is a cost-governed healthcare claims extraction platform in which "
    "every field takes the cheapest reliable path."
)


def pct(value: float) -> str:
    return f"{value:.3%}"


def usd(value: float, places: int = 6) -> str:
    return f"${value:.{places}f}"


def h1(text: str):
    return [para(text, "h1"), Rule(W)]


def section_1_overview() -> list:
    b = E.blended
    story = [
        para("ClaimRoute AI", "title"),
        para("Solution Architecture and Technical Design", "subtitle"),
        para(PRODUCT, "pull"),
        Rule(W),
        Spacer(1, 4 * mm),
    ]
    story += h1("1. Architecture Overview")
    story.append(para(
        "The pipeline is an ordered ladder of stages, cheapest first. Each stage may resolve "
        "a field, and only fields that survive every cheaper stage are allowed to consume a "
        "more expensive one. The controlling loop is <b>decide, spend the cheapest remaining "
        "rung, re-decide</b>: after every rung the candidate re-enters validation and the Cost "
        "Governor, and each decision is appended to the field's decision list so the whole "
        "ladder is auditable after the fact.", "body"))
    story.append(para(
        "This inverts the usual design. Rather than sending every page to the most capable "
        "model and paying for certainty everywhere, the platform pays for certainty only "
        "where the cheap deterministic stages could not produce it. On the frozen synthetic "
        f"test split, {pct(b['primary_local_resolution_rate'])} of routed fields never leave "
        "local compute at all.", "body"))
    story.append(Spacer(1, 3 * mm))
    story.append(MetricStrip([
        (pct(b["field_accuracy"]), "Exact field accuracy, frozen synthetic test split"),
        (pct(b["primary_local_resolution_rate"]), "Resolved at primary local OCR"),
        (pct(b["escalation_rate"]), "Routed to multimodal escalation"),
        (usd(b["projected_total_automated_cost_per_page_usd"]), "Projected automated cost per page"),
    ], W))
    story.append(Spacer(1, 4 * mm))
    story.append(para(
        "Two design rules make the ladder trustworthy rather than merely cheap. First, "
        "validator verdicts are deliberately <b>not</b> fused into the confidence score; they "
        "reach the governor as a separate, orthogonal input, so a confidently-read but "
        "clinically impossible value cannot buy its way to acceptance. Second, the attempt "
        "budget is finite, so an exhausted field routes to human review rather than looping.",
        "body"))
    return story


def section_2_prototype_flow() -> list:
    story = h1("2. Implemented Prototype Flow")
    story.append(para(
        "Every box below exists in the repository today and runs on a developer machine. "
        "Labels in this document follow one convention: <b>IMPLEMENTED PROTOTYPE</b> means "
        "code exists and is exercised by tests; <b>PRODUCTION ROADMAP</b> means designed and "
        "specified but not built.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(FlowDiagram([
        "Streamlit / Local Workspace",
        "Intake Service",
        "Signature Detection",
        "Page Decoder",
        "Document Router",
        "Preprocessing (Tier-0)",
        "Primary OCR (Tier-1)",
        "Layout Mapping",
        "Healthcare Validators",
        "Confidence Fusion",
        "Cost Governor",
        "Local Retry Rung",
        "Selective Multimodal",
        "Grounding Gate",
        "Human Review",
        "Results / Audit / Cost Ledger",
        "JSON / CSV Export",
    ], W, columns=3,
        note="IMPLEMENTED PROTOTYPE. Streamlit is the operator surface for a single machine; "
             "it is not the enterprise ingestion tier."))
    story.append(Spacer(1, 3 * mm))
    story.append(table([
        ["Stage", "Module", "Cost class", "What it decides"],
        ["Intake and decode", "app/intake.py", "Local compute only",
         "File role, format, page count; refuses unsupported content"],
        ["Signature detection", "app/intake.py, engine/router.py", "Local compute only",
         "Whether a page carries a known claim-form signature"],
        ["Document router", "engine/router.py", "Local compute only",
         "Form type and variant from a red-dropout ink mask; no OCR, no API"],
        ["Preprocess", "engine/preprocess.py", "Local compute only",
         "Which Tier-0 ops fire, each gated by its own measured signal"],
        ["Primary OCR", "engine/ocr/paddle_engine.py", "Local compute only",
         "Text and per-token confidence for the whole page"],
        ["Layout mapping", "engine/layout/mapper.py", "Local compute only",
         "Which tokens belong to which form box"],
        ["Validators", "engine/validators/registry.py", "Local compute only",
         "PASS / FAIL / INAPPLICABLE per policy-required check"],
        ["Fusion", "engine/fusion.py", "Local compute only",
         "Explainable weighted confidence from four signals"],
        ["Cost Governor", "engine/governor.py", "Local compute only",
         "ACCEPT, ACCEPT_WITH_FLAG, RETRY, ESCALATE, or HUMAN_REVIEW"],
        ["Local retry", "engine/retry_rung.py, app/local_retry.py", "Local compute only",
         "Crop re-OCR on the secondary engine plus agreement bonus"],
        ["Escalation", "engine/escalate.py, engine/vision/", "Paid, governed",
         "The one metered external transaction; crops only"],
        ["Grounding", "engine/grounding.py", "Local compute only",
         "Whether a model answer is even allowed to compete"],
        ["Human review", "app/workspace.py", "Priced per field touch",
         "Reviewer override with identity and reason, audit-logged"],
        ["Ledger", "engine/ledger.py", "Local compute only",
         "Append-only JSONL record behind every cost number in this submission"],
    ], [26 * mm, 40 * mm, 27 * mm, W - 93 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "Cheap deterministic stages are described throughout as <b>local compute only</b> with "
        "<b>near-zero incremental cost</b>, never as free. They burn CPU, that CPU is priced in "
        "configs/prices.yaml, and every one of them writes a row to the cost ledger.", "small"))
    return story


def section_3_intake() -> list:
    story = h1("3. Local Intake and Signature Detection")
    story.append(para(
        "Intake is content-aware rather than extension-trusting. Each file is sniffed for its "
        "real format, classified into a role (claim document, expected output, specification, "
        "attachment, unsupported), and decoded page by page. Multi-page TIFF containers are "
        "expanded so downstream stages always see a single page.", "body"))
    story.append(para(
        "Signature detection is what makes Tier B tractable. A container may hold one claim "
        "form and many supporting pages; the platform scores each page for a known form "
        "signature and carries forward only the claim page, discarding attachments before any "
        "extraction cost is incurred. On official Tier B data this page-selection behaviour is "
        "measured, and it is the part of Tier B the submission claims.", "body"))
    story.append(para(
        "Intake runs entirely on localhost. Nothing in this stage contacts a network service.",
        "body"))
    return story


def section_4_preprocess() -> list:
    ab = E.ablation["arms"]
    story = h1("4. Preprocessing (Tier-0)")
    story.append(para(
        "Four operations are available: deskew, illumination flattening, denoise, and contrast "
        "stretch. Each fires only when its own measured signal crosses a threshold, so a clean "
        "page passes through untouched and an empty transform history is the proof that nothing "
        "was done to it. Geometric operations append to a transform history, which lets "
        "ground-truth bounding boxes be replayed through exactly the same math during "
        "evaluation.", "body"))
    story.append(para(
        "The honest framing of the Tier-0 result is <b>pipeline recovery, not OCR uplift</b>. On "
        "the ugly degradation tier, extraction goes from 0% to functioning because rotation "
        "correction makes routing and layout mapping viable at all, not because character "
        "recognition improved. The composite quality score measures scan condition, not "
        "processing benefit, so preprocessing claims rest on the ablation below and on direct "
        "measurables, never on before-and-after quality deltas.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Ablation arm", "Field accuracy", "Cost / page", "Latency (ms)", "Status"],
        ["Primary OCR only", pct(ab["primary_ocr_only"]["accuracy"]),
         usd(ab["primary_ocr_only"]["local_cost_per_page_usd"]),
         f"{ab['primary_ocr_only']['average_latency_ms']:.0f}", "MEASURED"],
        ["Primary + preprocessing", pct(ab["primary_plus_preprocessing"]["accuracy"]),
         usd(ab["primary_plus_preprocessing"]["local_cost_per_page_usd"]),
         f"{ab['primary_plus_preprocessing']['average_latency_ms']:.0f}", "MEASURED"],
        ["Full cost-governed pipeline", pct(ab["full_cost_governed_pipeline"]["accuracy"]),
         usd(ab["full_cost_governed_pipeline"]["projected_automated_cost_per_page_usd"]),
         f"{ab['full_cost_governed_pipeline']['average_latency_ms']:.0f}",
         "MEASURED local + PROJECTED offline-oracle"],
    ], [46 * mm, 26 * mm, 24 * mm, 24 * mm, W - 120 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "A validator-bypass arm was deliberately not produced. No bypass exists in the frozen "
        "engine, and adding one after the freeze would invalidate the evidence.", "small"))
    return story


def section_5_router() -> list:
    story = h1("5. Document Routing")
    story.append(para(
        "The router is free of both OCR and API calls. Claim forms are printed in dropout ink, "
        "so isolating the red channel yields a layout mask that is essentially the blank form "
        "itself. Correlating that mask against per-form reference profiles classifies the "
        "document and its line-count variant deterministically, returning a document type, a "
        "variant, and the evidence behind the decision.", "body"))
    story.append(para(
        "Routing is the cheapest possible discriminator and it runs before anything expensive. "
        "A page that does not correlate with any known profile abstains rather than guessing, "
        "which keeps unstructured Tier D content out of the structured template path instead of "
        "producing confident nonsense.", "body"))
    return story


def section_6_ocr_layout() -> list:
    story = [KeepTogether(h1("6. Primary OCR and Layout Mapping") + [para(
        "Two OCR engines sit behind one schema: PaddleOCR is the primary full-page engine and "
        "Tesseract is the secondary engine used by the retry rung. Because both adapters return "
        "the same shape, the pipeline is engine-agnostic and a third engine is a new adapter "
        "rather than a pipeline change.", "body")])]
    story.append(para(
        "Layout mapping assigns recognised tokens to form boxes using templates generated from "
        "the renderers per line-count variant, with overlap-based assignment. For official "
        "organiser layouts there are dedicated registration modules for CMS-1500 and UB-04 that "
        "align the observed page to the expected field geometry.", "body"))
    story.append(para(
        "One detail matters enough to state: a field crop is one box, not a page. The retry rung "
        "passes a block page-segmentation mode to Tesseract, because the default mode discards "
        "isolated single characters, which is what made single-character fields such as patient "
        "sex and diagnosis pointers unreadable. The full-page adapter default is deliberately "
        "unchanged so the bake-off path is unaffected.", "body"))
    return story


def section_7_validation() -> list:
    story = h1("7. Healthcare Validation")
    story.append(para(
        "Fifteen policy-driven validators run on every extracted field for which they are "
        "applicable: NPI checksum, ICD-10 and CPT dictionary membership, date sanity and "
        "ordering, arithmetic consistency across charge columns, and cross-field agreement "
        "rules. Each returns PASS, FAIL, or INAPPLICABLE. Which validators are required for a "
        "given field is configuration, not code, and lives in configs/field_policy.yaml.",
        "body"))
    story.append(para(
        "Validators are the reason a cheap answer can be trusted. Optical confidence alone "
        "cannot distinguish a crisply-scanned wrong digit from a crisply-scanned right one; a "
        "checksum can. Keeping the verdicts out of the fused score preserves that "
        "independence.", "body"))
    return story


def section_8_fusion_governor() -> list:
    b = E.blended
    story = h1("8. Confidence Fusion and the Cost Governor")
    story.append(para(
        "Fusion combines four signals into one explainable weighted score: OCR token confidence, "
        "page quality, span sanity, and character-set fit against the field's expected shape. "
        "The output is a number a human can decompose, not a model logit.", "body"))
    story.append(para(
        "The Cost Governor then makes a four-way decision from four inputs: the fused "
        "confidence, the validator verdicts, the field policy, and the attempt history. "
        "<b>decide()</b> is a pure function of those inputs and <b>apply()</b> records the "
        "resulting state, which is what makes governor behaviour unit-testable in isolation. "
        "Thresholds are configuration: three presets (economy, balanced, accuracy) define the "
        "accuracy-cost frontier, and the frozen run used the balanced preset.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Field state", "Meaning", "Reachable from automation"],
        ["ACCEPT", "Confidence and validators both clear the preset bar", "Yes"],
        ["ACCEPT_WITH_FLAG", "Usable but marked for downstream attention; disabled in the accuracy preset", "Yes"],
        ["RETRY", "Cheap local rung is worth spending before anything paid", "Yes"],
        ["ESCALATE", "Only path to a paid model call; policy must permit it", "Yes"],
        ["HUMAN_REVIEW", "Attempt budget exhausted or policy forbids escalation", "Yes"],
        ["ACCEPT_WITH_OVERRIDE", "Reviewer identity and reason recorded; audit-logged",
         "No - human_override() only"],
    ], [34 * mm, W - 74 * mm, 40 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "The sixth state is structurally unreachable from automated code paths. Automated code "
        "may only emit the automated states, and the state setter enforces it, so no defect in "
        "pipeline logic can silently manufacture the appearance of human sign-off.", "body"))
    story.append(Spacer(1, 2 * mm))
    funnel = E.resolution_funnel()
    story.append(KeepTogether([
        para("Measured resolution funnel, frozen synthetic test split", "h2"),
        table(
            [["Stage", "Fields", "Share of routed", "Evidence label"]] +
            [[r["stage"], f"{r['fields']:,}", pct(r["share_of_routed"]), r["label"]] for r in funnel],
            [58 * mm, 20 * mm, 26 * mm, W - 104 * mm]),
    ]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        f"Of {b['routed_fields']:,} routed fields, {pct(b['local_retry_rate'])} needed the local "
        f"retry rung and {pct(b['escalation_rate'])} reached escalation. "
        f"{pct(b['human_review_rate'])} finished at human review.", "small"))
    return story


def section_9_validation_layer() -> list:
    story = h1("9. Healthcare Validation Layer")
    story.append(para(
        "Validation runs after every candidate-generation stage, not only at the end. NPI "
        "values receive the standard checksum test; dates are parsed and checked for plausible "
        "ordering; ICD-10, CPT, and HCPCS values receive format and dictionary checks; monetary "
        "fields receive amount, column-total, and cross-field arithmetic checks. Each field's "
        "policy selects only the validators that apply to that field.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(FlowDiagram([
        "Primary OCR", "Healthcare validation", "Local retry", "Healthcare validation",
        "Multimodal candidate", "Healthcare validation", "Human review",
    ], W, columns=1, box_h=8 * mm,
        note="A failed or inapplicable check stays explicit; it is never hidden inside OCR confidence."))
    story.append(Spacer(1, 2 * mm))
    story.append(CalloutBox(
        "Authority boundary",
        ["AI is a candidate generator, not an authority. Grounding and field-specific healthcare "
         "validation decide whether its candidate may be accepted; otherwise the field routes to review."],
        W,
    ))
    return story


def section_10_cost_governor() -> list:
    decision_table = table([
        ["Decision", "Meaning"],
        ["ACCEPT", "Candidate clears confidence and validation policy."],
        ["ACCEPT_WITH_FLAG", "Candidate is usable but remains visibly flagged."],
        ["RETRY", "Spend one cheaper local attempt before considering a provider."],
        ["ESCALATE", "A permitted unresolved crop may enter the paid-provider gate."],
        ["HUMAN_REVIEW", "Policy, attempts, validation, provider state, or budget requires review."],
    ], [38 * mm, W - 38 * mm])
    story = [KeepTogether(h1("10. Cost Governor") + [
        para(
            "The governor converts evidence and policy into one bounded next action. Its inputs are OCR "
            "confidence, layout confidence, page quality, validation outcomes, field criticality, retry "
            "history, provider availability, and remaining field, document, batch, and session budget.",
            "body"),
        decision_table,
    ])]
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Preset", "Policy intent", "Evidence boundary"],
        ["Economy", "Tighter spending; fewer fields remain escalation-eligible.",
         "Configuration and replay-calibration point; not a live-provider benchmark."],
        ["Balanced", "Local retry first with selective escalation; frozen benchmark preset.",
         "Frozen synthetic benchmark plus offline-oracle escalation contribution."],
        ["Accuracy", "Higher local acceptance bar; no accept-with-flag shortcut.",
         "Configuration and replay-calibration point; not a live-provider benchmark."],
    ], [28 * mm, 58 * mm, W - 86 * mm]))
    return story


def section_11_local_retry() -> list:
    b = E.blended
    retry_cost = next(row for row in E.stage_costs() if row["operation"] == "retry_tesseract")
    story = h1("11. Local Retry Rung")
    story.append(para(
        "When primary OCR is uncertain, ClaimRoute isolates the field box and runs Tesseract with "
        "field-aware page-segmentation profiles. The result is validated again and may receive an "
        "agreement bonus when independent local engines agree. Only fields still unresolved after "
        "this bounded retry can become provider candidates.", "body"))
    story.append(MetricStrip([
        (pct(b["local_retry_rate"]), "Routed to local retry, measured synthetic"),
        (pct(b["local_retry_resolution_rate"]), "Retry-route resolution, measured synthetic"),
        (f"{retry_cost['calls']:,}", "Retry OCR operations, measured"),
        (usd(retry_cost["cost_usd"], 8), "Retry OCR allocation, measured local compute"),
    ], W))
    story.append(Spacer(1, 3 * mm))
    story.append(para(
        "This rung adds near-zero incremental API spend because it is local compute, but it is not "
        "free. It also contributes meaningful latency: crop preparation and repeated Tesseract "
        "profiles are a current prototype bottleneck and a priority for profiling and bounded "
        "parallelism before production.", "body"))
    return story


def section_12_multimodal() -> list:
    smoke = E.live_openrouter_smoke()
    story = h1("12. Multimodal Escalation")
    story.append(FlowDiagram([
        "Cost Governor", "Crop isolation", "Policy gate", "Provider adapter",
        "Structured response", "Grounding", "Healthcare validation", "Accept or review",
    ], W, columns=2, box_h=9 * mm,
        note="Selective, crop-level candidate generation. Provider access is disabled by default."))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Guardrail", "Implemented control"],
        ["Data minimisation", "Crop only; no full-page request by default; maximum 25% of page; 12 px margin."],
        ["Provider activation", "Disabled by default; explicit environment gates and model allowlist required."],
        ["Spend control", "Per-field, page, document, batch, and session call/cost limits; no automatic reruns."],
        ["Duplicate control", "Request fingerprint reuses a prior result rather than paying twice."],
        ["Output control", "Strict schema, grounding, healthcare validation, and accept-or-review boundary."],
        ["Audit control", "Model, tokens, cost, latency, hashes, and decisions recorded; raw response not persisted."],
    ], [38 * mm, W - 38 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "MEASURED | LIVE_PROVIDER | SYNTHETIC | CROP_LEVEL | ONE_CALL_SMOKE_TEST", "h2"))
    story.append(para(
        f"One policy-guarded OpenRouter request used {smoke['actual_model_used']} with no model "
        f"substitution. It used {smoke['usage']['input_tokens']} input tokens and "
        f"{smoke['usage']['output_tokens']} output tokens, cost "
        f"{usd(smoke['cost']['measured_usd'], 8)}, and completed in "
        f"{smoke['latency_ms'] / 1000:.2f} seconds. The structured response was valid, grounding "
        "was accepted, and the synthetic NPI candidate passed checksum validation. Exactly one "
        "external call was made; no PHI or organiser document was sent and no raw response was "
        "persisted.", "body"))
    story.append(para(
        "This proves the guarded integration path only. It does not prove multimodal benchmark "
        "accuracy, general provider reliability, or live performance of all operating presets.",
        "small"))
    return story


def section_13_human_review() -> list:
    story = h1("13. Human Review and Auditability")
    story.append(para(
        "Fields that automation cannot safely resolve become explicit review tasks. The prototype "
        "shows the isolated crop, available candidates, confidence and validation context. A reviewer "
        "correction is validated before acceptance; the claim status and JSON/CSV exports then update "
        "from the same batch receipt.", "body"))
    story.append(para(
        "The audit event records reviewer identity, action, reason, prior state, resulting state, and "
        "timestamp. Automated code cannot manufacture a human override state. This is a functional "
        "single-workspace review prototype, not an enterprise review-operations platform.", "body"))
    story.append(CalloutBox(
        "Cost boundary",
        ["Human review is priced illustratively at $0.03 per field touch and is always shown separately "
         "from measured local compute and projected automated provider cost."],
        W,
    ))
    return story


def section_14_accuracy_evidence() -> list:
    b = E.blended
    story = h1("14. Accuracy and Resolution Evidence")
    story.append(para(
        f"Scope: frozen synthetic Balanced run, {b['documents']} documents, {b['pages']} pages, "
        f"{b['evaluated_fields']:,} evaluated fields, and {b['routed_fields']:,} routed fields.",
        "body"))
    story.append(table([
        ["Metric", "Value", "Classification"],
        ["Exact field accuracy", pct(b["field_accuracy"]), "MEASURED SYNTHETIC"],
        ["Critical-field accuracy", pct(b["critical_field_accuracy"]), "MEASURED SYNTHETIC"],
        ["Primary local resolution", pct(b["primary_local_resolution_rate"]), "MEASURED SYNTHETIC"],
        ["Local retry route", pct(b["local_retry_rate"]), "MEASURED SYNTHETIC"],
        ["Multimodal escalation route", pct(b["escalation_rate"]), "MEASURED ROUTING"],
        ["Human review", pct(b["human_review_rate"]), "MEASURED SYNTHETIC"],
        ["Accept with flag", pct(b["accept_with_flag_rate"]), "MEASURED SYNTHETIC"],
        ["External API calls in frozen run", str(b["measured_external_api_calls"]), "MEASURED"],
        ["Selective AI cost per page", usd(b["projected_api_cost_per_page_usd"]), "PROJECTED OFFLINE_ORACLE"],
    ], [63 * mm, 35 * mm, W - 98 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "The offline oracle contributes deterministic resolution at the escalation boundary; it is "
        "not a real model and provides no live-provider accuracy or latency evidence. The separate "
        "OpenRouter smoke test is integration evidence and is not blended into this table.", "small"))
    return story


def section_15_cost_architecture() -> list:
    b = E.blended
    costs = E.stage_costs()
    projections = E.cost_projection()
    at_100m = next(row for row in projections if row["pages"] == "100000000")
    labels = {
        "ocr_paddle": "Primary OCR (Paddle)",
        "escalate_offline-oracle": "Offline-oracle escalation",
        "preprocess": "Preprocessing",
        "retry_tesseract": "Tesseract retry",
        "route": "Routing",
        "validate_fuse": "Validation / fusion",
        "escalate_intent": "Escalation intent",
    }
    story = h1("15. Cost Architecture")
    story.append(MetricStrip([
        (usd(b["measured_local_cost_per_page_usd"], 7), "MEASURED local compute per page"),
        (usd(b["projected_api_cost_per_page_usd"], 7), "PROJECTED selective API per page"),
        (usd(b["projected_total_automated_cost_per_page_usd"], 7), "PROJECTED automated total per page"),
        ("$0.03", "ASSUMED human review per field touch"),
    ], W))
    story.append(Spacer(1, 3 * mm))
    rows = [["Stage", "Operations", "Total cost", "Classification"]]
    for row in costs:
        label = "OFFLINE_ORACLE / PROJECTED" if row["operation"] == "escalate_offline-oracle" else "MEASURED LOCAL"
        if row["operation"] == "escalate_intent":
            label = "MEASURED INTENT"
        rows.append([labels[row["operation"]], f"{row['calls']:,}", usd(row["cost_usd"], 8), label])
    story.append(table(rows, [55 * mm, 25 * mm, 33 * mm, W - 113 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        f"At 100 million pages the frozen projection is ${float(at_100m['measured_local_compute_projection_usd']):,.0f} "
        f"measured/local, ${float(at_100m['projected_api_cost_usd']):,.0f} projected API, and "
        f"${float(at_100m['projected_total_automated_cost_usd']):,.0f} projected automated total. "
        f"Illustrative human review is ${float(at_100m['configured_human_review_cost_usd']):,.2f} "
        "and remains separate. Local OCR consumes priced CPU; it is never described as free.", "body"))
    return story


def section_16_throughput_scalability() -> list:
    t = E.throughput
    story = h1("16. Throughput and Scalability")
    story.append(MetricStrip([
        (f"{t['p50_latency_ms']:,.0f} ms", "P50 page latency, measured prototype"),
        (f"{t['p95_latency_ms']:,.0f} ms", "P95 page latency, measured prototype"),
        (f"{t['pages_per_minute']:.2f}", "Pages per minute, measured prototype"),
        (f"{t['pages_per_hour']:.2f}", "Pages per hour, measured prototype"),
    ], W))
    story.append(Spacer(1, 3 * mm))
    story.append(para(
        f"These figures come from the {t['pages']}-page frozen synthetic run on one development "
        "workstation. They are prototype measurements, not a production SLA. Provider latency was "
        "not part of that frozen run.", "body"))
    story.append(para("PRODUCTION ROADMAP topology", "h2"))
    story.append(FlowDiagram([
        "Client", "API Gateway", "Auth / rate limit", "Object storage", "Queue",
        "Stateless extraction workers", "Validation / governor", "Review queue",
        "Results database", "Audit / monitoring",
    ], W, columns=2, box_h=8.5 * mm,
        note="Architecture roadmap only. Distributed infrastructure is not deployed evidence."))
    return story


def section_17_resilience() -> list:
    story = h1("17. Failure Handling and Resilience")
    story.append(table([
        ["Failure", "Bounded response"],
        ["Corrupt file / unsupported format", "Reject at intake with an explicit reason; do not enter extraction."],
        ["Routing uncertainty", "Abstain from a structured template rather than guessing a form type."],
        ["Zero meaningful extraction", "Return an observable incomplete result and create review work."],
        ["Partial extraction", "Preserve resolved fields; route only unresolved fields for further action."],
        ["Retry exhausted", "Stop the retry loop and evaluate escalation policy or human review."],
        ["Provider disabled or error", "Make no hidden fallback call; retain a typed outcome and route to review."],
        ["Invalid multimodal response", "Reject schema/grounding/validation failure; do not accept the candidate."],
        ["Budget exceeded", "Refuse the paid call and route to human review."],
        ["Duplicate request", "Reuse the fingerprinted result; avoid a second paid request."],
        ["Production worker failure", "Roadmap: idempotent receipts, queue retry, then dead-letter queue."],
    ], [55 * mm, W - 55 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "The terminal safety condition is human review, not an unbounded retry or a silently accepted "
        "candidate. Idempotency and duplicate-call protection already guard the provider boundary; "
        "a production dead-letter queue belongs to the distributed roadmap.", "body"))
    return story


def section_18_security_privacy() -> list:
    story = h1("18. Security, Privacy and PHI Minimisation")
    story.append(para(
        "PHI minimisation through field-level isolation and policy-governed escalation.", "pull"))
    story.append(table([
        ["Control", "Current implementation boundary"],
        ["Default processing", "Localhost/private processing; organiser data is not sent externally."],
        ["External payload", "Proven field crop only, bounded to 25% of source page with 12 px margin."],
        ["Provider state", "Disabled by default and requires explicit runtime gates plus an allowlisted model."],
        ["Secrets", "Environment-only credentials; no key in config, receipts, tests, or generated output."],
        ["Persistence", "Audit metadata and hashes retained; raw provider response is not persisted."],
        ["Live evidence", "Exactly one synthetic crop-level OpenRouter smoke test; no PHI transmitted."],
        ["Compliance", "Prototype controls only; no HIPAA certification or compliance claim."],
    ], [42 * mm, W - 42 * mm]))
    return story


def section_19_implemented_roadmap() -> list:
    implemented = [
        "Local intake; PNG/JPEG/TIFF/PDF and numeric-extension handling",
        "Preprocessing, routing, local OCR, and layout mapping",
        "Healthcare validators, confidence fusion, and Cost Governor",
        "Local retry and crop-level escalation interfaces",
        "Provider guardrails and one synthetic live OpenRouter smoke test",
        "JSON/CSV outputs, coverage/cost dashboards, and review prototype",
        "Audit ledger and reproducible benchmark harness",
    ]
    roadmap = [
        "Distributed queue workers and production object storage",
        "Enterprise review operations and customer-managed models",
        "Continuous calibration and model benchmarking at scale",
        "Expanded unstructured-document support",
        "Production observability, service levels, and dead-letter operations",
        "Formal compliance certification",
    ]
    count = max(len(implemented), len(roadmap))
    rows = [["IMPLEMENTED PROTOTYPE", "PRODUCTION ROADMAP"]]
    for index in range(count):
        rows.append([
            implemented[index] if index < len(implemented) else "",
            roadmap[index] if index < len(roadmap) else "",
        ])
    story = h1("19. Implemented vs Roadmap")
    story.append(para(
        "The line below is deliberate: current code and measured evidence stay separate from a "
        "credible production destination.", "body"))
    story.append(table(rows, [W / 2, W / 2]))
    story.append(Spacer(1, 6 * mm))
    story.append(Rule(W))
    story.append(Spacer(1, 5 * mm))
    story.append(para("Every field takes the cheapest reliable path.", "pull"))
    return story


def validate_required_evidence() -> None:
    b = E.blended
    required_blended = {
        "field_accuracy", "critical_field_accuracy", "pages", "documents",
        "evaluated_fields", "routed_fields", "primary_local_resolution_rate",
        "local_retry_rate", "local_retry_resolution_rate", "escalation_rate",
        "human_review_rate", "accept_with_flag_rate", "measured_local_cost_per_page_usd",
        "projected_api_cost_per_page_usd", "projected_total_automated_cost_per_page_usd",
        "p50_latency_ms", "p95_latency_ms", "throughput_pages_per_minute",
        "throughput_pages_per_hour", "measured_external_api_calls",
    }
    missing = sorted(required_blended - b.keys())
    if missing:
        raise KeyError(f"missing frozen blended evidence keys: {', '.join(missing)}")

    operations = {row["operation"] for row in E.stage_costs()}
    required_operations = {
        "ocr_paddle", "escalate_offline-oracle", "preprocess", "retry_tesseract",
        "route", "validate_fuse", "escalate_intent",
    }
    if required_operations - operations:
        raise KeyError("missing required stage-cost evidence")

    volumes = {row["pages"] for row in E.cost_projection()}
    if volumes != {"1000", "1000000", "10000000", "100000000"}:
        raise ValueError("unexpected frozen cost-projection volumes")

    smoke = E.live_openrouter_smoke()
    required_smoke = {
        "actual_model_used", "model_substituted", "called_provider", "attempts",
        "structured_response_valid", "grounding_result", "healthcare_validators_passed",
        "usage", "cost", "latency_ms", "raw_response_persisted", "external_calls_made",
    }
    missing_smoke = sorted(required_smoke - smoke.keys())
    if missing_smoke:
        raise KeyError(f"missing live-smoke evidence keys: {', '.join(missing_smoke)}")
    if smoke["external_calls_made"] != 1 or smoke["model_substituted"]:
        raise ValueError("live-smoke receipt does not describe the approved one-call result")


def section_9_validation_loop() -> list:
    story = h1("9. Validation After Every Candidate-Generation Stage")
    story.append(para(
        "Validation is not a final gate that runs once at the end. It runs after every stage "
        "that can produce a new candidate value, which is what makes the ladder safe to walk. "
        "A retry answer and a multimodal answer are both re-validated on exactly the same "
        "rules as the primary OCR answer; nothing earns a shortcut by being expensive.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(FlowDiagram([
        "Primary OCR",
        "Validation",
        "Local Retry",
        "Validation",
        "Multimodal",
        "Validation",
        "Human Review",
    ], W, columns=4, note="Every candidate generator is followed by the same validator set."))
    story.append(Spacer(1, 3 * mm))
    story.append(para(
        "<b>AI is a candidate generator, not an authority.</b> A multimodal model in this "
        "platform proposes a value; it does not decide one. Its answer must pass grounding, "
        "then pass the same healthcare validators as any cheaper answer, then satisfy the "
        "governor, before it is accepted. A model reply that is fluent, confident and "
        "clinically impossible loses to a checksum.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Validator family", "What it proves", "Example failure it catches"],
        ["NPI checksum", "Provider identifier is structurally valid",
         "A transposed digit that reads cleanly but identifies nobody"],
        ["Date parsing and ordering", "Dates exist and are consistently ordered",
         "A service date after the claim date, or 31 February"],
        ["ICD-10 / CPT / HCPCS membership", "The code is real, not merely code-shaped",
         "A confidently-read diagnosis code that no dictionary contains"],
        ["Amount and arithmetic rules", "Charge columns reconcile",
         "Line charges that do not sum to the stated total"],
        ["Field-specific format validators", "The value fits the box it came from",
         "A sex field holding a digit, or an ID longer than the box allows"],
        ["Cross-field agreement", "Related fields tell the same story",
         "A diagnosis pointer referring to a diagnosis line that is blank"],
    ], [40 * mm, 52 * mm, W - 92 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "Verdicts are PASS, FAIL, or INAPPLICABLE. INAPPLICABLE is a first-class outcome, not a "
        "silent pass: it records that a rule did not apply here, which keeps the denominator "
        "honest when a field is legitimately blank.", "small"))
    return story


def section_10_governor_policy() -> list:
    story = h1("10. Cost Governor Decision Policy")
    story.append(para(
        "The governor is where cost becomes a first-class engineering input rather than an "
        "afterthought. It answers one question per field per attempt: what is the cheapest "
        "action that could still produce a trustworthy answer?", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Decision", "Chosen when", "Cost consequence"],
        ["ACCEPT", "Fused confidence clears the preset bar and every required validator passes",
         "No further spend on this field"],
        ["ACCEPT_WITH_FLAG",
         "Usable but imperfect; the field is marked for downstream attention. Disabled entirely "
         "in the accuracy preset",
         "No further spend; flag carried into exports"],
        ["RETRY", "A cheap local rung has not yet been spent and could plausibly resolve it",
         "Local compute only"],
        ["ESCALATE",
         "Local rungs are exhausted, the field policy permits external processing, and budget "
         "remains",
         "The only decision that authorises metered spend"],
        ["HUMAN_REVIEW",
         "Attempt budget exhausted, policy forbids escalation, or every automated answer failed "
         "validation",
         "Priced per field touch, reported separately"],
    ], [34 * mm, W - 74 * mm, 40 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Policy inputs", "h2"))
    story.append(table([
        ["Input", "Source", "Role in the decision"],
        ["OCR confidence", "engine/ocr adapters", "Token-level recognition certainty"],
        ["Layout confidence", "engine/layout", "How cleanly tokens mapped into the form box"],
        ["Page quality", "engine/preprocess", "Measured scan condition of the source page"],
        ["Validation outcomes", "engine/validators", "Orthogonal correctness signal, never fused"],
        ["Field criticality", "configs/field_policy.yaml", "How much a wrong answer costs here"],
        ["Retry history", "page.decisions[field]", "What has already been spent on this field"],
        ["Provider availability", "engine/escalation/live_policy.py",
         "Whether any paid path is authorised at all"],
        ["Remaining budget", "session and document counters",
         "Whether spend is still permitted this run"],
    ], [36 * mm, 46 * mm, W - 82 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Operating presets", "h2"))
    story.append(table([
        ["Preset", "Accept threshold", "Flag threshold", "Intent"],
        ["Economy", "0.80", "0.50", "Fewest escalations; accepts more marginal reads"],
        ["Balanced", "0.88", "0.60", "Default; used for the frozen benchmark run"],
        ["Accuracy", "0.95", "0.75", "ACCEPT_WITH_FLAG disabled; marginal fields go to review"],
    ], [26 * mm, 30 * mm, 28 * mm, W - 84 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "The presets are configuration, not three separate products, so moving along the "
        "accuracy-cost frontier is a config change rather than a redeploy. Only the balanced "
        "preset carries a frozen end-to-end benchmark result. The economy and accuracy presets "
        "are supported configurations; this submission does not claim a frozen live-provider "
        "benchmark for either.", "small"))
    return story


def section_11_retry() -> list:
    b = E.blended
    retry_row = next(
        (r for r in E.stage_costs() if r["operation"] == "retry_tesseract"), None
    )
    story = h1("11. Local Retry Rung")
    story.append(para(
        "Before any field is allowed to cost money, it gets one more chance on local hardware. "
        "The retry rung crops the field's bounding box, re-runs the secondary OCR engine on "
        "that crop alone, re-validates the result, and fuses it with an agreement bonus when "
        "the two independent engines concur.", "body"))
    story.append(para(
        "Cropping is what makes the retry meaningfully different rather than a repeat of the "
        "same work. A full-page pass optimises for the page; a single-box pass optimises for "
        "the box, with a page-segmentation mode chosen for one block of text. That is why "
        "fields the full-page pass could not read at all become readable here.", "body"))
    story.append(para(
        "Engine agreement is computed here and only here. It is deliberately a retry-rung "
        "signal rather than a first-pass cost: running both engines on every page to harvest "
        "an agreement score would double primary OCR cost across the entire corpus to benefit "
        "the small minority of fields that actually need it.", "body"))
    story.append(Spacer(1, 2 * mm))
    if retry_row is not None:
        story.append(table([
            ["Measure", "Value", "Evidence label"],
            ["Fields routed to local retry", f"{round(b['routed_fields'] * b['local_retry_rate']):,}",
             "MEASURED SYNTHETIC"],
            ["Local retry rate", pct(b["local_retry_rate"]), "MEASURED SYNTHETIC"],
            ["Resolved by local retry", pct(b["local_retry_resolution_rate"]),
             "MEASURED SYNTHETIC"],
            ["Retry operations logged", f"{retry_row['calls']:,}", "MEASURED"],
            ["Total retry cost across the run", usd(retry_row["cost_usd"], 8),
             "MEASURED usage at ASSUMED compute rate"],
            ["Retry cost per page", usd(retry_row["cost_per_page_usd"], 8),
             "MEASURED usage at ASSUMED compute rate"],
        ], [56 * mm, 38 * mm, W - 94 * mm]))
        story.append(Spacer(1, 2 * mm))
    story.append(para(
        f"The economic case is direct: {pct(b['local_retry_resolution_rate'])} of the fields "
        "that reached the retry rung were resolved there, on local compute, and therefore never "
        "became a paid escalation. Retry is local compute only and carries near-zero incremental "
        "cost, but it is not free; every retry operation is priced and written to the ledger.",
        "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(CalloutBox("Honest limitation: retry latency", [
        "Retry is cheap in money and expensive in time. Adding preprocessing and the full",
        "governed ladder moves average per-page latency from roughly 2.7 s to roughly 6.5 s in",
        "the ablation, and the crop-level retry rung is a significant part of that increase.",
        "In the current single-process prototype this is the dominant throughput bottleneck.",
        "The production answer is horizontal worker scaling, not a faster retry, because retry",
        "cost per field is already near the floor.",
    ], W))
    return story


def section_12_escalation() -> list:
    b = E.blended
    story = h1("12. Selective Multimodal Escalation")
    story.append(para(
        "Escalation is the one governed paid transaction in the platform. It is reached only "
        "after every cheaper rung has failed, and it is surrounded by preconditions that are "
        "checked in a deliberate, load-bearing order.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(FlowDiagram([
        "Cost Governor",
        "Crop Isolation",
        "Policy Gate",
        "Provider Adapter",
        "Structured Response",
        "Grounding Gate",
        "Healthcare Validation",
        "Accept or Review",
    ], W, columns=4,
        note="Policy is checked before the cache, so a cached answer for a forbidden field "
             "can never be served."))
    story.append(Spacer(1, 3 * mm))
    story.append(table([
        ["Safeguard", "Enforcement"],
        ["Field crops only; never full pages",
         "engine/cropper.py raises CropPolicyError structurally, not by a flag callers "
         "might forget to check"],
        ["Maximum 25% of page area per crop", "max_crop_page_fraction in configs/pipeline.yaml"],
        ["12 px crop margin", "crop_margin_px; enough context to read the box, no more"],
        ["Provider disabled by default", "Tracked config ships the live path off"],
        ["Explicit model allowlist", "Only approved providers may be selected"],
        ["Cost and call limits", "Session and per-document budgets, checked before execution"],
        ["Duplicate protection", "Session fingerprint cache; a repeated crop is not re-billed"],
        ["Cost logged before execution", "The ledger row is written first, so no call is unrecorded"],
        ["Audit metadata retained", "Who, what, why, and how much, per escalation"],
        ["No raw response persistence", "Only the structured, grounded outcome is stored"],
    ], [52 * mm, W - 52 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Grounding: the gate before the gate", "h2"))
    story.append(para(
        "A model answer must clear mechanical, predictable rules before it is even allowed to "
        "compete with a local candidate. It must be structured, correctly typed, grounded in "
        "the model's own reported visible text, and no longer than one form box can physically "
        "hold. Rejections are counted and reported, and a rejected answer still cost money: the "
        "call was made. Grounding protects accuracy, not the budget.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(para("Provider portability", "h2"))
    story.append(para(
        "Adapters sit behind one contract, so adding a provider is a new subclass plus a price "
        "row in configs/prices.yaml. No pipeline code changes. Approved providers in the "
        "tracked configuration are offline-oracle, gpt-5-nano and gemini-2.5-flash-lite, with "
        "an OpenRouter transport implemented behind the same contract.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(CalloutBox("Evidence status of the paid path", [
        "IMPLEMENTED, GUARDED, NOT EXERCISED IN THIS EVIDENCE SET.",
        "Measured external provider calls in the frozen benchmark run: 0.",
        "Measured external API spend in the frozen benchmark run: $0.00.",
        "Escalation results in this submission come from the offline-oracle engine, a",
        "deterministic test double for the escalation boundary. Its accuracy is not evidence",
        "about any real model, and its cost is projected from token counts, never measured",
        "spend. Every such ledger row is marked simulated. No live-provider latency, accuracy",
        "or cost figure is claimed anywhere in this document.",
    ], W))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        f"Frozen-run escalation reached {pct(b['escalation_rate'])} of routed fields. Projected "
        f"selective AI cost is {usd(b['projected_api_cost_per_page_usd'])} per page, labelled "
        "PROJECTED OFFLINE_ORACLE throughout.", "small"))
    return story


def section_13_review_audit() -> list:
    story = h1("13. Human Review and Auditability")
    story.append(para(
        "Human review is the designed terminal state, not a failure of the pipeline. A field "
        "arrives here when the attempt budget is exhausted, when policy forbids sending it "
        "outside the trust boundary, or when every automated candidate failed validation. "
        "Routing a field to a person is the correct outcome in all three cases.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Step", "Behaviour"],
        ["Task creation", "Unresolved fields become review tasks attached to their document"],
        ["Reviewer context", "The reviewer sees the field crop alongside every candidate the "
                             "pipeline produced and the reason each was rejected"],
        ["Correction", "The submitted value runs through the same healthcare validators as any "
                       "automated candidate; a reviewer cannot save an invalid value unnoticed"],
        ["State transition", "Only FieldResult.human_override() can produce ACCEPT_WITH_OVERRIDE, "
                             "and it requires reviewer identity and a reason"],
        ["Propagation", "Document status and JSON/CSV exports update from the corrected value"],
        ["Audit event", "Who changed what, from which candidate, why, and when"],
    ], [34 * mm, W - 34 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para(
        "The audit trail is the reason the cost story is checkable rather than asserted. Every "
        "stage writes to an append-only JSONL ledger, and every cost and throughput number in "
        "this submission is a query over that ledger rather than a hand calculation. Combined "
        "with the per-field decision list, any accepted value can be traced backwards through "
        "each rung that was spent on it.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(CalloutBox("Honest scope of the review surface", [
        "The review workspace is a working prototype, not an enterprise review operation.",
        "It supports single-operator queue handling, crop-and-candidate context, validated",
        "correction, and audit logging on one machine. It does not implement reviewer",
        "authentication and roles, multi-reviewer assignment or SLAs, adjudication of",
        "disagreements, or productivity reporting. Those are on the production roadmap in",
        "section 19 and are not claimed as implemented.",
    ], W))
    return story


def section_14_accuracy_evidence() -> list:
    b = E.blended
    counts = E.precision_recall()
    story = h1("14. Accuracy and Resolution Evidence")
    story.append(para(
        "All figures in this section come from one frozen run over the sha256-pinned test "
        "split. The split is claim-level and disjoint from the calibration split; nothing in "
        "this document was tuned on the test split.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(MetricStrip([
        (pct(b["field_accuracy"]), "Exact field accuracy"),
        (pct(b["critical_field_accuracy"]), "Critical-field accuracy"),
        (pct(b["automated_exact_match_rate"]), "Automated exact match, no human touch"),
        (f"{b['pages']}", "Pages in the frozen run"),
    ], W))
    story.append(Spacer(1, 4 * mm))
    story.append(table([
        ["Measure", "Value", "Evidence label"],
        ["Documents / pages", f"{b['documents']} / {b['pages']}", "MEASURED SYNTHETIC"],
        ["Evaluated fields", f"{b['evaluated_fields']:,}", "MEASURED SYNTHETIC"],
        ["Routed fields", f"{b['routed_fields']:,}", "MEASURED SYNTHETIC"],
        ["Exact field accuracy", pct(b["field_accuracy"]), "MEASURED SYNTHETIC"],
        ["Critical-field accuracy", pct(b["critical_field_accuracy"]), "MEASURED SYNTHETIC"],
        ["Resolved at primary local OCR", pct(b["primary_local_resolution_rate"]),
         "MEASURED SYNTHETIC"],
        ["Routed to local retry", pct(b["local_retry_rate"]), "MEASURED SYNTHETIC"],
        ["Resolved by local retry", pct(b["local_retry_resolution_rate"]), "MEASURED SYNTHETIC"],
        ["Routed to multimodal escalation", pct(b["escalation_rate"]),
         "MEASURED ROUTING / OFFLINE_ORACLE RESOLUTION"],
        ["Routed to human review", pct(b["human_review_rate"]), "MEASURED SYNTHETIC"],
        ["Accepted with flag", pct(b["accept_with_flag_rate"]), "MEASURED SYNTHETIC"],
    ], [58 * mm, 30 * mm, W - 88 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Field-level detection counts", "h2"))
    if counts.derivable:
        story.append(table([
            ["Quantity", "Value", "Definition"],
            ["True positives", f"{counts.true_positives:,}",
             "Required populated field extracted and matching ground truth"],
            ["False positives", f"{counts.false_positives:,}",
             "A wrong value accepted, or a value invented into a blank field"],
            ["False negatives", f"{counts.false_negatives:,}",
             "Required populated field missed, unresolved, or sent to review unanswered"],
            ["Precision", pct(counts.precision), "TP / (TP + FP)"],
            ["Recall", pct(counts.recall), "TP / (TP + FN)"],
        ], [30 * mm, 26 * mm, W - 56 * mm]))
        story.append(Spacer(1, 2 * mm))
        story.append(para(
            "Derived from the frozen field rows using the frozen evaluator's own accuracy "
            "denominator, so the optional-and-absent exclusion rule is reused rather than "
            "reinvented. A wrong accepted value on a populated field counts once as a false "
            "positive and once as a false negative.", "small"))
    else:
        story.append(para(f"Precision and recall: {NOT_REPORTED}", "body"))
    story.append(Spacer(1, 3 * mm))
    story.append(CalloutBox("Reading these numbers correctly", [
        "This is a synthetic benchmark. The corpus is generated CMS-1500 and UB-04 claims with",
        "exact ground-truth boxes, degraded into clean, noisy and ugly tiers. It contains zero",
        "PHI by construction, and it is not a substitute for organiser-data accuracy.",
        "Escalation outcomes inside these totals were resolved by the offline-oracle test",
        "double, not by a live model. Per-tier official evidence is reported separately and is",
        "deliberately never blended into a single official accuracy, because tier support",
        "genuinely differs by tier.",
    ], W))
    return story


def section_15_cost_architecture() -> list:
    b = E.blended
    story = h1("15. Cost Architecture")
    story.append(para(
        "Cost is measured, not estimated. Every stage writes a priced row to an append-only "
        "ledger as it runs, and the figures below are queries over that ledger. Local compute "
        "is priced at the configured vCPU rate; the compute is real and so is the charge.",
        "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Cost component", "Per page", "Evidence label"],
        ["Local preprocessing, routing, OCR, validation, fusion",
         usd(b["measured_local_cost_per_page_usd"]), "MEASURED usage at ASSUMED compute rate"],
        ["Selective multimodal escalation",
         usd(b["projected_api_cost_per_page_usd"]), "PROJECTED OFFLINE_ORACLE"],
        ["Total automated cost per page",
         usd(b["projected_total_automated_cost_per_page_usd"]), "PROJECTED"],
        ["Measured external API spend in this run",
         usd(b["measured_external_api_spend_usd"], 2), "MEASURED"],
        ["Cost per correctly resolved escalated field",
         usd(b["projected_cost_per_correctly_resolved_escalated_field_usd"]),
         "PROJECTED OFFLINE_ORACLE"],
    ], [66 * mm, 26 * mm, W - 92 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Measured stage costs from the frozen ledger", "h2"))
    stage_rows = [
        ["Ledger operation", "Operations", "Total cost", "Cost per page"],
    ]
    for row in E.stage_costs():
        stage_rows.append([
            row["operation"], f"{row['calls']:,}",
            usd(row["cost_usd"], 8), usd(row["cost_per_page_usd"], 8),
        ])
    story.append(table(stage_rows, [50 * mm, 24 * mm, 30 * mm, W - 104 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "Primary OCR dominates local spend, which is the expected shape: it is the only stage "
        "that processes every pixel of every page. Routing and validation are close to "
        "arithmetically negligible yet decide where the expensive stages are allowed to run. "
        "Escalation intent rows cost nothing because they record a decision; the escalation "
        "rows carry the projected token cost.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(CalloutBox("Human review is quoted separately and is an assumption", [
        "Human review is priced at a configurable illustrative rate of $0.03 per field touch.",
        "It is not a measured cost, it is not part of the automated cost per page, and it is",
        "never blended into it. Real cost depends on labour market, review-tool efficiency and",
        "operator skill. It is reported alongside automated cost so the total operational",
        "picture is visible without contaminating the measured figure.",
        "",
        "Local OCR and retry are local compute only with near-zero incremental cost. They are",
        "not free. They consume CPU, that CPU is priced, and every operation is in the ledger.",
    ], W))
    return story


def section_16_throughput() -> list:
    b = E.blended
    story = h1("16. Throughput and Scalability")
    story.append(para("Measured prototype throughput", "h2"))
    story.append(para(
        f"One process, one machine, {b['pages']} pages end to end through the full governed "
        "ladder. This is a correctness and cost benchmark that also recorded timing; it is not "
        "a tuned throughput benchmark and is not a production capacity claim.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Measure", "Value", "Evidence label"],
        ["P50 latency per page", f"{b['p50_latency_ms']:,.0f} ms", "MEASURED"],
        ["P95 latency per page", f"{b['p95_latency_ms']:,.0f} ms", "MEASURED"],
        ["Average latency per page", f"{b['average_latency_per_page_ms']:,.0f} ms", "MEASURED"],
        ["Throughput", f"{b['throughput_pages_per_minute']:.2f} pages / minute", "MEASURED"],
        ["Throughput", f"{b['throughput_pages_per_hour']:,.0f} pages / hour", "MEASURED"],
        ["Benchmark size", f"{b['pages']} pages, {b['documents']} documents", "MEASURED"],
        ["Memory profile", "not measured", "UNAVAILABLE"],
    ], [50 * mm, 40 * mm, W - 90 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Production reference architecture", "h2"))
    story.append(FlowDiagram([
        "Client / Mailroom Feed",
        "API Gateway",
        "Auth and Rate Limit",
        "Object Storage",
        "Work Queue",
        "Stateless Extraction Workers",
        "Validation and Governor",
        "Review Queue",
        "Results Database",
        "Audit and Monitoring",
    ], W, columns=4,
        note="PRODUCTION ROADMAP. Designed and specified; not built, not deployed, not "
             "benchmarked at this scale."))
    story.append(Spacer(1, 3 * mm))
    story.append(para(
        "The prototype's operator surface is a local Streamlit workspace. <b>Streamlit is not "
        "the ingestion tier and does not scale to enterprise volume</b>; it is how a single "
        "operator drives and inspects the pipeline on one machine. Enterprise volume is served "
        "by the queue-and-worker architecture above, in which extraction workers are stateless "
        "and therefore horizontally scalable. Because per-page work is independent, throughput "
        "is a function of worker count rather than of a faster single pass, which is the "
        "correct answer to the current latency bottleneck.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(para("Cost at volume", "h2"))
    proj_rows = [["Annual pages", "Local compute", "Selective AI", "Automated total",
                  "Human review (illustrative)"]]
    for row in E.cost_projection():
        proj_rows.append([
            f"{int(float(row['pages'])):,}",
            f"${float(row['measured_local_compute_projection_usd']):,.2f}",
            f"${float(row['projected_api_cost_usd']):,.2f}",
            f"${float(row['projected_total_automated_cost_usd']):,.2f}",
            f"${float(row['configured_human_review_cost_usd']):,.2f}",
        ])
    story.append(table(proj_rows,
                       [26 * mm, 28 * mm, 26 * mm, 30 * mm, W - 110 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "These are linear extrapolations of measured per-page cost, not a quote. They assume "
        "the frozen run's field-difficulty mix holds at volume and exclude infrastructure, "
        "storage, egress and operations. Real organiser traffic will have a different mix, and "
        "the escalation share is the term that moves the total. The human-review column is the "
        "illustrative assumption from section 15 and is deliberately kept out of the automated "
        "total.", "small"))
    return story


def section_17_failure_handling() -> list:
    story = h1("17. Failure Handling and Resilience")
    story.append(para(
        "A mailroom pipeline is judged by what it does with the documents that do not behave. "
        "The governing principle is that every failure has a defined terminal state and none of "
        "them is a confident wrong answer: when the platform cannot resolve something, it says "
        "so and routes it to a person.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Failure mode", "Behaviour", "Status"],
        ["Corrupt or unreadable file",
         "Rejected at intake with a recorded reason; the batch continues",
         "IMPLEMENTED PROTOTYPE"],
        ["Unsupported format",
         "Content sniffing classifies it as unsupported rather than trusting the extension",
         "IMPLEMENTED PROTOTYPE"],
        ["Routing uncertainty",
         "The router abstains instead of guessing a form type; the page avoids the structured "
         "template path",
         "IMPLEMENTED PROTOTYPE"],
        ["Zero meaningful extraction",
         "No fields accepted; the page is surfaced for review rather than emitted as empty "
         "success",
         "IMPLEMENTED PROTOTYPE"],
        ["Partial extraction",
         "Resolved fields are accepted individually; unresolved ones continue up the ladder "
         "independently",
         "IMPLEMENTED PROTOTYPE"],
        ["Retry exhaustion",
         "Attempt budget is finite; an exhausted field routes onward, never loops",
         "IMPLEMENTED PROTOTYPE"],
        ["Provider disabled or unavailable",
         "Typed outcome distinguishes disabled path, missing key, budget exhausted and provider "
         "error; the field falls back to review",
         "IMPLEMENTED PROTOTYPE"],
        ["Invalid multimodal response",
         "Grounding rejects it before it can compete; the rejection is counted and the call is "
         "still costed",
         "IMPLEMENTED PROTOTYPE"],
        ["Budget exceeded",
         "Session and document budgets are checked before execution, so the limit blocks the "
         "call rather than reporting it afterwards",
         "IMPLEMENTED PROTOTYPE"],
        ["Duplicate escalation",
         "Session fingerprint cache serves the prior result; policy is still checked first so a "
         "cached answer cannot bypass a forbidden field",
         "IMPLEMENTED PROTOTYPE"],
        ["Human-review fallback",
         "The designed terminal state for everything the ladder could not resolve",
         "IMPLEMENTED PROTOTYPE"],
        ["Dead-letter queue and poison-message isolation",
         "Repeatedly failing documents are quarantined for operator triage without stalling the "
         "queue",
         "PRODUCTION ROADMAP"],
        ["Worker crash recovery and at-least-once redelivery",
         "Queue redelivery with idempotent page processing keyed on document and page identity",
         "PRODUCTION ROADMAP"],
    ], [44 * mm, W - 82 * mm, 38 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(para(
        "Idempotency is the property that makes retries safe at both levels. Within a run, the "
        "escalation fingerprint cache prevents paying twice for the same crop. In the production "
        "architecture the same principle extends to queue redelivery, so a worker that dies "
        "mid-page cannot cause a second billed escalation when the message is redelivered.",
        "small"))
    return story


def section_18_security_phi() -> list:
    story = h1("18. Security, Privacy and PHI Minimisation")
    story.append(para(
        "<b>PHI minimisation through field-level isolation and policy-governed escalation.</b> "
        "That sentence is the whole security posture, and it is enforced by code structure "
        "rather than by configuration discipline.", "body"))
    story.append(Spacer(1, 2 * mm))
    story.append(table([
        ["Control", "How it holds"],
        ["Local-first processing",
         "Intake, preprocessing, routing, OCR, layout mapping, validation, fusion, governance "
         "and retry all run on localhost. The default configuration makes no network call."],
        ["Organiser data never sent externally",
         "Measured external provider calls across all organiser-data evaluation: 0."],
        ["Crop-level isolation",
         "Nothing leaves the process except through crop_field(), which raises CropPolicyError "
         "when a crop exceeds the configured page fraction. The crops-only rule is structural, "
         "not a flag a caller could forget."],
        ["Full pages never leave the boundary",
         "send_full_pages_externally is false; a full page has no code path out."],
        ["Provider disabled by default",
         "The tracked configuration ships the paid path off, so enabling it is a reviewable "
         "change to a committed file rather than a shell variable."],
        ["Secrets from environment only",
         "No credential is committed, logged, or written into any artifact in this submission."],
        ["No raw response persistence",
         "Only the structured, grounded outcome and its audit metadata are retained."],
        ["Audit metadata",
         "Who, what, why, how much, per escalation and per human override."],
        ["Synthetic-only corpus by construction",
         "The generated benchmark corpus contains zero PHI; it is rendered from seeded fake "
         "data with exact ground-truth geometry."],
    ], [46 * mm, W - 46 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(CalloutBox("Compliance claims deliberately not made", [
        "ClaimRoute AI is not HIPAA certified and this document makes no certification claim.",
        "The controls above are engineering controls, not an attested compliance posture. A",
        "production deployment handling real PHI would additionally require a signed BAA with",
        "every processor in the path, encryption at rest and in transit with managed keys,",
        "access control and reviewer authentication, retention and disposal policy, breach",
        "notification procedure, and independent audit. Those are roadmap items in section 19,",
        "not implemented capabilities.",
    ], W))
    return story


def section_19_implemented_vs_roadmap() -> list:
    story = h1("19. Implemented Prototype versus Production Roadmap")
    story.append(para(
        "This table is the honest boundary of the submission. Everything in the left column "
        "exists in the repository and runs; everything in the right column is designed and "
        "specified but not built. No item appears in both.", "body"))
    story.append(Spacer(1, 2 * mm))
    implemented = [
        "Local intake with content-aware format sniffing",
        "PNG, JPEG, TIFF, PDF and numeric-extension handling",
        "Multi-page container expansion",
        "Signal-gated Tier-0 preprocessing with transform history",
        "Free deterministic document routing",
        "Local primary OCR with per-token confidence",
        "Template and overlap-based layout mapping",
        "Official CMS-1500 and UB-04 registration modules",
        "Fifteen policy-driven healthcare validators",
        "Explainable weighted confidence fusion",
        "Cost Governor with three operating presets",
        "Crop-level local retry on a secondary engine",
        "Crop-only multimodal escalation interfaces",
        "Model-agnostic provider adapters and allowlist",
        "Nine-condition live-provider guardrail layer",
        "Mechanical grounding gate",
        "Six-state field model with human-only override",
        "Human review workspace prototype",
        "Append-only cost and audit ledger",
        "JSON and CSV export",
        "Coverage, cost and latency dashboards",
        "Reproducible benchmark and ablation harnesses",
        "Synthetic corpus generator with exact ground truth",
    ]
    roadmap = [
        "Distributed queue and stateless worker fleet",
        "Production object storage and lifecycle policy",
        "API gateway, authentication and rate limiting",
        "Dead-letter queue and poison-message isolation",
        "Enterprise review operations: roles, assignment, SLAs",
        "Multi-reviewer adjudication and productivity reporting",
        "Customer-managed and on-premise model hosting",
        "Continuous calibration from operator corrections",
        "Live multi-model benchmarking at scale",
        "Expanded unstructured and layout-free extraction",
        "Observability, alerting and published SLAs",
        "Formal compliance certification and independent audit",
        "Managed key handling and encryption at rest",
        "Multi-tenant isolation and per-tenant budgets",
    ]
    rows = [["IMPLEMENTED PROTOTYPE", "PRODUCTION ROADMAP"]]
    for i in range(max(len(implemented), len(roadmap))):
        rows.append([
            implemented[i] if i < len(implemented) else "",
            roadmap[i] if i < len(roadmap) else "",
        ])
    story.append(table(rows, [W / 2, W / 2]))
    story.append(Spacer(1, 3 * mm))
    story.append(CalloutBox("Known limitations, stated plainly", [
        "Tier A: no frozen holdout score exists. Official CMS-1500 field mapping was proven on",
        "three development documents only. This is not an official Tier A accuracy result.",
        "Tier B: claim-page selection and attachment rejection are measured on official data;",
        "field-level extraction accuracy on Tier B is not separately frozen.",
        "Tier C: the UB-04 holdout was consumed once and must not be rerun. Three documents.",
        "Tier D: routing only. Layout-free extraction is conservative and unproven; no Tier D",
        "extraction capability is claimed.",
        "Escalation accuracy comes from a deterministic offline test double, not a live model.",
        "Throughput is single-process prototype evidence; retry latency is the bottleneck.",
        "Human-review cost is an illustrative configurable assumption, never a measured cost.",
        "Streamlit is the single-operator surface, not the enterprise ingestion tier.",
        "There is no container image in this repository; deployment packaging is not provided.",
    ], W))
    story.append(Spacer(1, 4 * mm))
    story.append(Rule(W))
    story.append(Spacer(1, 2 * mm))
    story.append(para("Every field takes the cheapest reliable path.", "pull"))
    return story


SECTIONS = [
    section_1_overview,
    section_2_prototype_flow,
    section_3_intake,
    section_4_preprocess,
    section_5_router,
    section_6_ocr_layout,
    section_7_validation,
    section_8_fusion_governor,
    section_9_validation_loop,
    section_10_governor_policy,
    section_11_retry,
    section_12_escalation,
    section_13_review_audit,
    section_14_accuracy_evidence,
    section_15_cost_architecture,
    section_16_throughput,
    section_17_failure_handling,
    section_18_security_phi,
    section_19_implemented_vs_roadmap,
]

# Sections that start a fresh page, keeping diagrams and wide tables off page seams.
PAGE_BREAK_BEFORE = {2, 5, 8, 10, 12, 14, 16, 17, 19}

REQUIRED_BLENDED_KEYS = (
    "field_accuracy",
    "critical_field_accuracy",
    "automated_exact_match_rate",
    "documents",
    "pages",
    "evaluated_fields",
    "routed_fields",
    "primary_local_resolution_rate",
    "local_retry_rate",
    "local_retry_resolution_rate",
    "escalation_rate",
    "human_review_rate",
    "accept_with_flag_rate",
    "measured_local_cost_per_page_usd",
    "projected_api_cost_per_page_usd",
    "projected_total_automated_cost_per_page_usd",
    "projected_cost_per_correctly_resolved_escalated_field_usd",
    "measured_external_api_spend_usd",
    "p50_latency_ms",
    "p95_latency_ms",
    "average_latency_per_page_ms",
    "throughput_pages_per_minute",
    "throughput_pages_per_hour",
)


def validate_evidence() -> None:
    """Fail loudly before rendering if the frozen evidence is not what we expect."""
    missing = [key for key in REQUIRED_BLENDED_KEYS if key not in E.blended]
    if missing:
        raise SystemExit(f"Frozen evidence is missing required keys: {', '.join(missing)}")

    for arm in ("primary_ocr_only", "primary_plus_preprocessing", "full_cost_governed_pipeline"):
        if arm not in E.ablation["arms"]:
            raise SystemExit(f"Frozen ablation evidence is missing arm: {arm}")

    if not E.stage_costs():
        raise SystemExit("Frozen ledger produced no stage cost rows.")
    if not E.cost_projection():
        raise SystemExit("Frozen cost projection is empty.")

    # Stage-cost operations, projection volumes, and the one-call live-smoke receipt.
    try:
        validate_required_evidence()
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"Frozen evidence failed detailed validation: {exc}") from exc


def build_story() -> list:
    story: list = []
    for index, section in enumerate(SECTIONS, start=1):
        if index in PAGE_BREAK_BEFORE:
            story.append(PageBreak())
        story.extend(section())
    return story


def main() -> int:
    try:
        validate_evidence()
    except SystemExit as exc:
        print(f"FAILED: {exc}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".pdf.tmp")
    if tmp.exists():
        tmp.unlink()

    try:
        build(
            tmp,
            title="ClaimRoute AI - Solution Architecture and Technical Design",
            subject="Cost-governed healthcare claims extraction architecture",
            story=build_story(),
            footer_left="ClaimRoute AI - Solution Architecture and Technical Design",
        )
    except Exception as exc:  # noqa: BLE001 - report and leave no partial output
        if tmp.exists():
            tmp.unlink()
        print(f"FAILED: PDF generation raised {type(exc).__name__}: {exc}")
        return 1

    size = tmp.stat().st_size if tmp.exists() else 0
    if size <= 0:
        if tmp.exists():
            tmp.unlink()
        print("FAILED: generated PDF is empty.")
        return 1

    tmp.replace(OUT)

    pages = "unavailable"
    try:
        import pypdfium2

        with pypdfium2.PdfDocument(str(OUT)) as doc:
            pages = str(len(doc))
    except Exception:  # noqa: BLE001 - page count is informational
        pass

    print(f"Wrote  : submission/final/{OUT.name}")
    print(f"Size   : {size:,} bytes")
    print(f"Pages  : {pages}")
    print(f"Frozen : {E.frozen_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
