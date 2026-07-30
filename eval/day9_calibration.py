"""Day 9 unresolved-field analysis and replay-only operating-mode calibration.

Replays Day 8 synthetic calibration evidence. It does not rerun OCR, call an
external provider, or infer outcomes for fields without a recorded candidate.

    python -m eval.day9_calibration
"""
from __future__ import annotations

import csv
import itertools
import json
import re
from collections import Counter
from pathlib import Path

import yaml

from engine.governor import field_policy
from engine.validators import validate_field

RESULTS = Path("eval/results")
ROWS = RESULTS / "day8_escalation_rows.jsonl"
PAGES = RESULTS / "day8_escalation_pages.jsonl"
CONFIG = Path("configs/operating_modes.yaml")
FAILURE_JSON = RESULTS / "day9_failure_analysis.json"
FAILURE_CSV = RESULTS / "day9_failure_analysis.csv"
CALIBRATION_CSV = RESULTS / "day9_calibration_rows.csv"
SUMMARY_JSON = RESULTS / "day9_calibration_summary.json"
FRONTIER_CSV = RESULTS / "day9_accuracy_cost_frontier.csv"
REPORT_MD = Path("docs/evaluation/day9_failure_analysis.md")
TERMINAL = {"ACCEPT", "ACCEPT_WITH_FLAG"}
CRITICALITIES = {"high", "med", "low"}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def exact(value, truth) -> bool:
    return norm(value) == norm(truth)


def load_modes(path: Path = CONFIG) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    modes = data.get("modes", {})
    required = {
        "local_accept_confidence", "multimodal_accept_confidence",
        "paid_escalation_criticalities", "accept_with_flag_criticalities",
        "retry_before_escalation", "allow_optional_escalation",
    }
    if not modes:
        raise ValueError("operating modes config has no modes")
    for name, mode in modes.items():
        missing = required - mode.keys()
        if missing:
            raise ValueError(f"mode {name!r} missing {sorted(missing)}")
        for key in ("local_accept_confidence", "multimodal_accept_confidence"):
            if not 0 <= float(mode[key]) <= 1:
                raise ValueError(f"mode {name!r} has invalid {key}")
        if not set(mode["paid_escalation_criticalities"]) <= CRITICALITIES:
            raise ValueError(f"mode {name!r} has invalid criticality")
        if mode["allow_optional_escalation"]:
            raise ValueError("optional-field escalation is prohibited")
    return modes


def _point_id(local: float, model: float, paid: list[str], flagged: bool) -> str:
    return (f"local-{local:.2f}_model-{model:.2f}_paid-{'-'.join(paid)}_"
            f"flags-{'on' if flagged else 'off'}")


def build_sweep(sweep: dict) -> list[dict]:
    points = []
    products = itertools.product(
        sorted(set(map(float, sweep["local_accept_confidence"]))),
        sorted(set(map(float, sweep["multimodal_accept_confidence"]))),
        sorted({tuple(v) for v in sweep["paid_escalation_criticalities"]}),
        sorted(set(map(bool, sweep["accept_with_flag"]))),
    )
    for local, model, paid, flagged in products:
        point = {
            "local_accept_confidence": local,
            "multimodal_accept_confidence": model,
            "paid_escalation_criticalities": list(paid),
            "accept_with_flag_criticalities": ["low", "med"] if flagged else [],
            "retry_before_escalation": True,
            "allow_optional_escalation": False,
        }
        point["point_id"] = _point_id(local, model, list(paid), flagged)
        points.append(point)
    return sorted(points, key=lambda p: p["point_id"])


