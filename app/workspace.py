"""Local-only document and batch processing contracts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from typing import Callable

from app import service
from app.intake import FileRole, IntakeFile, decode_pages


PageProcessor = Callable[[object, str, str], dict]


def _default_page_processor(image, doc_id: str, mode: str) -> dict:
    return service.process_document(
        image, doc_id, mode, source_kind="local_workspace", tier="clean"
    )


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


def process_item(item: IntakeFile, mode: str = service.DEFAULT_MODE,
                 *, page_processor: PageProcessor | None = None) -> dict:
    """Process every decoded page without consulting expected output."""
    if item.role != FileRole.CLAIM_DOCUMENT:
        return _failed_result(item, "File role is not a claim document.", status="SKIPPED")
    if item.status == "ERROR":
        return _failed_result(item, item.warning or "Document intake failed.")
    processor = page_processor or _default_page_processor
    try:
        pages = decode_pages(item.content, item.source_format)
        receipts = [
            processor(page, f"{item.safe_source_id}-p{index}", mode)
            for index, page in enumerate(pages, 1)
        ]
    except Exception:
        return _failed_result(item, "Document processing failed; other batch items continued.")

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
              existing_results: dict[str, dict] | None = None) -> dict:
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
    return {
        "batch_job_id": _job_id(ordered, mode),
        "processing_status": "COMPLETED_WITH_ERRORS" if any(
            result["processing_status"] == "FAILED" for result in results
        ) else "COMPLETED",
        "operating_mode": mode,
        "documents": results,
        "summary": summarize_results(results),
        "evaluation": None,
    }


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def export_batch_json(batch: dict) -> str:
    return json.dumps(_public(batch), indent=2, sort_keys=True)


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
