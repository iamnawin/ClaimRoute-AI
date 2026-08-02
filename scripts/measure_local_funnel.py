"""Measure the local extraction funnel per document family.

Runs the same code path the workspace UI runs (``workspace.process_item``) and
reports, for each document family separately, how far local processing gets
before anything is eligible for a paid multimodal call.

Ground truth is never read. The headline metric is validated local coverage:

    validated fields after primary OCR and retry / applicable fields

Raw OCR confidence is deliberately not reported as a success measure - a
confident wrong string is not a resolved field.

Usage (from the repository root):

    python scripts/measure_local_funnel.py --sample 5
    python scripts/measure_local_funnel.py --sample 25 --out eval/results/local_funnel.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw

from app import workspace
from app.intake import inspect_content

GENERATED = REPO_ROOT / "data" / "generated"
TIERS = ("clean", "noisy", "ugly")

# Authorized development documents live outside the repository so that no real
# scan is ever committed. Point at the folder with --authorized-dir.
DEFAULT_AUTHORIZED = Path(
    os.environ.get("CLAIMROUTE_AUTHORIZED_DIR",
                   str(REPO_ROOT.parent / "authorized-development")))


def _int(value) -> int:
    return int(value or 0)


def _ratio(numerator, denominator):
    denominator = float(denominator or 0)
    return float(numerator or 0) / denominator if denominator else None


def _synthetic_items(form: str, sample: int) -> list:
    items = []
    for tier in TIERS:
        folder = GENERATED / form / tier / "images"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.png"))[:sample]:
            items.append((f"{form}_{tier}", inspect_content(
                path.name, path.read_bytes())))
    return items


def _authorized_items(folder: Path) -> list:
    if not folder.is_dir():
        return []
    return [("monochrome_authorized", inspect_content(path.name, path.read_bytes()))
            for path in sorted(folder.iterdir())
            if path.is_file() and not path.name.startswith(".")]


def _rendered(text_lines: list[str]) -> bytes:
    """A synthetic page with text but no claim-form geometry."""
    page = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(page)
    for index, line in enumerate(text_lines):
        draw.text((120, 160 + index * 60), line, fill="black")
    stream = io.BytesIO()
    page.save(stream, format="PNG")
    return stream.getvalue()


def _fixture_items() -> list:
    """Synthetic stand-ins for the unstructured and unknown-form families."""
    unstructured = _rendered([
        "PATIENT STATEMENT", "Patient Name: SYNTHETIC PERSON",
        "Member ID: ZZ9999999", "Date of Service: 01/15/2025",
        "Total Charges: 250.00", "Provider NPI: 1234567893",
    ])
    unknown = _rendered([
        "INTERNAL ROUTING SLIP", "Reference 00-11-22",
        "No claim form markers are present on this page.",
    ])
    return [
        ("unstructured_synthetic", inspect_content("synthetic_statement.png",
                                                   unstructured)),
        ("unknown_synthetic", inspect_content("synthetic_routing_slip.png",
                                              unknown)),
    ]


def _document_row(family: str, item, result: dict) -> dict:
    coverage = result.get("coverage") or workspace.coverage_metrics(result)
    resolution = result.get("resolution_summary") or {}
    retry = result.get("retry_summary") or {}
    escalation = result.get("escalation_summary") or {}
    review = result.get("human_review_summary") or {}
    latency = result.get("latency") or {}
    stages = latency.get("stages_ms") or {}
    return {
        "family": family,
        "document": item.filename,
        "document_type": result.get("document_type"),
        "processing_status": result.get("processing_status"),
        "page_count": _int(result.get("page_count")),
        "available": bool(coverage.get("available")),
        "applicable_fields": _int(coverage.get("applicable_fields")),
        "fields_produced": _int(coverage.get("fields_produced")),
        "validated_fields": _int(coverage.get("validated_fields")),
        "unresolved_fields": _int(coverage.get("unresolved_fields")),
        "inapplicable_fields": _int(coverage.get("inapplicable_fields")),
        "primary_resolved": _int(resolution.get("accepted_without_retry")),
        "retry_resolved": _int(resolution.get("accepted_after_local_retry")),
        "fields_retried": _int(retry.get("fields_retried")),
        "multimodal_eligible": _int(resolution.get("multimodal_eligible")),
        "pending_multimodal": _int(escalation.get("pending_multimodal")),
        "human_review_required": _int(review.get("required")),
        "external_calls": _int(escalation.get("external_provider_calls")),
        "latency_ms": float(latency.get("milliseconds") or 0),
        "primary_ocr_ms": float(stages.get("primary_ocr") or 0),
        "retry_ocr_ms": float(stages.get("retry_ocr") or 0),
        "measured_cost_usd": float((result.get("measured_cost") or {}).get("usd") or 0),
        "warnings": result.get("warnings") or [],
    }


def _aggregate(family: str, rows: list[dict]) -> dict:
    def total(key: str) -> int:
        return sum(_int(row[key]) for row in rows)

    applicable = total("applicable_fields")
    pages = total("page_count") or len(rows)
    return {
        "family": family,
        "documents": len(rows),
        "documents_with_schema": sum(row["available"] for row in rows),
        "pages": pages,
        "applicable_fields": applicable,
        "fields_produced": total("fields_produced"),
        "validated_fields": total("validated_fields"),
        "unresolved_fields": total("unresolved_fields"),
        "inapplicable_fields": total("inapplicable_fields"),
        "primary_resolved": total("primary_resolved"),
        "retry_resolved": total("retry_resolved"),
        "fields_retried": total("fields_retried"),
        "multimodal_eligible": total("multimodal_eligible"),
        "human_review_required": total("human_review_required"),
        "external_calls": total("external_calls"),
        "validated_local_coverage": _ratio(total("validated_fields"), applicable),
        "primary_ocr_resolution_rate": _ratio(total("primary_resolved"), applicable),
        "retry_contribution_rate": _ratio(total("retry_resolved"), applicable),
        "retry_yield": _ratio(total("retry_resolved"), total("fields_retried")),
        "unresolved_rate": _ratio(total("unresolved_fields"), applicable),
        "human_review_rate": _ratio(total("human_review_required"), applicable),
        "mean_latency_ms": _ratio(sum(row["latency_ms"] for row in rows), len(rows)),
        "mean_primary_ocr_ms": _ratio(
            sum(row["primary_ocr_ms"] for row in rows), len(rows)),
        "mean_retry_ocr_ms": _ratio(sum(row["retry_ocr_ms"] for row in rows), len(rows)),
        "measured_cost_per_page_usd": _ratio(
            sum(row["measured_cost_usd"] for row in rows), pages),
        "statuses": {status: sum(row["processing_status"] == status for row in rows)
                     for status in sorted({row["processing_status"] for row in rows})},
        "document_types": {name: sum(row["document_type"] == name for row in rows)
                           for name in sorted({str(row["document_type"])
                                               for row in rows})},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=5,
                        help="synthetic documents per form and tier")
    parser.add_argument("--authorized-dir", type=Path, default=DEFAULT_AUTHORIZED)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mode", default="balanced")
    args = parser.parse_args()

    items = (_synthetic_items("cms1500", args.sample)
             + _synthetic_items("ub04", args.sample)
             + _authorized_items(args.authorized_dir)
             + _fixture_items())
    if not items:
        print("No documents found. Generate the synthetic dataset first.")
        return 1

    rows, started = [], time.perf_counter()
    for index, (family, item) in enumerate(items, 1):
        result = workspace.process_item(item, args.mode)
        rows.append(_document_row(family, item, result))
        print(f"  [{index}/{len(items)}] {family:24s} {item.filename:28s} "
              f"{rows[-1]['processing_status']:18s} "
              f"validated {rows[-1]['validated_fields']}/"
              f"{rows[-1]['applicable_fields']}", flush=True)

    families = []
    for family in dict.fromkeys(row["family"] for row in rows):
        families.append(_aggregate(family, [row for row in rows
                                            if row["family"] == family]))
    for form in ("cms1500", "ub04"):
        tiered = [row for row in rows if row["family"].startswith(f"{form}_")]
        if tiered:
            families.append(_aggregate(f"{form}_all_tiers", tiered))

    report = {
        "mode": args.mode,
        "sample_per_tier": args.sample,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "families": families,
        "documents": rows,
        "external_calls_total": sum(row["external_calls"] for row in rows),
    }
    print()
    header = (f"{'family':26s} {'docs':>5s} {'appl':>6s} {'valid':>6s} "
              f"{'cover':>7s} {'primary':>8s} {'retry+':>7s} {'unres':>6s} "
              f"{'review':>7s}")
    print(header)
    print("-" * len(header))
    for family in families:
        def pct(value):
            return f"{value:.1%}" if value is not None else "  n/a"
        print(f"{family['family']:26s} {family['documents']:5d} "
              f"{family['applicable_fields']:6d} {family['validated_fields']:6d} "
              f"{pct(family['validated_local_coverage']):>7s} "
              f"{pct(family['primary_ocr_resolution_rate']):>8s} "
              f"{pct(family['retry_contribution_rate']):>7s} "
              f"{family['unresolved_fields']:6d} "
              f"{pct(family['human_review_rate']):>7s}")
    print(f"\nexternal calls: {report['external_calls_total']}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