def _local_candidate(row: dict) -> tuple[object, float]:
    """Best reconstructable pre-escalation candidate from recorded attempts."""
    decision = row.get("escalation_decision", "")
    if decision.startswith("keep_primary") or decision == "rejected_by_grounding":
        value = row.get("final_value")
        if exact(value, row.get("retry_candidate")):
            return value, float(row.get("retry_confidence") or 0)
        return value, float(row.get("primary_confidence") or 0)
    primary = row.get("primary_candidate")
    retry = row.get("retry_candidate")
    primary_conf = float(row.get("primary_confidence") or 0)
    retry_conf = float(row.get("retry_confidence") or 0)
    if retry and (not primary or retry_conf > primary_conf + 0.05):
        return retry, retry_conf
    return primary, primary_conf


def _fails_validation(field_name: str, value) -> bool:
    stamps = validate_field(field_name, value, {field_name: value})
    return any(stamp.verdict.value == "FAIL" for stamp in stamps)


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def simulate(rows: list[dict], pages: list[dict], mode: dict) -> dict:
    """Replay one mode against the observed Day 8 escalation cohort."""
    total_fields = sum(int(page["total_fields"]) for page in pages)
    page_count = len(pages)
    local_cost = sum(float(page["local_cost_usd"]) for page in pages)
    final_row_correct = sum(bool(row["resolved_correctly"]) for row in rows)
    fixed_correct = sum(int(page["correct_fields"]) for page in pages) - final_row_correct
    critical_rows = [row for row in rows if row["field_criticality"] == "high"]
    fixed_critical_total = (sum(int(page["critical_fields"]) for page in pages)
                            - len(critical_rows))
    fixed_critical_correct = (
        sum(int(page["critical_correct_fields"]) for page in pages)
        - sum(bool(row["resolved_correctly"]) for row in critical_rows))

    called = human = flagged = row_correct = critical_correct = terminal_correct = 0
    projected_api = measured_api = 0.0
    escalations_by_criticality = Counter()
    paid = set(mode["paid_escalation_criticalities"])
    flags = set(mode["accept_with_flag_criticalities"])

    for row in rows:
        name = row["field_name"]
        criticality = row["field_criticality"]
        policy = field_policy(name)
        local_value, local_conf = _local_candidate(row)
        local_valid = bool(local_value) and not _fails_validation(name, local_value)
        state, value = "HUMAN_REVIEW", local_value

        if local_valid and local_conf >= float(mode["local_accept_confidence"]):
            state = "ACCEPT"
        else:
            retry_observed = "retry_candidate" in row
            eligible = (
                criticality in paid
                and policy.get("external_model_allowed", True)
                and not policy.get("optional", False)
                and (retry_observed or not mode["retry_before_escalation"])
            )
            if eligible:
                called += 1
                escalations_by_criticality[criticality] += 1
                projected_api += float(row.get("projected_cost_usd") or 0)
                measured_api += float(row.get("total_api_cost_usd") or 0)
                validation_failed = any(
                    stamp.get("verdict") == "FAIL"
                    for stamp in row.get("validation_results", []))
                usable = (
                    not row.get("grounding_rejections")
                    and not validation_failed
                    and float(row.get("escalation_confidence") or 0)
                    >= float(mode["multimodal_accept_confidence"])
                )
                if usable:
                    state, value = "ACCEPT", row.get("final_value")
                elif criticality in flags and local_valid:
                    state = "ACCEPT_WITH_FLAG"
            elif criticality in flags and local_valid:
                state = "ACCEPT_WITH_FLAG"

        correct = exact(value, row.get("ground_truth"))
        row_correct += correct
        if criticality == "high":
            critical_correct += correct
        if state in TERMINAL and correct:
            terminal_correct += 1
        if state == "ACCEPT_WITH_FLAG":
            flagged += 1
        if state == "HUMAN_REVIEW":
            human += 1

    correct_fields = fixed_correct + row_correct
    critical_total = fixed_critical_total + len(critical_rows)
    critical_correct_fields = fixed_critical_correct + critical_correct
    automated_correct = fixed_correct + terminal_correct
    projected_total = local_cost + projected_api
    measured_total = local_cost + measured_api
    return {
        "pages_processed": page_count,
        "fields_processed": total_fields,
        "observed_escalation_cohort_fields": len(rows),
        "correct_fields": correct_fields,
        "field_accuracy": _ratio(correct_fields, total_fields),
        "critical_field_accuracy": _ratio(critical_correct_fields, critical_total),
        "escalated_fields": called,
        "escalation_rate": _ratio(called, total_fields),
        "human_review_fields": human,
        "human_review_rate": _ratio(human, total_fields),
        "accept_with_flag_fields": flagged,
        "accept_with_flag_rate": _ratio(flagged, total_fields),
        "automated_correct_fields": automated_correct,
        "escalations_by_criticality": dict(sorted(escalations_by_criticality.items())),
        "optional_escalations": 0,
        "local_cost_per_page_usd": _ratio(local_cost, page_count),
        "measured_api_cost_per_page_usd": _ratio(measured_api, page_count),
        "projected_api_cost_per_page_usd": _ratio(projected_api, page_count),
        "measured_total_automated_cost_per_page_usd": _ratio(measured_total, page_count),
        "projected_total_automated_cost_per_page_usd": _ratio(projected_total, page_count),
        "projected_cost_per_correctly_resolved_field_usd": _ratio(
            projected_total, automated_correct),
    }


