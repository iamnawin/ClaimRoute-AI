"""Local-only organiser sample benchmark with PHI-safe aggregate outputs.

Usage:
    uv run python -m eval.official.benchmark inspect --dataset-root "D:\\...\\Images & Output"
    uv run python -m eval.official.benchmark run --dataset-root "D:\\...\\Images & Output"
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time

import yaml

from eval.official.adapter import dataset_files, read_tiff_pages
from eval.official.evaluator import claimroute_expected, compare_fields, phi_safe_document_row
from eval.official.extraction import local_ocr, structured_page, unstructured_fields
from eval.official.linker import LinkResult, link_record
from eval.official.pages import select_claim_pages
from eval.official.parsers import OfficialRecord, parse_nsf_bytes, parse_ub_bytes

GROUPS = {"Group A": "A", "Group B": "B", "Group C": "C", "Group D": "D"}
RESULTS = Path("eval/official/results")


def _source_id(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _records(path: Path, tier: str) -> list[OfficialRecord]:
    data = path.read_bytes()
    return parse_ub_bytes(data) if tier == "C" else parse_nsf_bytes(data)


def inspect_dataset(root: str | Path) -> dict:
    receipt = {"read_only": True, "groups": {}, "total_containers": 0, "total_pages": 0}
    for group, tier in GROUPS.items():
        images, output = dataset_files(root, group)
        pages = sum(len(read_tiff_pages(path)) for path in images)
        records = _records(output, tier)
        receipt["groups"][tier] = {
            "containers": len(images), "pages": pages, "records": len(records),
            "format": records[0].format_name if records else None,
        }
        receipt["total_containers"] += len(images)
        receipt["total_pages"] += pages
    return receipt


def _resolve_group_links(texts: list[str], records: list[OfficialRecord]) -> list[LinkResult]:
    links = [link_record(text, records) for text in texts]
    winners: dict[int, list[int]] = defaultdict(list)
    for index, link in enumerate(links):
        if link.status == "deterministic" and link.record_ordinal is not None:
            winners[link.record_ordinal].append(index)
    for indexes in winners.values():
        if len(indexes) <= 1:
            continue
        keep = max(indexes, key=lambda index: (links[index].score, links[index].margin))
        for index in indexes:
            if index != keep:
                old = links[index]
                links[index] = LinkResult("ambiguous", None, old.score, old.margin,
                                          old.evidence_count,
                                          "record collision after unique-anchor linkage")
    return links


def _extract(tier: str, pages, words_by_page, texts, selection, source_id: str):
    if tier == "D":
        values = {}
        for text in texts:
            for name, value in unstructured_fields(text).items():
                values.setdefault(name, value)
        return values, Counter()
    if selection.status != "deterministic" or not selection.claim_pages:
        return {}, Counter()
    index = selection.claim_pages[0]
    form = "ub04" if tier == "C" else "cms1500"
    page = structured_page(pages[index], words_by_page[index], form, source_id)
    states = Counter(field.state.value for field in page.fields.values())
    return {name: field.value for name, field in page.fields.items()}, states


def _tier_b_page_truth(page_texts: list[str], record: OfficialRecord) -> int | None:
    evidence = [link_record(text, [record]).score for text in page_texts]
    if not evidence or max(evidence) == 0 or evidence.count(max(evidence)) != 1:
        return None
    return evidence.index(max(evidence))


def run_benchmark(root: str | Path, results: Path = RESULTS) -> dict:
    root = Path(root)
    vcpu_hour = float(yaml.safe_load(Path("configs/prices.yaml").read_text(
        encoding="utf-8"))["compute"]["vcpu_hour_usd"])
    started = time.perf_counter()
    safe_rows, proof, tier_records = [], {}, {}
    all_states = Counter()
    total_pages = 0
    b_page_evaluable = b_page_correct = b_attachment_total = b_attachment_correct = 0

    for group, tier in GROUPS.items():
        image_paths, output_path = dataset_files(root, group)
        records = _records(output_path, tier)
        tier_records[tier] = len(records)
        documents = []
        for path in image_paths:
            pages = read_tiff_pages(path)
            words_by_page, page_texts, ocr_ms = [], [], 0.0
            for page in pages:
                words, text, latency = local_ocr(page)
                words_by_page.append(words)
                page_texts.append(text)
                ocr_ms += latency
            documents.append((path, pages, words_by_page, page_texts, ocr_ms))
            total_pages += len(pages)

        links = _resolve_group_links([" ".join(doc[3]) for doc in documents], records)
        by_ordinal = {record.ordinal: record for record in records}
        for (path, pages, words_by_page, page_texts, ocr_ms), link in zip(documents, links):
            source_id = _source_id(path)
            selection = select_claim_pages(page_texts, tier)
            extract_start = time.perf_counter()
            extracted, states = _extract(tier, pages, words_by_page, page_texts,
                                         selection, source_id)
            extraction_ms = (time.perf_counter() - extract_start) * 1000
            all_states.update(states)
            comparisons = []
            record = by_ordinal.get(link.record_ordinal) if link.status == "deterministic" else None
            if record:
                comparisons = compare_fields(claimroute_expected(record), extracted)
                if tier == "B":
                    truth_page = _tier_b_page_truth(page_texts, record)
                    if truth_page is not None:
                        b_page_evaluable += 1
                        chosen = selection.claim_pages[0] if selection.claim_pages else None
                        b_page_correct += chosen == truth_page
                        expected_attachments = {i for i in range(len(pages)) if i != truth_page}
                        selected_attachments = set(selection.attachment_pages)
                        b_attachment_total += len(expected_attachments)
                        b_attachment_correct += len(expected_attachments & selected_attachments)
            latency = ocr_ms + extraction_ms
            cost = latency / 1000 / 3600 * vcpu_hour
            row = phi_safe_document_row(
                source_id=source_id, tier=tier, page_count=len(pages),
                linkage=link.safe_receipt(), comparisons=comparisons,
                latency_ms=latency, cost_usd=cost,
                detected_format=selection.detected_format,
                page_selection_status=selection.status,
                claim_pages_selected=len(selection.claim_pages),
                attachments_rejected=len(selection.attachment_pages),
                parsed_expected_field_count=(len(claimroute_expected(record)) if record else 0),
                extracted_field_count=sum(value not in (None, "") for value in extracted.values()),
                normalization="field-aware v1",
                external_provider_calls=0,
            )
            safe_rows.append(row)
            if tier not in proof and link.status == "deterministic":
                proof[tier] = row

    per_tier = {}
    for tier in GROUPS.values():
        rows = [row for row in safe_rows if row["tier"] == tier]
        evaluated = sum(row["evaluated_fields"] for row in rows)
        correct = sum(row["correct_fields"] for row in rows)
        deterministic = sum(row["linkage"]["status"] == "deterministic" for row in rows)
        per_tier[tier] = {
            "containers": len(rows), "pages": sum(row["page_count"] for row in rows),
            "records_parsed": tier_records[tier], "deterministic_mappings": deterministic,
            "ambiguous_or_unmatched": len(rows) - deterministic,
            "evaluated_fields": evaluated, "correct_fields": correct,
            "field_accuracy": correct / evaluated if evaluated else None,
            "present_field_rate": (sum(row["present_fields"] for row in rows) / evaluated
                                   if evaluated else None),
            "local_cost_usd": sum(row["local_cost_usd"] for row in rows),
        }
    per_tier["B"]["claim_page_identification"] = {
        "correct": b_page_correct, "evaluable": b_page_evaluable,
        "accuracy": b_page_correct / b_page_evaluable if b_page_evaluable else None,
    }
    per_tier["B"]["attachment_rejection"] = {
        "correct": b_attachment_correct, "expected_attachments": b_attachment_total,
        "accuracy": b_attachment_correct / b_attachment_total if b_attachment_total else None,
    }
    ambiguous = sum(row["linkage"]["status"] != "deterministic" for row in safe_rows)
    wall_ms = (time.perf_counter() - started) * 1000
    summary = {
        "benchmark": "official organiser sample (separate from frozen synthetic)",
        "architecture": "v1.2 locked plus monochrome official-input adapter",
        "dataset_root_committed": False, "source_files_modified": False,
        "containers_processed": len(safe_rows), "pages_processed": int(total_pages),
        "records_parsed": tier_records,
        "deterministic_mappings": len(safe_rows) - ambiguous,
        "ambiguous_mappings": ambiguous, "per_tier": per_tier,
        "combined_result": None if ambiguous else "available in per-tier weighted aggregation",
        "combined_result_reason": ("withheld because at least one expected-record linkage abstained"
                                   if ambiguous else None),
        "measured_local_cost_per_input_page_usd": sum(
            row["local_cost_usd"] for row in safe_rows) / total_pages,
        "throughput_input_pages_per_minute": total_pages * 60000 / wall_ms,
        "human_review_rate": (all_states["HUMAN_REVIEW"] / sum(all_states.values())
                              if all_states else None),
        "human_review_rate_interpretation": (
            "governor terminal HUMAN_REVIEW only; unresolved RETRY/ESCALATE fields are not "
            "counted because the official run disabled retry and external escalation"),
        "external_provider_calls": 0, "external_provider_spend_usd": 0.0,
        "phi_controls": ["local-only OCR", "read-only source access", "no values in reports",
                         "opaque source IDs", "aggregate correctness only"],
        "tier_b_cost_denominator": "all organiser input pages, including rejected attachments",
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "official_sample_rows.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in safe_rows), encoding="utf-8")
    (results / "official_four_document_proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    (results / "official_sample_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "run"):
        child = sub.add_parser(command)
        child.add_argument("--dataset-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    receipt = (inspect_dataset(args.dataset_root) if args.command == "inspect" else
               run_benchmark(args.dataset_root))
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
