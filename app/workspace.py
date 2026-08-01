"""Local-only document and batch processing contracts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from collections import Counter
from typing import Callable

import yaml

from app import service
from app.intake import FileRole, IntakeFile, decode_pages
from engine.governor import field_policy
from eval.official.evaluator import claimroute_expected, compare_fields
from eval.official.extraction import local_ocr, structured_page, unstructured_fields
from eval.official.linker import link_record
from eval.official.pages import select_claim_pages
from eval.official.parsers import parse_nsf_bytes, parse_ub_bytes


PageProcessor = Callable[[object, str, str], dict]


def _default_page_processor(image, doc_id: str, mode: str) -> dict:
    return service.process_document(
        image, doc_id, mode, source_kind="local_workspace", tier="clean"
    )


def _official_tier(group_key: str) -> str | None:
    match = re.search(r"(?:^|[/\\])group\s*([a-d])(?:$|[/\\])", group_key, re.I)
    return match.group(1).upper() if match else None


def _local_cost(latency_ms: float) -> float:
    prices = yaml.safe_load((service.ROOT / "configs" / "prices.yaml").read_text(
        encoding="utf-8"))
    return latency_ms / 1000 / 3600 * float(prices["compute"]["vcpu_hour_usd"])


def _official_unstructured_result(item: IntakeFile, pages, texts, latency_ms: float) -> dict:
    values = {}
    for text in texts:
        for name, value in unstructured_fields(text).items():
            values.setdefault(name, value)
    fields = {name: {
        "value": value,
        "state": "ACCEPT_WITH_FLAG",
        "confidence": None,
        "stamps": [],
        "provenance": [{"rung": "local_ocr", "engine": "official_unstructured"}],
        "cost_usd": 0.0,
    } for name, value in values.items()}
    return {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": "unstructured",
        "page_count": len(pages),
        "processing_status": "COMPLETED",
        "fields": [{"page": 1, "fields": fields}],
        "validations": [],
        "governor_summary": {"ACCEPT_WITH_FLAG": len(fields)},
        "retry_summary": {"fields_retried": 0},
        "escalation_summary": {"fields_escalated": 0, "external_provider_calls": 0},
        "unresolved_fields": 0,
        "latency": {"milliseconds": round(latency_ms, 3)},
        "measured_cost": {"usd": round(_local_cost(latency_ms), 9)},
        "projected_cost": {"usd": round(_local_cost(latency_ms), 9)},
        "warnings": ["Tier D uses limited label-driven extraction."],
        "evaluation": None,
        "evidence_semantics": "official_unstructured_adapter",
        "_group_key": item.group_key,
        "_linkage_text": " ".join(texts),
    }


def _process_official_item(item: IntakeFile, tier: str, mode: str) -> dict:
    started = time.perf_counter()
    try:
        pages = decode_pages(item.content, item.source_format)
        words_by_page, texts = [], []
        for page in pages:
            words, text, _ = local_ocr(page)
            words_by_page.append(words)
            texts.append(text)
        if tier == "D":
            return _official_unstructured_result(
                item, pages, texts, (time.perf_counter() - started) * 1000)
        selection = select_claim_pages(texts, tier)
        if selection.status != "deterministic" or not selection.claim_pages:
            result = _failed_result(
                item, "Claim-page selection abstained; no page was extracted.",
                status="COMPLETED",
            )
            result.update({
                "page_count": len(pages),
                "evidence_semantics": "official_monochrome_adapter",
                "_group_key": item.group_key,
                "_linkage_text": " ".join(texts),
            })
            return result
        page_index = selection.claim_pages[0]
        form = "ub04" if tier == "C" else "cms1500"
        page_result = structured_page(
            pages[page_index], words_by_page[page_index], form,
            item.safe_source_id, preset=mode, run_retry=True,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        cost = _local_cost(elapsed_ms)
        receipt = service.build_receipt(
            page_result,
            [{"operation": "official_local_compute", "cost_usd": cost,
              "latency_ms": elapsed_ms, "meta": {}}],
            mode, elapsed_ms, source_kind="local_workspace",
        )
        result = _unify_receipts(item, [receipt])
        result["page_count"] = len(pages)
        result["evidence_semantics"] = "official_monochrome_adapter"
        result["_linkage_text"] = " ".join(texts)
        if selection.attachment_pages:
            result["warnings"].append(
                f"{len(selection.attachment_pages)} attachment page(s) excluded from extraction.")
        return result
    except Exception:
        return _failed_result(item, "Official document processing failed; batch continued.")


def _failed_result(item: IntakeFile, warning: str, *, status: str = "FAILED") -> dict:
    return {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": "unknown",
        "page_count": item.page_count or 0,
        "processing_status": status,
        "fields": [],
        "validations": [],
        "governor_summary": {},
        "retry_summary": {"fields_retried": 0},
        "escalation_summary": {"fields_escalated": 0, "external_provider_calls": 0},
        "unresolved_fields": 0,
        "latency": {"milliseconds": 0.0},
        "measured_cost": {"usd": 0.0},
        "projected_cost": {"usd": 0.0},
        "warnings": [warning],
        "evaluation": None,
    }


def _unify_receipts(item: IntakeFile, receipts: list[dict]) -> dict:
    if item.role != FileRole.CLAIM_DOCUMENT:
        return _failed_result(item, "File role is not a claim document.", status="SKIPPED")
    document_types = {receipt["document"]["document_type"] for receipt in receipts}
    fields, validations = [], []
    governor = Counter()
    retried = escalated = unresolved = 0
    measured = projected = latency = 0.0
    linkage_values = []
    for page_number, receipt in enumerate(receipts, 1):
        page_fields = receipt["final_output"]
        fields.append({"page": page_number, "fields": page_fields})
        for field in receipt["fields"]:
            validations.append({
                "page": page_number,
                "field_name": field["field_name"],
                "results": field["validation"],
            })
            governor[field["decision"]] += 1
            retried += int(field["retry_count"] > 0)
            escalated += int(field["escalated"])
            unresolved += int(field["decision"] not in {
                "ACCEPT", "ACCEPT_WITH_FLAG", "ACCEPT_WITH_OVERRIDE"
            })
            if field.get("final_value") not in (None, ""):
                linkage_values.append(str(field["final_value"]))
        measured += float(receipt["costs"]["measured_total_automated"]["value_usd"])
        projected += float(receipt["costs"]["projected_total_automated"]["value_usd"])
        latency += float(receipt["latency_ms"])
    return {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": next(iter(document_types)) if len(document_types) == 1 else "mixed",
        "page_count": len(receipts),
        "processing_status": "COMPLETED",
        "fields": fields,
        "validations": validations,
        "governor_summary": dict(sorted(governor.items())),
        "retry_summary": {"fields_retried": retried},
        "escalation_summary": {
            "fields_escalated": escalated,
            "external_provider_calls": 0,
        },
        "unresolved_fields": unresolved,
        "latency": {"milliseconds": round(latency, 3)},
        "measured_cost": {"usd": round(measured, 9)},
        "projected_cost": {"usd": round(projected, 9)},
        "warnings": [],
        "evaluation": None,
        "_group_key": item.group_key,
        "_linkage_text": " ".join(linkage_values),
    }


def process_item(item: IntakeFile, mode: str = service.DEFAULT_MODE,
                 *, page_processor: PageProcessor | None = None) -> dict:
    """Process every decoded page without consulting expected output."""
    if item.role != FileRole.CLAIM_DOCUMENT:
        return _failed_result(item, "File role is not a claim document.", status="SKIPPED")
    if item.status == "ERROR":
        return _failed_result(item, item.warning or "Document intake failed.")
    official_tier = _official_tier(item.group_key)
    if official_tier and page_processor is None:
        return _process_official_item(item, official_tier, mode)
    processor = page_processor or _default_page_processor
    try:
        pages = decode_pages(item.content, item.source_format)
        receipts = [
            processor(page, f"{item.safe_source_id}-p{index}", mode)
            for index, page in enumerate(pages, 1)
        ]
        return _unify_receipts(item, receipts)
    except Exception:
        return _failed_result(item, "Document processing failed; other batch items continued.")


def _job_id(items: list[IntakeFile], mode: str) -> str:
    material = "|".join([mode, *(item.safe_source_id for item in items)])
    return f"batch-{hashlib.sha256(material.encode()).hexdigest()[:12]}"


def summarize_results(results: list[dict]) -> dict:
    counts = Counter(result["processing_status"] for result in results)
    completed = [result for result in results if result["processing_status"] == "COMPLETED"]
    pages = sum(result["page_count"] for result in completed)
    latency = sum(result["latency"]["milliseconds"] for result in completed)
    types = Counter(result["document_type"] for result in completed)
    return {
        "files": len(results),
        "pages": pages,
        "success": counts["COMPLETED"],
        "failed": counts["FAILED"],
        "skipped": counts["SKIPPED"] + counts["DUPLICATE"],
        "cancelled": counts["CANCELLED"],
        "document_types": dict(sorted(types.items())),
        "unresolved_fields": sum(result["unresolved_fields"] for result in completed),
        "measured_cost_usd": round(sum(
            result["measured_cost"]["usd"] for result in completed), 9),
        "projected_cost_usd": round(sum(
            result["projected_cost"]["usd"] for result in completed), 9),
        "latency_ms": round(latency, 3),
        "throughput_pages_per_minute": round(pages * 60000 / latency, 6) if latency else None,
        "accuracy": None,
        "critical_accuracy": None,
    }


def run_batch(items: list[IntakeFile], mode: str = service.DEFAULT_MODE,
              *, processor: Callable[[IntakeFile, str], dict] | None = None,
              progress: Callable[[int, int, dict], None] | None = None,
              stop_requested: Callable[[], bool] | None = None,
              existing_results: dict[str, dict] | None = None,
              evaluate: bool = False) -> dict:
    """Process deterministically, skip duplicates, and continue after failures."""
    ordered = sorted(items, key=lambda item: (item.filename.casefold(), item.safe_source_id))
    process = processor or (lambda item, selected_mode: process_item(item, selected_mode))
    existing_results = existing_results or {}
    seen = set()
    results = []
    for index, item in enumerate(ordered, 1):
        if stop_requested and stop_requested():
            result = _failed_result(item, "Batch stopped before this document.", status="CANCELLED")
        elif item.safe_source_id in existing_results:
            result = existing_results[item.safe_source_id]
        elif item.safe_source_id in seen:
            result = _failed_result(item, "Duplicate content skipped.", status="DUPLICATE")
        elif item.role != FileRole.CLAIM_DOCUMENT:
            result = _failed_result(item, "File is not routed to document processing.", status="SKIPPED")
        else:
            try:
                result = process(item, mode)
            except Exception:
                result = _failed_result(
                    item, "Document processing failed; other batch items continued.")
        seen.add(item.safe_source_id)
        results.append(result)
        if progress:
            progress(index, len(ordered), result)
    batch = {
        "batch_job_id": _job_id(ordered, mode),
        "processing_status": "COMPLETED_WITH_ERRORS" if any(
            result["processing_status"] == "FAILED" for result in results
        ) else "COMPLETED",
        "operating_mode": mode,
        "documents": results,
        "summary": summarize_results(results),
        "evaluation": None,
    }
    return evaluate_dataset(batch, ordered) if evaluate else batch


def _flatten_fields(result: dict) -> dict:
    flattened = {}
    for page in result.get("fields", []):
        for name, field in page.get("fields", {}).items():
            value = field.get("value") if isinstance(field, dict) else field
            if name not in flattened or flattened[name] in (None, ""):
                flattened[name] = value
    return flattened


def parse_expected_output(item: IntakeFile):
    if item.source_format == "NSF320":
        return parse_nsf_bytes(item.content)
    if item.source_format == "UB192":
        return parse_ub_bytes(item.content)
    if item.source_format == "JSON":
        payload = json.loads(item.content.decode("utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("fields"), dict):
            return payload
    raise ValueError("Expected-output format is not supported.")


def _comparison_receipt(comparisons: list[dict], linkage: dict) -> dict:
    critical = [row for row in comparisons
                if field_policy(row["field_name"]).get("criticality") == "high"]
    return {
        "linkage": linkage,
        "evaluated_fields": len(comparisons),
        "correct_fields": sum(row["correct"] for row in comparisons),
        "accuracy": (sum(row["correct"] for row in comparisons) / len(comparisons)
                     if comparisons else None),
        "critical_fields": len(critical),
        "critical_correct_fields": sum(row["correct"] for row in critical),
        "critical_accuracy": (sum(row["correct"] for row in critical) / len(critical)
                              if critical else None),
        "field_results": comparisons,
    }


def evaluate_dataset(batch: dict, items: list[IntakeFile]) -> dict:
    """Parse/link expected output only after all document extraction is complete."""
    expected_by_group: dict[str, list] = {}
    synthetic_by_id: dict[tuple[str, str], dict] = {}
    for item in items:
        if item.role != FileRole.EXPECTED_OUTPUT:
            continue
        parsed = parse_expected_output(item)
        if isinstance(parsed, list):
            expected_by_group.setdefault(item.group_key, []).extend(parsed)
        else:
            synthetic_by_id[(item.group_key, str(parsed.get("doc_id", "")))] = parsed

    all_comparisons = []
    all_critical = []
    linked = 0
    for result in batch["documents"]:
        if result["processing_status"] != "COMPLETED":
            continue
        actual = _flatten_fields(result)
        group = result.get("_group_key", ".")
        synthetic = synthetic_by_id.get((group, result["source_file"].rsplit(".", 1)[0]))
        if synthetic:
            expected = {
                name: row.get("value") if isinstance(row, dict) else row
                for name, row in synthetic["fields"].items()
            }
            linkage = {"status": "deterministic", "record_ordinal": None,
                       "method": "synthetic document ID after extraction"}
        else:
            records = expected_by_group.get(group, [])
            link = link_record(result.get("_linkage_text", ""), records)
            linkage = link.safe_receipt()
            record = next((row for row in records if row.ordinal == link.record_ordinal), None)
            expected = claimroute_expected(record) if record else {}
        comparisons = compare_fields(expected, actual) if expected else []
        result["evaluation"] = _comparison_receipt(comparisons, linkage)
        linked += int(linkage["status"] == "deterministic")
        all_comparisons.extend(comparisons)
        all_critical.extend(row for row in comparisons
                            if field_policy(row["field_name"]).get("criticality") == "high")
    evaluation = {
        "documents_linked": linked,
        "evaluated_fields": len(all_comparisons),
        "correct_fields": sum(row["correct"] for row in all_comparisons),
        "accuracy": (sum(row["correct"] for row in all_comparisons) / len(all_comparisons)
                     if all_comparisons else None),
        "critical_fields": len(all_critical),
        "critical_correct_fields": sum(row["correct"] for row in all_critical),
        "critical_accuracy": (sum(row["correct"] for row in all_critical) / len(all_critical)
                              if all_critical else None),
        "ground_truth_stage": "post_extraction_only",
    }
    batch["evaluation"] = evaluation
    batch["summary"]["accuracy"] = evaluation["accuracy"]
    batch["summary"]["critical_accuracy"] = evaluation["critical_accuracy"]
    return batch


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def export_batch_json(batch: dict) -> str:
    return json.dumps(_public(batch), indent=2, sort_keys=True)


def export_document_json(result: dict) -> str:
    return json.dumps(_public(result), indent=2, sort_keys=True)


def export_document_csv(result: dict) -> str:
    stream = io.StringIO(newline="")
    fieldnames = ["page", "field_name", "value", "state", "confidence", "cost_usd"]
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for page in result.get("fields", []):
        for name, field in page.get("fields", {}).items():
            writer.writerow({
                "page": page["page"],
                "field_name": name,
                "value": field.get("value") if isinstance(field, dict) else field,
                "state": field.get("state") if isinstance(field, dict) else "",
                "confidence": field.get("confidence") if isinstance(field, dict) else "",
                "cost_usd": field.get("cost_usd") if isinstance(field, dict) else "",
            })
    return stream.getvalue()


def export_batch_csv(batch: dict) -> str:
    stream = io.StringIO(newline="")
    fieldnames = [
        "batch_job_id", "safe_source_id", "source_file", "source_format",
        "processing_status", "document_type", "page_count", "unresolved_fields",
        "measured_cost_usd", "projected_cost_usd", "latency_ms", "accuracy", "warning",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for result in batch["documents"]:
        evaluation = result.get("evaluation") or {}
        writer.writerow({
            "batch_job_id": batch["batch_job_id"],
            "safe_source_id": result["safe_source_id"],
            "source_file": result["source_file"],
            "source_format": result["source_format"],
            "processing_status": result["processing_status"],
            "document_type": result["document_type"],
            "page_count": result["page_count"],
            "unresolved_fields": result["unresolved_fields"],
            "measured_cost_usd": result["measured_cost"]["usd"],
            "projected_cost_usd": result["projected_cost"]["usd"],
            "latency_ms": result["latency"]["milliseconds"],
            "accuracy": evaluation.get("accuracy"),
            "warning": "; ".join(result["warnings"]),
        })
    return stream.getvalue()