def calibrate(rows: list[dict], pages: list[dict], modes: dict) -> dict:
    return {name: {"configuration": mode, "metrics": simulate(rows, pages, mode)}
            for name, mode in sorted(modes.items())}


def _char_type(value) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or ""))
    if not text:
        return "empty"
    if text.isdigit():
        return "numeric"
    if text.isalpha():
        return "alphabetic"
    return "mixed"


def _length_bucket(length: int) -> str:
    if length == 0:
        return "0"
    if length <= 4:
        return "1-4"
    if length <= 9:
        return "5-9"
    if length <= 19:
        return "10-19"
    return "20+"


def _outcome(value, truth) -> str:
    return "missing" if value in (None, "") else ("correct" if exact(value, truth) else "incorrect")


def _root_cause(row: dict, primary: str, retry: str, escalation: str,
                validator_failures: list[str]) -> tuple[str, str]:
    if row["final_decision"] == "HUMAN_REVIEW" and row["resolved_correctly"]:
        return "governor_threshold", "governor_threshold_calibration"
    if validator_failures and row["resolved_correctly"]:
        return "validator_strictness", "validator_correction"
    truth = str(row.get("ground_truth") or "")
    final_value = str(row.get("final_value") or "")
    if (norm(final_value) != norm(truth)
            and re.sub(r"\W", "", final_value).lower()
            == re.sub(r"\W", "", truth).lower()):
        return "normalization", "deterministic_normalization"
    if row.get("grounding_rejections") or (
            primary == "correct" and escalation == "incorrect"):
        return "oracle_limitation", "multimodal_escalation"
    primary_value = str(row.get("primary_candidate") or "")
    if (norm(primary_value) != norm(truth)
            and re.sub(r"\W", "", primary_value).lower()
            == re.sub(r"\W", "", truth).lower()):
        return "normalization", "deterministic_normalization"
    crop = row.get("crop_dimensions") or []
    if crop and min(crop) < 50:
        return "crop_accuracy", "better_local_crop_strategy"
    if primary == "missing" or retry == "missing" or len(truth) <= 2:
        return "ocr_segmentation", "field_specific_ocr_mode"
    if len(truth) >= 20 and _char_type(truth) == "alphabetic":
        return "field_mapping", "better_local_crop_strategy"
    if row["tier"] == "ugly":
        return "preprocessing", "better_local_crop_strategy"
    return "genuinely_unreadable_source", "human_review_only"


