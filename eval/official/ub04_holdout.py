"""One-time, local-only Tier C holdout runner with PHI-safe output."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from engine.layout.official_ub04_registration import normalize_official_ub04_page
from eval.official.adapter import dataset_files, read_tiff_pages
from eval.official.evaluator import claimroute_expected, compare_fields
from eval.official.extraction import local_ocr, retry_official_page, structured_page
from eval.official.parsers import parse_ub_bytes
from eval.official.ub04_freeze_review import freeze_manifest, provisional_denominators


POLICY_PATH = Path("eval/official/ub04_denominator_policy.yaml")
SPLIT_PATH = Path("eval/official/splits/tier_c_split_v1.json")
MANIFEST_PATH = Path("eval/results/official_ub04_freeze_manifest.json")
OUTPUT_PATH = Path("eval/results/official_ub04_holdout_summary.json")
CONFIRMATION = "RUN_TIER_C_HOLDOUT_ONCE"


def verify_freeze() -> None:
    recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if recorded != freeze_manifest():
        raise RuntimeError("Tier C freeze manifest mismatch; do not access holdout")


def _records(path: Path, ordinals: set[int]) -> dict[int, object]:
    rows = path.read_bytes().splitlines()
    starts = [index for index, row in enumerate(rows) if row.startswith(b"10")]
    starts.append(len(rows))
    return {
        ordinal: parse_ub_bytes(b"\n".join(rows[starts[ordinal - 1]:starts[ordinal]]))[0]
        for ordinal in ordinals
    }


def run(dataset_root: Path, output: Path = OUTPUT_PATH,
        visibly_populated: set[str] | None = None) -> dict:
    verify_freeze()  # Must pass before any organiser dataset path is touched.
    if output.exists():
        raise FileExistsError(f"one-time receipt already exists: {output}")
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    holdout = {row["source_id"]: row["record_ordinal"] for row in split["holdout"]}
    image_paths, expected_path = dataset_files(dataset_root, "Group C")
    selected = {}
    for path in image_paths:
        source_id = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        if source_id in holdout:
            selected[source_id] = path
    if set(selected) != set(holdout):
        raise RuntimeError("Tier C holdout files do not match the immutable split")

    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    records = _records(expected_path, set(holdout.values()))
    rows = []
    for source_id in sorted(holdout):
        pages = read_tiff_pages(selected[source_id])
        normalized = normalize_official_ub04_page(pages[0])
        if normalized is None:
            raise RuntimeError(f"registration abstained for safe source {source_id}")
        image, registration = normalized
        words, _, latency_ms = local_ocr(image)
        page = structured_page(image, words, "ub04", source_id, registration=registration)
        expected = claimroute_expected(records[holdout[source_id]])
        denominators = provisional_denominators(expected, policy, visibly_populated)
        all_fields = dict(page.fields)
        page.fields = {name: all_fields[name] for name in denominators["primary"]
                       if name in all_fields}
        page.decisions = {name: page.decisions[name] for name in page.fields}
        retry_official_page(page, image)
        extracted = {name: field.value for name, field in all_fields.items()}
        extracted.update({name: field.value for name, field in page.fields.items()})
        primary = compare_fields(
            {name: expected[name] for name in denominators["primary"]}, extracted
        )
        extended = compare_fields(
            {name: expected[name] for name in denominators["extended"]}, extracted
        )
        rows.append({
            "source_id": source_id,
            "primary_denominator": len(primary),
            "primary_correct": sum(item["correct"] for item in primary),
            "extended_denominator": len(extended),
            "extended_correct": sum(item["correct"] for item in extended),
            "primary_field_results": primary,
            "extended_field_results": extended,
            "latency_ms": round(latency_ms, 3),
        })

    receipt = {
        "result_label": policy["meta"]["result_label"],
        "split_id": split["split_id"],
        "documents": len(rows),
        "primary_denominator": sum(row["primary_denominator"] for row in rows),
        "primary_correct": sum(row["primary_correct"] for row in rows),
        "extended_denominator": sum(row["extended_denominator"] for row in rows),
        "extended_correct": sum(row["extended_correct"] for row in rows),
        "excluded_predictions_counted_correct": 0,
        "conditional_fields_confirmed_visible": sorted(visibly_populated or set()),
        "external_provider_calls": 0,
        "rows": rows,
    }
    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--visible-conditional-field", action="append", default=[],
                        choices=["attending_npi"])
    args = parser.parse_args(argv)
    if args.confirm != CONFIRMATION:
        parser.error(f"--confirm must equal {CONFIRMATION}")
    print(json.dumps(run(args.dataset_root,
                         visibly_populated=set(args.visible_conditional_field)), indent=2))


if __name__ == "__main__":
    main()
