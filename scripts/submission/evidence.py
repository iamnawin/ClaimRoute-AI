"""Single evidence loader for every generated submission artifact.

Both PDF generators and the benchmark workbook read their numbers from here, and this
module reads only committed frozen evidence under ``eval/frozen/`` plus the PHI-safe
official receipts under ``eval/results/`` and ``eval/official/results/``.

The rule this enforces: a number that appears in a deliverable is produced by a function
in this file, never typed into a document by hand. If a value cannot be derived from a
committed artifact, the accessor returns an explicit unavailable marker instead of a
plausible-looking number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN = REPO_ROOT / "eval" / "frozen"
RESULTS = REPO_ROOT / "eval" / "results"
OFFICIAL_RESULTS = REPO_ROOT / "eval" / "official" / "results"

# Returned wherever the organiser asked for a metric that the frozen evidence cannot
# support. Never replace this with an estimate.
NOT_METERED = "NOT SEPARATELY METERED"
NOT_REPORTED = (
    "NOT REPORTED - FROZEN RESULT ARTIFACT DOES NOT PROVIDE SUFFICIENT TP/FP/FN COUNTS"
)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@dataclass(frozen=True)
class PrecisionRecall:
    """Field-level detection counts derived from the frozen benchmark rows.

    Definitions follow the submission brief:

    - true positive: a required populated field was extracted and matched ground truth
    - false positive: a wrong value was accepted, or a value was produced for a field
      whose ground truth is blank
    - false negative: a required populated field was missed, left unresolved, or routed
      to human review without an automated answer

    A wrong accepted value on a populated field counts once as a false positive (a wrong
    value was emitted) and once as a false negative (the true value was not captured).
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    populated_fields: int
    blank_ground_truth_fields: int

    @property
    def precision(self) -> float:
        return self.true_positives / (self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        return self.true_positives / (self.true_positives + self.false_negatives)

    @property
    def derivable(self) -> bool:
        return (self.true_positives + self.false_positives) > 0 and (
            self.true_positives + self.false_negatives
        ) > 0


class Evidence:
    """Lazy accessor over the committed frozen and official evidence files."""

    def __init__(self) -> None:
        self._summary: dict | None = None
        self._throughput: dict | None = None
        self._ablation: dict | None = None
        self._manifest: dict | None = None
        self._rows: list[dict] | None = None
        self._ledger: list[dict] | None = None
        self._precision_recall: PrecisionRecall | None = None

    # -- raw frozen artifacts -------------------------------------------------

    @property
    def summary(self) -> dict:
        if self._summary is None:
            self._summary = _load_json(FROZEN / "final_benchmark_summary.json")
        return self._summary

    @property
    def throughput(self) -> dict:
        if self._throughput is None:
            self._throughput = _load_json(FROZEN / "throughput_summary.json")
        return self._throughput

    @property
    def ablation(self) -> dict:
        if self._ablation is None:
            self._ablation = _load_json(FROZEN / "ablation_summary.json")
        return self._ablation

    @property
    def manifest(self) -> dict:
        if self._manifest is None:
            self._manifest = _load_json(FROZEN / "frozen_manifest.json")
        return self._manifest

    @property
    def rows(self) -> list[dict]:
        if self._rows is None:
            self._rows = _load_jsonl(FROZEN / "final_benchmark_rows.jsonl")
        return self._rows

    @property
    def ledger(self) -> list[dict]:
        if self._ledger is None:
            self._ledger = _load_jsonl(FROZEN / "final_benchmark_ledger.jsonl")
        return self._ledger

    @property
    def blended(self) -> dict:
        return self.summary["blended"]

    @property
    def per_tier(self) -> dict:
        return self.summary["per_tier"]

    @property
    def integrity(self) -> dict:
        return self.summary["integrity"]

    @property
    def frozen_commit(self) -> str:
        return self.summary["frozen_git_commit"]

    # -- derived metrics ------------------------------------------------------

    def precision_recall(self) -> PrecisionRecall:
        """Derive TP/FP/FN from the frozen field rows.

        Only rows the frozen evaluator itself included in the accuracy denominator are
        counted, so this reuses the frozen optional/absent exclusion rule rather than
        inventing a second one.
        """
        if self._precision_recall is not None:
            return self._precision_recall

        true_positives = false_positives = false_negatives = 0
        populated = blank = 0

        for row in self.rows:
            if not row.get("included_in_accuracy"):
                continue
            ground_truth = (row.get("ground_truth") or "").strip()
            final_value = (row.get("final_value") or "").strip()

            if not ground_truth:
                blank += 1
                # A value invented into a legitimately blank field is a false positive.
                if final_value:
                    false_positives += 1
                continue

            populated += 1
            if row.get("final_state") == "HUMAN_REVIEW":
                false_negatives += 1
            elif final_value and row.get("resolved_correctly"):
                true_positives += 1
            elif final_value:
                false_positives += 1
                false_negatives += 1
            else:
                false_negatives += 1

        self._precision_recall = PrecisionRecall(
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            populated_fields=populated,
            blank_ground_truth_fields=blank,
        )
        return self._precision_recall

    def stage_costs(self) -> list[dict]:
        """Per-stage measured cost from the frozen append-only ledger.

        Returns one row per ledger operation with call count, total cost, and cost per
        page. These are measured local-compute allocations at the configured price, not
        an external invoice.
        """
        pages = self.blended["pages"]
        totals: dict[str, dict] = {}
        for entry in self.ledger:
            operation = entry.get("operation")
            if operation is None:
                continue
            bucket = totals.setdefault(
                operation, {"operation": operation, "calls": 0, "cost_usd": 0.0}
            )
            bucket["calls"] += 1
            bucket["cost_usd"] += entry.get("cost_usd") or 0.0

        rows = []
        for bucket in totals.values():
            bucket["cost_per_page_usd"] = bucket["cost_usd"] / pages
            rows.append(bucket)
        rows.sort(key=lambda item: item["cost_usd"], reverse=True)
        return rows

    def resolution_funnel(self) -> list[dict]:
        """Applicable fields -> primary -> retry -> escalation -> human review."""
        blended = self.blended
        routed = blended["routed_fields"]
        return [
            {
                "stage": "Applicable routed fields",
                "fields": routed,
                "share_of_routed": 1.0,
                "label": "MEASURED SYNTHETIC",
            },
            {
                "stage": "Resolved at primary local OCR",
                "fields": round(routed * blended["primary_local_resolution_rate"]),
                "share_of_routed": blended["primary_local_resolution_rate"],
                "label": "MEASURED SYNTHETIC",
            },
            {
                "stage": "Routed to local retry",
                "fields": round(routed * blended["local_retry_rate"]),
                "share_of_routed": blended["local_retry_rate"],
                "label": "MEASURED SYNTHETIC",
            },
            {
                "stage": "Routed to multimodal escalation",
                "fields": round(routed * blended["escalation_rate"]),
                "share_of_routed": blended["escalation_rate"],
                "label": "MEASURED ROUTING / OFFLINE_ORACLE RESOLUTION",
            },
            {
                "stage": "Routed to human review",
                "fields": round(routed * blended["human_review_rate"]),
                "share_of_routed": blended["human_review_rate"],
                "label": "MEASURED SYNTHETIC",
            },
        ]

    def cost_projection(self) -> list[dict]:
        """Volume projections, read from the frozen projection CSV."""
        path = FROZEN / "cost_projection.csv"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        header = lines[0].split(",")
        rows = []
        for line in lines[1:]:
            rows.append(dict(zip(header, line.split(","))))
        return rows

    def frontier(self) -> list[dict]:
        """Day 9 replay-calibration accuracy-cost frontier.

        This is replay evidence over recorded candidates. It is not the frozen test
        result and not live-provider performance.
        """
        path = RESULTS / "day9_accuracy_cost_frontier.csv"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        header = lines[0].split(",")
        return [dict(zip(header, line.split(","))) for line in lines[1:]]

    def live_openrouter_smoke(self) -> dict:
        """PHI-safe receipt for the single synthetic crop-level provider smoke test."""
        return _load_json(RESULTS / "openrouter_qwen37_flash_smoke.json")

    # -- official (non-synthetic) evidence -------------------------------------

    def official_ub04_holdout(self) -> dict:
        return _load_json(RESULTS / "official_ub04_holdout_summary.json")

    def official_sample(self) -> dict:
        return _load_json(OFFICIAL_RESULTS / "official_sample_summary.json")

    def official_tier_rows(self) -> list[dict]:
        """Per-tier official evidence, deliberately never blended into one score.

        Tier support differs by tier, so a single combined official accuracy would be
        misleading. Each row carries its own support classification.
        """
        sample = self.official_sample()
        holdout = self.official_ub04_holdout()
        per_tier = sample["per_tier"]
        tier_b = per_tier["B"]

        return [
            {
                "tier": "A",
                "document": "Machine-printed CMS-1500, single page, no attachments",
                "support": "DEVELOPMENT_PROOF",
                "containers": per_tier["A"]["containers"],
                "pages": per_tier["A"]["pages"],
                "accuracy": NOT_REPORTED,
                "evidence": (
                    "Structured extraction on the organiser layout measured 0/299 exact "
                    "fields in the full-sample run; official CMS-1500 registration and "
                    "field mapping were subsequently built and proven on three "
                    "development documents only."
                ),
                "holdout_used": "No - Tier A holdout remains unopened",
                "external_calls": 0,
                "limitation": (
                    "No frozen Tier A holdout score exists. Development-only evidence; "
                    "do not present as an official Tier A accuracy result."
                ),
            },
            {
                "tier": "B",
                "document": "Machine-printed CMS-1500 plus attachments; score the claim page only",
                "support": "PARTIAL_EVIDENCE",
                "containers": tier_b["containers"],
                "pages": tier_b["pages"],
                "accuracy": (
                    f"Claim-page selection {tier_b['claim_page_identification']['correct']}"
                    f"/{tier_b['claim_page_identification']['evaluable']}; "
                    f"attachment rejection {tier_b['attachment_rejection']['correct']}"
                    f"/{tier_b['attachment_rejection']['expected_attachments']}"
                ),
                "evidence": "Page-selection and attachment-rejection are measured on official data",
                "holdout_used": "No - deterministic linked evaluable items",
                "external_calls": 0,
                "limitation": (
                    "Routing/page-selection is proven; field-level extraction accuracy "
                    "on Tier B is not separately frozen. One ambiguous item excluded."
                ),
            },
            {
                "tier": "C",
                "document": "Machine-printed UB-04, single page",
                "support": "FULLY_BENCHMARKED",
                "containers": holdout["documents"],
                "pages": holdout["documents"],
                "accuracy": (
                    f"Primary normalized {holdout['primary_correct']}"
                    f"/{holdout['primary_denominator']} "
                    f"({holdout['primary_correct'] / holdout['primary_denominator']:.3%})"
                ),
                "evidence": (
                    f"One-time consumed holdout; extended coverage "
                    f"{holdout['extended_correct']}/{holdout['extended_denominator']}"
                ),
                "holdout_used": "Yes - consumed once, must not be rerun",
                "external_calls": holdout["external_provider_calls"],
                "limitation": (
                    "Provisional visible-and-supported denominator adopted because "
                    "organiser clarification was unavailable. Three documents. This is "
                    "not a universal UB-04 benchmark."
                ),
            },
            {
                "tier": "D",
                "document": "Unstructured layout; specific fields extracted from available information",
                "support": "ROUTING_ONLY",
                "containers": per_tier["D"]["containers"],
                "pages": per_tier["D"]["pages"],
                "accuracy": NOT_REPORTED,
                "evidence": (
                    f"{per_tier['D']['correct_fields']}/{per_tier['D']['evaluated_fields']} "
                    "exact fields in the conservative full-sample run"
                ),
                "holdout_used": "No",
                "external_calls": 0,
                "limitation": (
                    "Layout-free extraction is conservative and unproven. Do not claim "
                    "Tier D extraction capability."
                ),
            },
        ]

    # -- executive metric block ------------------------------------------------

    def executive_metrics(self) -> list[tuple[str, object, str]]:
        """(metric, value, evidence classification) for the Executive Metrics sheet."""
        blended = self.blended
        throughput = self.throughput
        counts = self.precision_recall()
        total_seconds = throughput["total_elapsed_ms"] / 1000.0

        rows: list[tuple[str, object, str]] = [
            ("Benchmark name", "ClaimRoute AI frozen synthetic test split", "MEASURED"),
            ("Evidence scope", "Synthetic CMS-1500 / UB-04, clean+noisy+ugly", "SYNTHETIC"),
            ("Frozen git commit", self.frozen_commit, "MEASURED"),
            ("Operating mode", self.summary["operating_mode"], "MEASURED"),
            ("Total documents", blended["documents"], "MEASURED SYNTHETIC"),
            ("Total pages", blended["pages"], "MEASURED SYNTHETIC"),
            ("Evaluated fields", blended["evaluated_fields"], "MEASURED SYNTHETIC"),
            ("Routed fields", blended["routed_fields"], "MEASURED SYNTHETIC"),
            ("Exact field accuracy", blended["field_accuracy"], "MEASURED SYNTHETIC"),
            (
                "Critical-field accuracy",
                blended["critical_field_accuracy"],
                "MEASURED SYNTHETIC",
            ),
        ]

        if counts.derivable:
            rows.extend(
                [
                    ("Precision", counts.precision, "MEASURED SYNTHETIC (derived)"),
                    ("Recall", counts.recall, "MEASURED SYNTHETIC (derived)"),
                    ("True positives", counts.true_positives, "MEASURED SYNTHETIC (derived)"),
                    ("False positives", counts.false_positives, "MEASURED SYNTHETIC (derived)"),
                    ("False negatives", counts.false_negatives, "MEASURED SYNTHETIC (derived)"),
                ]
            )
        else:
            rows.extend(
                [("Precision", NOT_REPORTED, "UNAVAILABLE"), ("Recall", NOT_REPORTED, "UNAVAILABLE")]
            )

        rows.extend(
            [
                ("Human-review rate", blended["human_review_rate"], "MEASURED SYNTHETIC"),
                ("Accept-with-flag rate", blended["accept_with_flag_rate"], "MEASURED SYNTHETIC"),
                ("Total processing time (s)", round(total_seconds, 3), "MEASURED"),
                ("Average latency (ms/page)", blended["average_latency_per_page_ms"], "MEASURED"),
                ("P50 latency (ms)", blended["p50_latency_ms"], "MEASURED"),
                ("P95 latency (ms)", blended["p95_latency_ms"], "MEASURED"),
                (
                    "Pages per second",
                    round(blended["throughput_pages_per_minute"] / 60.0, 6),
                    "MEASURED",
                ),
                ("Pages per minute", blended["throughput_pages_per_minute"], "MEASURED"),
                (
                    "Measured local cost per page (USD)",
                    blended["measured_local_cost_per_page_usd"],
                    "MEASURED usage at ASSUMED compute rate",
                ),
                (
                    "Measured external API spend (USD)",
                    blended["measured_external_api_spend_usd"],
                    "MEASURED",
                ),
                (
                    "Measured external API calls",
                    blended["measured_external_api_calls"],
                    "MEASURED",
                ),
                (
                    "Projected selective AI cost per page (USD)",
                    blended["projected_api_cost_per_page_usd"],
                    "PROJECTED OFFLINE_ORACLE",
                ),
                (
                    "Projected automated total cost per page (USD)",
                    blended["projected_total_automated_cost_per_page_usd"],
                    "PROJECTED",
                ),
            ]
        )
        return rows


EVIDENCE = Evidence()