def analyze_failures(rows: list[dict]) -> dict:
    selected = [row for row in rows
                if row["final_decision"] not in TERMINAL or not row["resolved_correctly"]]
    records = []
    for row in selected:
        truth = row.get("ground_truth")
        primary = _outcome(row.get("primary_candidate"), truth)
        retry = _outcome(row.get("retry_candidate"), truth)
        escalation = _outcome(row.get("escalation_candidate"), truth)
        failures = sorted(stamp["validator"] for stamp in row.get("validation_results", [])
                          if stamp.get("verdict") == "FAIL")
        crop = row.get("crop_dimensions") or []
        area = crop[0] * crop[1] if len(crop) == 2 else 0
        crop_bucket = ("missing" if not crop else "small" if area < 10_000
                       else "medium" if area < 30_000 else "large")
        cause, resolution = _root_cause(
            row, primary, retry, escalation, failures)
        truth_length = len(str(truth or ""))
        records.append({
            "tier": row["tier"],
            "document_id": row["document_id"],
            "document_type": row["document_id"].split("_")[0],
            "page": row["page"],
            "field_name": row["field_name"],
            "field_criticality": row["field_criticality"],
            "ground_truth": truth,
            "final_value": row.get("final_value"),
            "final_decision": row["final_decision"],
            "resolved_correctly": bool(row["resolved_correctly"]),
            "primary_outcome": primary,
            "retry_outcome": retry,
            "escalation_outcome": escalation,
            "escalation_decision": row.get("escalation_decision"),
            "validator_failures": ";".join(failures) if failures else "none",
            "grounding_rejections": ";".join(row.get("grounding_rejections", [])) or "none",
            "crop_width": crop[0] if len(crop) == 2 else None,
            "crop_height": crop[1] if len(crop) == 2 else None,
            "crop_area": area or None,
            "crop_dimensions_bucket": crop_bucket,
            "image_quality": row["tier"],
            "image_quality_basis": "degradation-tier proxy; numeric score absent from Day 8 rows",
            "character_length": truth_length,
            "character_length_bucket": _length_bucket(truth_length),
            "character_type": _char_type(truth),
            "likely_cause": cause,
            "recommended_resolution": resolution,
        })

    dimensions = {
        "tier": "tier", "document_type": "document_type", "field_name": "field_name",
        "field_criticality": "field_criticality", "primary_outcome": "primary_outcome",
        "retry_outcome": "retry_outcome", "escalation_outcome": "escalation_outcome",
        "validator_failure": "validator_failures",
        "crop_dimensions": "crop_dimensions_bucket", "image_quality": "image_quality",
        "character_length": "character_length_bucket", "character_type": "character_type",
        "likely_cause": "likely_cause", "recommended_resolution": "recommended_resolution",
    }
    groups = {name: dict(sorted(Counter(r[key] for r in records).items()))
              for name, key in dimensions.items()}
    cluster_counts = Counter(
        (r["tier"], r["document_type"], r["field_name"], r["likely_cause"],
         r["recommended_resolution"])
        for r in records)
    clusters = [
        {"tier": key[0], "document_type": key[1], "field_name": key[2],
         "likely_cause": key[3], "recommended_resolution": key[4], "count": count}
        for key, count in sorted(cluster_counts.items(),
                                 key=lambda item: (-item[1], item[0]))
    ]
    resolution_paths = [
        "better_local_crop_strategy", "field_specific_ocr_mode",
        "deterministic_normalization", "validator_correction",
        "multimodal_escalation", "human_review_only",
        "governor_threshold_calibration",
    ]
    resolution_counts = Counter(r["recommended_resolution"] for r in records)
    return {
        "source": str(ROWS),
        "scope_note": "All Day 8 human-review fields plus any incorrect terminal field.",
        "image_quality_note": "Day 8 rows record tier, not numeric page quality; tier is the proxy.",
        "rows_analyzed": len(records),
        "human_review_fields": sum(r["final_decision"] == "HUMAN_REVIEW" for r in records),
        "correct_values_sent_to_human_review": sum(
            r["final_decision"] == "HUMAN_REVIEW" and r["resolved_correctly"]
            for r in records),
        "incorrect_fields": sum(not r["resolved_correctly"] for r in records),
        "groups": groups,
        "resolution_path_counts": {
            path: resolution_counts.get(path, 0) for path in resolution_paths},
        "top_recurring_clusters": clusters[:20],
        "records": records,
    }


