"""Day 11 frozen synthetic-test benchmark and submission evidence generator.

The test split and runtime policy are read but never changed. The harness is
resumable, uses Balanced mode, permits only the deterministic offline oracle,
and keeps measured local costs separate from projected provider costs.

    python -m eval.day11_frozen freeze
    python -m eval.day11_frozen run --limit 5
    python -m eval.day11_frozen summarize
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image

import engine.escalate as escalation
from engine.extract import run_page
from engine.governor import apply, field_policy
from engine.ledger import CostLedger
from engine.preprocess import preprocess_page
from engine.router import route
from engine.schemas import FieldState
from eval.day8_escalation import execute_escalation

DATA = Path("data/generated")
SPLIT = Path("eval/splits/split_v1.json")
FROZEN = Path("eval/frozen")
WORK = FROZEN / "_work"
ROWS = FROZEN / "final_benchmark_rows.jsonl"
PAGES = FROZEN / "final_benchmark_pages.jsonl"
LEDGER = FROZEN / "final_benchmark_ledger.jsonl"
SUMMARY_JSON = FROZEN / "final_benchmark_summary.json"
SUMMARY_CSV = FROZEN / "final_benchmark_summary.csv"
ABLATION_JSON = FROZEN / "ablation_summary.json"
ABLATION_CSV = FROZEN / "ablation_summary.csv"
THROUGHPUT_JSON = FROZEN / "throughput_summary.json"
COST_CSV = FROZEN / "cost_projection.csv"
TIERS = ("clean", "noisy", "ugly")
TERMINAL = {FieldState.ACCEPT.value, FieldState.ACCEPT_WITH_FLAG.value}
MODE = "balanced"
RUN_ID = "day11-frozen-test-balanced-offline-oracle"
VOLUMES = (1_000, 1_000_000, 10_000_000, 100_000_000)
HASH_PATHS = (
    "configs/operating_modes.yaml", "configs/field_policy.yaml",
    "configs/engines.yaml", "configs/pipeline.yaml", "configs/prices.yaml",
    "engine/governor.py", "engine/preprocess.py", "engine/retry_rung.py",
    "engine/validators/registry.py", "engine/cropper.py", "engine/escalate.py",
    "eval/splits/split_v1.json", "data/generated/manifest.json",
    "requirements.txt",
)
PACKAGE_NAMES = (
    "pillow", "numpy", "pyyaml", "faker", "rapidocr-onnxruntime",
    "pytesseract", "onnxruntime", "opencv-python", "streamlit", "pytest",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], text=True, encoding="utf-8").strip()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append_once(path: Path, record: dict, key: tuple, seen: set[tuple]) -> bool:
    if key in seen:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
        fh.flush()
    seen.add(key)
    return True


def _split() -> dict:
    return json.loads(SPLIT.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def validate_dataset() -> dict:
    split, manifest = _split(), _manifest()
    calibration, test = set(split["calibration"]), set(split["test"])
    manifest_ids = [row["doc_id"] for row in manifest["docs"]]
    if calibration & test:
        raise ValueError("calibration and frozen-test document IDs overlap")
    if len(manifest_ids) != len(set(manifest_ids)):
        raise ValueError("dataset manifest contains duplicate document IDs")
    if calibration | test != set(manifest_ids):
        raise ValueError("split IDs do not exactly match the dataset manifest")
    digest = hashlib.sha256("\n".join(sorted(test)).encode()).hexdigest()
    if digest != split["test_sha256"]:
        raise ValueError("frozen test SHA-256 does not match its document IDs")

    seeds = {row["doc_id"]: row["seed"] for row in manifest["docs"]}
    page_count = field_count = 0
    tier_field_sets: dict[str, set[str]] = {}
    for doc_id in sorted(test):
        form = doc_id.split("_")[0]
        tier_field_sets.clear()
        for tier in TIERS:
            image_path = DATA / form / tier / "images" / f"{doc_id}.png"
            gt_path = DATA / form / tier / "ground_truth" / f"{doc_id}.json"
            if not image_path.exists() or not gt_path.exists():
                raise FileNotFoundError(f"missing frozen page or truth: {doc_id}/{tier}")
            truth = json.loads(gt_path.read_text(encoding="utf-8"))
            names = set(truth.get("fields", {}))
            if not names or any("value" not in row for row in truth["fields"].values()):
                raise ValueError(f"incomplete ground truth: {doc_id}/{tier}")
            tier_field_sets[tier] = names
            page_count += 1
            field_count += len(names)
        if len({frozenset(names) for names in tier_field_sets.values()}) != 1:
            raise ValueError(f"tier ground-truth fields differ for {doc_id}")
    return {
        "calibration_documents": len(calibration),
        "frozen_test_documents": len(test),
        "frozen_test_pages": page_count,
        "frozen_test_fields": field_count,
        "calibration_test_overlap": 0,
        "test_sha256": digest,
        "dataset_ids": sorted(test),
        "seeds": {doc_id: seeds[doc_id] for doc_id in sorted(test)},
        "tiers": list(TIERS),
        "official_data_included": False,
    }


def _package_manifest() -> dict:
    packages = {}
    for name in PACKAGE_NAMES:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
            continue
        packages[name] = {
            "version": dist.version,
            "license": dist.metadata.get("License"),
            "license_expression": dist.metadata.get("License-Expression"),
        }
    return packages


def freeze() -> dict:
    status = git("status", "--porcelain")
    if status:
        raise RuntimeError(
            "freeze requires a clean working tree; commit the harness before freezing:\n" + status)
    dataset = validate_dataset()
    pipeline = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    operating = yaml.safe_load(
        Path("configs/operating_modes.yaml").read_text(encoding="utf-8"))
    FROZEN.mkdir(parents=True, exist_ok=True)
    hashes = {path: sha256(path) for path in HASH_PATHS}
    (FROZEN / "config_hashes.json").write_text(
        json.dumps({"sha256": hashes}, indent=2, sort_keys=True), encoding="utf-8")
    environment = {
        "captured_at": utc_now(),
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "not reported by platform module",
        "packages": _package_manifest(),
        "tesseract": subprocess.check_output(
            [r"C:\Program Files\Tesseract-OCR\tesseract.exe", "--version"],
            text=True, encoding="utf-8", errors="replace").splitlines()[0],
    }
    (FROZEN / "environment_manifest.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "evaluation_timestamp": utc_now(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "working_tree_status_before_freeze": "clean",
        "configuration_frozen": True,
        "architecture": "v1.2 locked",
        "operating_mode": MODE,
        "runtime_preset": pipeline["presets"][MODE],
        "replay_mode_record": operating["modes"][MODE],
        "dataset": dataset,
        "benchmark_commands": [
            "python -m eval.day11_frozen freeze",
            "python -m eval.day11_frozen run --limit 5",
            "python -m eval.day11_frozen summarize",
        ],
        "cost_labels": {
            "local_compute": "MEASURED",
            "external_api_spend": "MEASURED (must remain $0)",
            "offline_oracle": "PROJECTED",
            "scale_costs": "PROJECTED",
            "vcpu_and_human_review_prices": "CONFIGURED ASSUMPTION",
        },
        "provider_policy": {
            "external_calls": False,
            "test_double": "offline-oracle",
            "official_data": False,
            "full_page_external": False,
        },
    }
    (FROZEN / "frozen_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _attempt(field, rung: str):
    return next((attempt for attempt in reversed(field.attempts)
                 if attempt.rung == rung), None)


def _stamp_rows(field) -> list[dict]:
    return [{"validator": stamp.validator, "verdict": stamp.verdict.value,
             "detail": stamp.detail} for stamp in field.stamps]


def _included(expected: dict | None, policy: dict, value) -> bool:
    return expected is not None or not policy.get("optional") or value not in (None, "")


def _snapshot(field, expected: dict | None) -> dict:
    policy = field_policy(field.field_name)
    value = field.value
    included = _included(expected, policy, value)
    return {
        "value": value,
        "confidence": field.confidence,
        "state": field.state.value,
        "correct": norm(value) == norm(expected["value"]) if expected else value in (None, ""),
        "included_in_accuracy": included,
        "validation_results": _stamp_rows(field),
    }


def _operation_totals(entries: list[dict], operations: set[str]) -> tuple[float, float]:
    selected = [row for row in entries if row["operation"] in operations]
    return (sum(float(row["cost_usd"]) for row in selected),
            sum(float(row["latency_ms"]) for row in selected))


def _iter_targets(limit: int, completed: set[tuple[str, str]]):
    yielded = 0
    for doc_id in _split()["test"]:
        for tier in TIERS:
            if (doc_id, tier) in completed:
                continue
            if limit and yielded >= limit:
                return
            yield doc_id, tier
            yielded += 1


def run(limit: int = 0) -> int:
    frozen_manifest = FROZEN / "frozen_manifest.json"
    if not frozen_manifest.exists():
        raise RuntimeError("run freeze first")
    frozen = json.loads(frozen_manifest.read_text(encoding="utf-8"))
    if frozen["git_commit"] != git("rev-parse", "HEAD"):
        raise RuntimeError("HEAD differs from frozen harness commit")
    unexpected = [line for line in git("status", "--porcelain").splitlines()
                  if line and not any(path in line.replace("\\", "/")
                                      for path in ("eval/frozen/",))]
    if unexpected:
        raise RuntimeError("non-frozen-output working-tree changes detected:\n" + "\n".join(unexpected))

    WORK.mkdir(parents=True, exist_ok=True)
    escalation.CACHE_PATH = WORK / "vision_cache.jsonl"
    escalation._CACHE = None
    existing_pages = read_jsonl(PAGES)
    completed = {(row["document_id"], row["tier"]) for row in existing_pages}
    row_seen = {(row["document_id"], row["tier"], row["field_name"])
                for row in read_jsonl(ROWS)}
    page_seen = set(completed)
    ledger_seen = {(row["document_id"], row["tier"], row["operation"], row.get("field", ""))
                   for row in read_jsonl(LEDGER)}
    written = 0

    for doc_id, tier in _iter_targets(limit, completed):
        form = doc_id.split("_")[0]
        gt_path = DATA / form / tier / "ground_truth" / f"{doc_id}.json"
        image_path = DATA / form / tier / "images" / f"{doc_id}.png"
        truth = json.loads(gt_path.read_text(encoding="utf-8"))["fields"]
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        with tempfile.TemporaryDirectory(prefix="claimroute-day11-") as temp:
            temp_path = Path(temp)
            raw_ledger = CostLedger(temp_path / "raw.jsonl")
            full_ledger = CostLedger(temp_path / "full.jsonl")

            raw_page = run_page(image, doc_id, raw_ledger, prep=False,
                                run_retry=False, preset_name=MODE,
                                run_escalate=False, tier=tier)
            wall_start = time.perf_counter()
            page = run_page(image, doc_id, full_ledger, prep=True,
                            run_retry=True, preset_name=MODE,
                            run_escalate=False, tier=tier)
            local_snapshot = {name: _snapshot(field, truth.get(name))
                              for name, field in page.fields.items()}
            first_states = {name: decisions[0][0]
                            for name, decisions in page.decisions.items()}

            work = preprocess_page(image)["processed"]
            routing = route(work)
            values = {name: field.value for name, field in page.fields.items()}
            for name, field in page.fields.items():
                if field.state != FieldState.ESCALATE:
                    continue
                rec, error, _ = execute_escalation(
                    field, work, page.doc_type, routing["variant"], values,
                    page.quality_score, full_ledger, "offline-oracle", tier)
                rec["error"] = error
                page.escalations[name] = rec
                state, reason = apply(field, MODE)
                page.decisions[name].append((state.value, reason))
            full_wall_ms = (time.perf_counter() - wall_start) * 1000

            raw_entries = raw_ledger.entries()
            full_entries = full_ledger.entries()
            raw_cost, raw_latency = _operation_totals(
                raw_entries, {"route", "ocr_paddle"})
            prep_cost, prep_latency = _operation_totals(
                full_entries, {"preprocess", "route", "ocr_paddle"})
            validate_cost, validate_latency = _operation_totals(
                full_entries, {"preprocess", "route", "ocr_paddle", "validate_fuse"})
            local_cost, local_latency = _operation_totals(
                full_entries, {"preprocess", "route", "ocr_paddle", "validate_fuse",
                               "retry_tesseract"})

            page_rows = []
            all_names = sorted(set(truth) | set(page.fields) | set(raw_page.fields))
            for name in all_names:
                field = page.fields.get(name)
                expected = truth.get(name)
                policy = field_policy(name)
                raw_field = raw_page.fields.get(name)
                raw_primary = _attempt(raw_field, "primary_ocr") if raw_field else None
                primary = _attempt(field, "primary_ocr") if field else None
                retry = _attempt(field, "retry_ocr") if field else None
                oracle = _attempt(field, "multimodal") if field else None
                local = local_snapshot.get(name, {
                    "value": None, "confidence": 0.0, "state": "UNRESOLVED",
                    "correct": expected is None, "included_in_accuracy": expected is not None,
                    "validation_results": [],
                })
                final = _snapshot(field, expected) if field else dict(local)

                def arm(value, state, included=None):
                    use = (_included(expected, policy, value) if included is None else included)
                    return {
                        "value": value,
                        "state": state,
                        "correct": norm(value) == norm(expected["value"])
                                   if expected else value in (None, ""),
                        "included_in_accuracy": use,
                    }

                raw_value = raw_primary.value if raw_primary else None
                primary_value = primary.value if primary else None
                row = {
                    "run_id": RUN_ID,
                    "document_id": doc_id,
                    "tier": tier,
                    "page": "p1",
                    "field_name": name,
                    "criticality": policy["criticality"],
                    "optional": bool(policy.get("optional")),
                    "ground_truth": expected["value"] if expected else None,
                    "included_in_accuracy": final["included_in_accuracy"],
                    "final_value": final["value"],
                    "final_state": final["state"],
                    "resolved_correctly": final["correct"],
                    "primary_candidate": primary_value,
                    "primary_confidence": primary.confidence if primary else None,
                    "retry_candidate": retry.value if retry else None,
                    "retry_confidence": retry.confidence if retry else None,
                    "escalation_candidate": oracle.value if oracle else None,
                    "escalation_confidence": oracle.confidence if oracle else None,
                    "first_state": first_states.get(name, "UNRESOLVED"),
                    "pre_escalation_state": local["state"],
                    "validation_results": final["validation_results"],
                    "processing_path": [
                        {"rung": attempt.rung, "engine": attempt.engine,
                         "value": attempt.value, "confidence": attempt.confidence,
                         "cost_usd": attempt.cost_usd, "latency_ms": attempt.latency_ms}
                        for attempt in (field.attempts if field else [])
                    ],
                    "projected_api_cost_usd": oracle.cost_usd if oracle else 0.0,
                    "measured_api_cost_usd": 0.0,
                    "provider_mode": "offline-oracle test double",
                    "timestamp": utc_now(),
                    "ablation": {
                        "primary_ocr_only": arm(raw_value,
                                                "RESOLVED" if raw_value else "UNRESOLVED"),
                        "primary_plus_preprocessing": arm(
                            primary_value, "RESOLVED" if primary_value else "UNRESOLVED"),
                        "primary_plus_validators": arm(
                            primary_value, first_states.get(name, "UNRESOLVED")),
                        "primary_validators_local_retry": arm(
                            local["value"], local["state"],
                            local["included_in_accuracy"]),
                        "full_cost_governed_pipeline": arm(
                            final["value"], final["state"],
                            final["included_in_accuracy"]),
                    },
                }
                page_rows.append(row)

            projected_api = sum(row["projected_api_cost_usd"] for row in page_rows)
            measured_api = 0.0
            page_record = {
                "run_id": RUN_ID,
                "document_id": doc_id,
                "tier": tier,
                "page": "p1",
                "routed_fields": len(page_rows),
                "evaluated_fields": sum(row["included_in_accuracy"] for row in page_rows),
                "correct_fields": sum(row["included_in_accuracy"] and row["resolved_correctly"]
                                      for row in page_rows),
                "critical_fields": sum(row["included_in_accuracy"] and
                                       row["criticality"] == "high" for row in page_rows),
                "critical_correct_fields": sum(
                    row["included_in_accuracy"] and row["criticality"] == "high" and
                    row["resolved_correctly"] for row in page_rows),
                "primary_resolved_fields": sum(row["first_state"] in TERMINAL
                                               for row in page_rows),
                "retry_routed_fields": sum(row["first_state"] == "RETRY"
                                           for row in page_rows),
                "retry_attempted_fields": sum(any(a["rung"] == "retry_ocr"
                                                   for a in row["processing_path"])
                                              for row in page_rows),
                "retry_resolved_fields": sum(
                    any(a["rung"] == "retry_ocr" for a in row["processing_path"])
                    and row["pre_escalation_state"] in TERMINAL for row in page_rows),
                "escalated_fields": sum(row["pre_escalation_state"] == "ESCALATE"
                                        for row in page_rows),
                "escalation_resolved_fields": sum(
                    row["pre_escalation_state"] == "ESCALATE" and
                    row["final_state"] in TERMINAL for row in page_rows),
                "accept_with_flag_fields": sum(row["final_state"] == "ACCEPT_WITH_FLAG"
                                               for row in page_rows),
                "human_review_fields": sum(row["final_state"] == "HUMAN_REVIEW"
                                           for row in page_rows),
                "measured_local_cost_usd": local_cost,
                "measured_api_cost_usd": measured_api,
                "projected_api_cost_usd": projected_api,
                "projected_total_automated_cost_usd": local_cost + projected_api,
                "measured_local_latency_ms": local_latency,
                "full_wall_latency_ms": full_wall_ms,
                "projected_provider_latency_ms": None,
                "ablation_cost_latency": {
                    "primary_ocr_only": {"cost_usd": raw_cost, "latency_ms": raw_latency},
                    "primary_plus_preprocessing": {
                        "cost_usd": prep_cost, "latency_ms": prep_latency},
                    "primary_plus_validators": {
                        "cost_usd": validate_cost, "latency_ms": validate_latency},
                    "primary_validators_local_retry": {
                        "cost_usd": local_cost, "latency_ms": local_latency},
                    "full_cost_governed_pipeline": {
                        "cost_usd": local_cost + projected_api,
                        "latency_ms": full_wall_ms},
                },
                "timestamp": utc_now(),
            }

            for row in page_rows:
                append_once(ROWS, row, (doc_id, tier, row["field_name"]), row_seen)
            for entry in full_entries:
                record = {"run_id": RUN_ID, "document_id": doc_id, "tier": tier,
                          "cost_basis": ("PROJECTED" if entry["operation"].startswith(
                              "escalate_offline-oracle") else "MEASURED"), **entry}
                key = (doc_id, tier, entry["operation"], entry.get("field", ""))
                append_once(LEDGER, record, key, ledger_seen)
            append_once(PAGES, page_record, (doc_id, tier), page_seen)
        written += 1
        print(f"completed {doc_id}/{tier}: {page_record['evaluated_fields']} fields, "
              f"{page_record['escalated_fields']} escalated")
    print(f"chunk done ({written} pages)")
    return written


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(quantile * len(ordered)) - 1)], 3)


def aggregate(rows: list[dict], pages: list[dict]) -> dict:
    evaluated = [row for row in rows if row["included_in_accuracy"]]
    routed = len(rows)
    escalated = [row for row in rows if row["pre_escalation_state"] == "ESCALATE"]
    wall = [float(page["full_wall_latency_ms"]) for page in pages]
    page_count = len(pages)
    projected_api = sum(float(page["projected_api_cost_usd"]) for page in pages)
    local_cost = sum(float(page["measured_local_cost_usd"]) for page in pages)
    correct_escalated = sum(row["final_state"] in TERMINAL and
                            row["resolved_correctly"] for row in escalated)
    return {
        "documents": len({row["document_id"] for row in pages}),
        "pages": page_count,
        "routed_fields": routed,
        "evaluated_fields": len(evaluated),
        "field_accuracy": _ratio(sum(row["resolved_correctly"] for row in evaluated),
                                  len(evaluated)),
        "critical_field_accuracy": _ratio(
            sum(row["resolved_correctly"] for row in evaluated
                if row["criticality"] == "high"),
            sum(row["criticality"] == "high" for row in evaluated)),
        "automated_exact_match_rate": _ratio(
            sum(row["resolved_correctly"] and row["final_state"] in TERMINAL
                for row in evaluated), len(evaluated)),
        "primary_local_resolution_rate": _ratio(
            sum(row["first_state"] in TERMINAL for row in rows), routed),
        "local_retry_rate": _ratio(
            sum(any(a["rung"] == "retry_ocr" for a in row["processing_path"])
                for row in rows), routed),
        "local_retry_resolution_rate": _ratio(
            sum(any(a["rung"] == "retry_ocr" for a in row["processing_path"])
                and row["pre_escalation_state"] in TERMINAL for row in rows),
            sum(any(a["rung"] == "retry_ocr" for a in row["processing_path"])
                for row in rows)),
        "escalation_rate": _ratio(len(escalated), routed),
        "escalation_resolution_rate": _ratio(
            sum(row["final_state"] in TERMINAL for row in escalated), len(escalated)),
        "accept_with_flag_rate": _ratio(
            sum(row["final_state"] == "ACCEPT_WITH_FLAG" for row in rows), routed),
        "human_review_rate": _ratio(
            sum(row["final_state"] == "HUMAN_REVIEW" for row in rows), routed),
        "measured_local_cost_per_page_usd": _ratio(local_cost, page_count),
        "measured_api_spend_per_page_usd": 0.0,
        "projected_api_cost_per_page_usd": _ratio(projected_api, page_count),
        "projected_total_automated_cost_per_page_usd": _ratio(
            local_cost + projected_api, page_count),
        "projected_cost_per_correctly_resolved_escalated_field_usd": _ratio(
            projected_api, correct_escalated),
        "average_latency_per_page_ms": _ratio(sum(wall), page_count),
        "p50_latency_ms": _percentile(wall, 0.50),
        "p95_latency_ms": _percentile(wall, 0.95),
        "throughput_pages_per_minute": _ratio(page_count * 60_000, sum(wall)),
        "throughput_pages_per_hour": _ratio(page_count * 3_600_000, sum(wall)),
        "projected_provider_latency": "not available; offline oracle is not a provider benchmark",
        "measured_external_api_calls": 0,
        "measured_external_api_spend_usd": 0.0,
    }


def aggregate_ablation(rows: list[dict], pages: list[dict], arm: str) -> dict:
    samples = [(row, row["ablation"][arm]) for row in rows
               if row["ablation"][arm]["included_in_accuracy"]]
    routed = len(rows)
    costs = [page["ablation_cost_latency"][arm] for page in pages]
    total_latency = sum(float(item["latency_ms"]) for item in costs)
    unresolved = sum(item["state"] not in TERMINAL and item["state"] != "RESOLVED"
                     for _, item in samples)
    return {
        "status": "measured" if arm != "full_cost_governed_pipeline" else
                  "measured local plus projected offline-oracle",
        "pages": len(pages),
        "evaluated_fields": len(samples),
        "accuracy": _ratio(sum(item["correct"] for _, item in samples), len(samples)),
        "critical_field_accuracy": _ratio(
            sum(item["correct"] for row, item in samples if row["criticality"] == "high"),
            sum(row["criticality"] == "high" for row, _ in samples)),
        "unresolved_rate": _ratio(unresolved, len(samples)),
        "human_review_rate": _ratio(
            sum(item["state"] == "HUMAN_REVIEW" for _, item in samples), len(samples)),
        "local_cost_per_page_usd": _ratio(
            sum(float(item["cost_usd"]) for item in costs)
            - (sum(float(page["projected_api_cost_usd"]) for page in pages)
               if arm == "full_cost_governed_pipeline" else 0.0), len(pages)),
        "projected_automated_cost_per_page_usd": _ratio(
            sum(float(item["cost_usd"]) for item in costs), len(pages)),
        "average_latency_ms": _ratio(total_latency, len(pages)),
        "throughput_pages_per_minute": _ratio(len(pages) * 60_000, total_latency),
        "routing_denominator_fields": routed,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def summarize() -> dict:
    rows, pages = read_jsonl(ROWS), read_jsonl(PAGES)
    integrity = validate_dataset()
    expected = {(doc_id, tier) for doc_id in integrity["dataset_ids"] for tier in TIERS}
    page_keys = [(row["document_id"], row["tier"]) for row in pages]
    field_keys = [(row["document_id"], row["tier"], row["field_name"]) for row in rows]
    if len(page_keys) != len(set(page_keys)) or len(field_keys) != len(set(field_keys)):
        raise ValueError("duplicate benchmark rows detected")
    if set(page_keys) != expected:
        missing = sorted(expected - set(page_keys))
        raise RuntimeError(f"frozen benchmark incomplete: {len(missing)} pages missing")
    if any(row["measured_api_cost_usd"] != 0 for row in rows):
        raise ValueError("measured API spend must remain zero")

    per_tier = {}
    flat_summary = []
    for tier in TIERS:
        tier_rows = [row for row in rows if row["tier"] == tier]
        tier_pages = [row for row in pages if row["tier"] == tier]
        per_tier[tier] = aggregate(tier_rows, tier_pages)
        flat_summary.append({"scope": tier, **per_tier[tier]})
    blended = aggregate(rows, pages)
    flat_summary.append({"scope": "blended", **blended})
    summary = {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "frozen_git_commit": json.loads(
            (FROZEN / "frozen_manifest.json").read_text(encoding="utf-8"))["git_commit"],
        "operating_mode": MODE,
        "dataset_split": "frozen synthetic test split",
        "integrity": {
            **{key: value for key, value in integrity.items()
               if key not in {"dataset_ids", "seeds"}},
            "duplicate_page_rows": 0,
            "duplicate_field_rows": 0,
            "external_provider_calls": 0,
            "official_data_included": False,
            "optional_absent_fields_excluded_unless_hallucinated": True,
        },
        "evidence_labels": {
            "accuracy_and_routing": "MEASURED on synthetic frozen test data",
            "local_latency_and_compute": "MEASURED on development workstation",
            "external_api_spend": "MEASURED at $0",
            "offline_oracle_cost": "PROJECTED using configured GPT-5 nano prices",
            "volume_costs": "PROJECTED",
        },
        "per_tier": per_tier,
        "blended": blended,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(SUMMARY_CSV, flat_summary)

    arms = (
        "primary_ocr_only", "primary_plus_preprocessing", "primary_plus_validators",
        "primary_validators_local_retry", "full_cost_governed_pipeline",
    )
    ablations = {arm: aggregate_ablation(rows, pages, arm) for arm in arms}
    ablations["full_pipeline_without_healthcare_validators"] = {
        "status": "not supported",
        "reason": "No validator bypass exists in the frozen engine; adding one after freeze would invalidate evidence.",
    }
    ABLATION_JSON.write_text(
        json.dumps({"run_id": RUN_ID, "arms": ablations}, indent=2, sort_keys=True),
        encoding="utf-8")
    _write_csv(ABLATION_CSV, [
        {"arm": name, **values} for name, values in ablations.items()
        if values.get("status") != "not supported"
    ])

    human_per_page = _ratio(sum(page["human_review_fields"] for page in pages), len(pages)) or 0
    human_price = yaml.safe_load(Path("configs/prices.yaml").read_text(
        encoding="utf-8"))["human_review"]["cost_per_field_touch_usd"]
    cost_rows = []
    for volume in VOLUMES:
        cost_rows.append({
            "pages": volume,
            "measured_local_compute_projection_usd": round(
                blended["measured_local_cost_per_page_usd"] * volume, 6),
            "projected_api_cost_usd": round(
                blended["projected_api_cost_per_page_usd"] * volume, 6),
            "projected_total_automated_cost_usd": round(
                blended["projected_total_automated_cost_per_page_usd"] * volume, 6),
            "configured_human_review_cost_usd": round(
                human_per_page * human_price * volume, 6),
        })
    _write_csv(COST_CSV, cost_rows)

    throughput = {
        "basis": "measured local prototype throughput on the frozen synthetic test run",
        "not_production_claim": True,
        "environment_manifest": "eval/frozen/environment_manifest.json",
        "warm_up": "first completed page retained; no warm-up exclusion",
        "pages": blended["pages"],
        "total_elapsed_ms": round(sum(float(page["full_wall_latency_ms"])
                                      for page in pages), 3),
        "average_latency_per_page_ms": blended["average_latency_per_page_ms"],
        "p50_latency_ms": blended["p50_latency_ms"],
        "p95_latency_ms": blended["p95_latency_ms"],
        "pages_per_minute": blended["throughput_pages_per_minute"],
        "pages_per_hour": blended["throughput_pages_per_hour"],
        "memory_observation": "not measured; no supported process RSS probe was added",
        "projected_provider_latency": "not available",
    }
    THROUGHPUT_JSON.write_text(
        json.dumps(throughput, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--limit", type=int, default=0)
    sub.add_parser("summarize")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", 0) < 0:
        raise SystemExit("--limit must be >= 0")
    if args.command == "freeze":
        freeze()
    elif args.command == "run":
        run(args.limit)
    else:
        summarize()


if __name__ == "__main__":
    main()