def accuracy_cost_frontier(points: list[dict]) -> list[dict]:
    ordered = sorted(points, key=lambda row: (
        row["projected_total_automated_cost_per_page_usd"],
        -row["field_accuracy"], row["human_review_rate"], row["point_id"]))
    frontier, best_accuracy = [], -1.0
    for row in ordered:
        if row["field_accuracy"] > best_accuracy:
            frontier.append(row)
            best_accuracy = row["field_accuracy"]
    return frontier


def recommend_balanced(points: list[dict]) -> dict:
    eligible = [row for row in points
                if row["paid_escalation_criticalities"] == "high|med"
                and row["accept_with_flag"]
                and row["critical_field_accuracy"] >= 0.995]
    best_accuracy = max(row["field_accuracy"] for row in eligible)
    near_best = [row for row in eligible if row["field_accuracy"] >= best_accuracy - 0.001]
    return min(near_best, key=lambda row: (
        row["projected_total_automated_cost_per_page_usd"],
        row["human_review_rate"], row["point_id"]))


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _flat_point(point: dict, metrics: dict) -> dict:
    return {
        "point_id": point["point_id"],
        "local_accept_confidence": point["local_accept_confidence"],
        "multimodal_accept_confidence": point["multimodal_accept_confidence"],
        "paid_escalation_criticalities": "|".join(point["paid_escalation_criticalities"]),
        "accept_with_flag": bool(point["accept_with_flag_criticalities"]),
        **{key: value for key, value in metrics.items()
           if key != "escalations_by_criticality"},
    }


def _write_report(analysis: dict, summary: dict) -> None:
    top_fields = sorted(analysis["groups"]["field_name"].items(),
                        key=lambda item: (-item[1], item[0]))[:10]
    causes = sorted(analysis["groups"]["likely_cause"].items(),
                    key=lambda item: (-item[1], item[0]))
    resolutions = sorted(analysis["resolution_path_counts"].items(),
                         key=lambda item: (-item[1], item[0]))
    lines = [
        "# Day 9 failure analysis and replay calibration", "",
        "## Evidence boundary", "",
        "This analysis uses only the synthetic Day 8 calibration results. It reruns no OCR,",
        "makes no external API calls, and does not use the official dataset. Offline-oracle",
        "costs remain projected; measured API spend is $0. Pre-escalation local candidates",
        "are reconstructed deterministically from recorded primary/retry attempts because Day 8",
        "did not persist the selected local candidate or full page validation context.", "",
        f"Analyzed **{analysis['rows_analyzed']}** unresolved-or-wrong fields: "
        f"**{analysis['human_review_fields']}** human-review outcomes and "
        f"**{analysis['incorrect_fields']}** incorrect values. "
        f"**{analysis['correct_values_sent_to_human_review']}** correct values were still sent "
        "to human review.", "", "## Top unresolved field types", "",
        "| Field | Count |", "|---|---:|",
        *[f"| `{name}` | {count} |" for name, count in top_fields], "",
        "## Root-cause clusters", "", "| Likely cause | Count |", "|---|---:|",
        *[f"| {name.replace('_', ' ')} | {count} |" for name, count in causes], "",
        "| Resolution path | Count |", "|---|---:|",
        *[f"| {name.replace('_', ' ')} | {count} |" for name, count in resolutions], "",
        "### Top recurring clusters", "",
        "| Tier | Form | Field | Cause | Resolution | Count |",
        "|---|---|---|---|---|---:|",
        *[
            f"| {cluster['tier']} | {cluster['document_type']} | "
            f"`{cluster['field_name']}` | {cluster['likely_cause'].replace('_', ' ')} | "
            f"{cluster['recommended_resolution'].replace('_', ' ')} | {cluster['count']} |"
            for cluster in analysis["top_recurring_clusters"][:10]
        ], "",
        "The dominant cluster is a policy-resolution issue: validators passed and the retained",
        "value was correct, but exhausted retry/escalation budgets plus the configured confidence",
        "threshold still produced HUMAN_REVIEW. This is not OCR or provider accuracy evidence.", "",
        "## Operating modes", "",
        "| Mode | Accuracy | Critical accuracy | Escalation | Human review | Projected cost/page |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("economy", "balanced", "accuracy"):
        metrics = summary["modes"][name]["metrics"]
        lines.append(
            f"| {name.title()} | {metrics['field_accuracy']:.2%} | "
            f"{metrics['critical_field_accuracy']:.2%} | {metrics['escalation_rate']:.2%} | "
            f"{metrics['human_review_rate']:.2%} | "
            f"${metrics['projected_total_automated_cost_per_page_usd']:.6f} |")
    rec = summary["recommended_balanced"]
    lines += ["", "## Recommended Balanced thresholds", "",
              f"- Local accept confidence: `{rec['local_accept_confidence']}`",
              f"- Multimodal accept confidence: `{rec['multimodal_accept_confidence']}`",
              "- Paid escalation: high and medium criticality only",
              f"- ACCEPT_WITH_FLAG enabled for low/medium: `{rec['accept_with_flag']}`",
              "- Optional-field escalation: prohibited", "",
              "## Accuracy-cost frontier", "",
              "| Accuracy | Escalation | Human review | Projected cost/page | Point |",
              "|---:|---:|---:|---:|---|",
              *[
                  f"| {point['field_accuracy']:.2%} | {point['escalation_rate']:.2%} | "
                  f"{point['human_review_rate']:.2%} | "
                  f"${point['projected_total_automated_cost_per_page_usd']:.6f} | "
                  f"`{point['point_id']}` |"
                  for point in summary["accuracy_cost_frontier"]
              ], "",
              "## Limits and next evidence", "",
        "The accuracy-cost frontier is bounded by the 406 fields actually escalated on Day 8.",
        "Accuracy is retained-value exact match, including HUMAN_REVIEW values; automated correct",
        "fields and human-review rate separately describe workflow resolution.",
              "It must not be presented as real-provider performance or extrapolated to unobserved",
              "calls. Official-dataset tuning remains blocked until its role and field mapping are",
              "confirmed.", ""]
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def generate() -> dict:
    rows, pages = read_jsonl(ROWS), read_jsonl(PAGES)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    modes = load_modes(CONFIG)
    analysis = analyze_failures(rows)
    FAILURE_JSON.write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(FAILURE_CSV, analysis["records"])

    mode_results = calibrate(rows, pages, modes)
    sweep_rows = []
    for point in build_sweep(config["sweep"]):
        sweep_rows.append(_flat_point(point, simulate(rows, pages, point)))
    frontier = accuracy_cost_frontier(sweep_rows)
    recommendation = recommend_balanced(sweep_rows)
    summary = {
        "source": {"field_rows": str(ROWS), "page_rows": str(PAGES)},
        "evidence_boundary": (
            "Replay of recorded Day 8 synthetic candidates only; no OCR rerun, external API, "
            "official dataset, or unobserved provider outcomes. Pre-escalation local values "
            "are deterministic reconstructions from recorded primary/retry attempts because "
            "Day 8 did not persist the selected local candidate or full validation context."),
        "metric_note": (
            "Field accuracy follows Day 8 retained-value exact match even for HUMAN_REVIEW; "
            "automated_correct_fields and human_review_rate report workflow resolution."),
        "provider_mode": "offline-oracle test double",
        "measured_api_spend_usd": 0.0,
        "modes": mode_results,
        "recommended_balanced": recommendation,
        "frontier_points": len(frontier),
        "accuracy_cost_frontier": frontier,
    }
    _write_csv(CALIBRATION_CSV, sweep_rows)
    _write_csv(FRONTIER_CSV, frontier)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_report(analysis, summary)
    return summary


def main() -> None:
    print(json.dumps(generate(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
