"""Local-only document and batch processing contracts."""
from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

import yaml

from app import service
from app.intake import FileRole, IntakeFile, decode_pages
from app.local_retry import retry_cms1500_page
from engine.governor import field_policy, preset
from engine.schemas import FieldState, ValidationStamp, Verdict
from engine.validators import validate_field
from engine.validators.registry import cpt_format, currency_format, date_valid
from eval.official.evaluator import claimroute_expected, compare_fields
from eval.official.extraction import (
    local_ocr,
    new_stage_latency,
    record_stage,
    retry_official_page,
    structured_page,
    unstructured_fields,
)
from eval.official.linker import link_record
from eval.official.pages import CMS_MARKERS, UB_MARKERS, _score, select_claim_pages
from eval.official.parsers import parse_nsf_bytes, parse_ub_bytes


PageProcessor = Callable[[object, str, str], dict]

# Statuses that mean "this document produced extraction output". PARTIAL
# documents did real work and must keep contributing to batch metrics.
PRODUCED_OUTPUT = {"COMPLETED", "PARTIAL"}
RESOLVED_FIELD_STATES = {
    "INAPPLICABLE", "ACCEPT", "ACCEPT_WITH_FLAG", "ACCEPT_WITH_OVERRIDE",
}


class ProcessingStage(str, Enum):
    QUEUED = "QUEUED"
    DECODING = "DECODING"
    ROUTING = "ROUTING"
    PRIMARY_OCR = "PRIMARY_OCR"
    VALIDATING_PRIMARY = "VALIDATING_PRIMARY"
    LOCAL_RETRY = "LOCAL_RETRY"
    VALIDATING_RETRY = "VALIDATING_RETRY"
    MULTIMODAL_PENDING = "MULTIMODAL_PENDING"
    MULTIMODAL_PROCESSING = "MULTIMODAL_PROCESSING"
    VALIDATING_MULTIMODAL = "VALIDATING_MULTIMODAL"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    HUMAN_REVIEW_COMPLETED = "HUMAN_REVIEW_COMPLETED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED_EXTRACTION = "FAILED_EXTRACTION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def mode_policy(mode: str) -> dict:
    """The runtime policy actually consumed by the governor."""
    runtime = preset(mode)
    calibrated = service.load_operating_modes()[mode]
    result = {
        "mode": mode,
        "accept_threshold": runtime["accept_threshold"],
        "escalate_threshold": runtime["escalate_threshold"],
        "allow_accept_with_flag": runtime["allow_accept_with_flag"],
        "paid_escalation_criticalities": calibrated["paid_escalation_criticalities"],
        "retry_before_escalation": calibrated["retry_before_escalation"],
        "external_calls_enabled": False,
    }
    return result


def _stage(progress: Callable[[dict], None] | None, stage: ProcessingStage,
           message: str, **details) -> None:
    if progress:
        progress({"stage": stage.value, "message": message, **details})


def _document_status(field_count: int, unresolved: int) -> str:
    """An empty extraction is never a success, and unresolved work is never clean."""
    if field_count == 0:
        return "FAILED_EXTRACTION"
    return "PARTIAL" if unresolved else "COMPLETED"


def _final_stage(status: str) -> ProcessingStage:
    return {
        "COMPLETED": ProcessingStage.COMPLETED,
        "PARTIAL": ProcessingStage.PARTIAL,
        "FAILED_EXTRACTION": ProcessingStage.FAILED_EXTRACTION,
        "CANCELLED": ProcessingStage.CANCELLED,
    }.get(status, ProcessingStage.FAILED)


def _default_page_processor(image, doc_id: str, mode: str) -> dict:
    return service.process_document(
        image, doc_id, mode, source_kind="local_workspace", tier="clean"
    )


def _cms1500_service_line_anchor_counts(fields: dict) -> dict[int, int]:
    validators = {
        "date_from": date_valid,
        "cpt_code": cpt_format,
        "charges": currency_format,
    }
    return {
        index: sum(
            validator(getattr(fields.get(f"line{index}_{suffix}"), "value", None), {})[0]
            == Verdict.PASS
            for suffix, validator in validators.items()
        )
        for index in range(1, 4)
    }


def _active_cms1500_service_lines(fields: dict) -> set[int]:
    """Detect printed rows from raw OCR anchors without expected output."""
    return {index for index, count in _cms1500_service_line_anchor_counts(fields).items()
            if count >= 2}


def _mark_inactive_cms1500_service_lines(page) -> None:
    anchor_counts = _cms1500_service_line_anchor_counts(page.fields)
    for name, field in page.fields.items():
        match = re.fullmatch(r"line(\d+)_\w+", name)
        if not match or anchor_counts[int(match.group(1))] > 0:
            continue
        field.value = None
        field.confidence = 0.0
        field.stamps = [ValidationStamp(
            "service_line_activation", Verdict.INAPPLICABLE,
            "service line has no valid activation anchors",
        )]
        for attempt in field.attempts:
            attempt.value = None
            attempt.confidence = 0.0
        field.set_state(FieldState.ACCEPT)
        page.decisions[name] = [("INAPPLICABLE", "service line is not active")]


def _local_cost(latency_ms: float) -> float:
    prices = yaml.safe_load((service.ROOT / "configs" / "prices.yaml").read_text(
        encoding="utf-8"))
    return latency_ms / 1000 / 3600 * float(prices["compute"]["vcpu_hour_usd"])


def _provider_policy_snapshot(config: dict | None = None,
                              env: dict | None = None) -> dict:
    """Return safe provider availability metadata without constructing a client."""
    if config is None:
        config = yaml.safe_load((service.ROOT / "configs" / "multimodal_providers.yaml")
                                .read_text(encoding="utf-8")) or {}
    live = config.get("live_provider") or {}
    provider_name = live.get("provider") or config.get("active_provider") or ""
    provider = (config.get("providers") or {}).get(provider_name) or {}
    model = provider.get("model") or ""
    key_env = provider.get("api_key_env") or ""
    values = os.environ if env is None else env
    enabled = bool(config.get("enabled", False) and live.get("enabled", False))
    credential_available = bool(key_env and str(values.get(key_env) or "").strip())

    if not enabled:
        state, reason = "PENDING_MULTIMODAL_PROVIDER_DISABLED", "disabled by policy"
    elif not model:
        state, reason = ("PENDING_MULTIMODAL_MODEL_NOT_CONFIGURED",
                         "model not configured")
    elif not credential_available:
        state, reason = ("PENDING_MULTIMODAL_CREDENTIAL_MISSING",
                         "credential missing")
    else:
        state, reason = ("HUMAN_REVIEW_REQUIRED",
                         "external calls are not executed by the local workspace")
    return {
        "provider_enabled": enabled,
        "provider_name": provider_name,
        "configured_model": model,
        "credential_available": credential_available,
        "external_call_attempted": False,
        "external_call_count": 0,
        "reason_not_attempted": reason,
        "final_workflow_state": state,
        "no_data_sent": True,
    }


def _provider_escalation(page: int, field: dict, policy: dict,
                         routing_policy: dict) -> dict:
    """Attach one safe terminal workflow state to an unresolved/attempted field."""
    decision = field.get("decision", "")
    attempted = bool(field.get("escalated"))
    record = field.get("escalation_record") or {}
    attempted_model = record.get("model") or ""
    external_calls = int(
        record.get("escalated") is True and attempted_model != "offline-oracle")
    configured = field_policy(field["field_name"])
    eligible = bool(
        configured.get("external_model_allowed", True)
        and configured.get("criticality", "med")
        in routing_policy["paid_escalation_criticalities"]
        and not configured.get("optional", False)
    )
    unresolved = decision not in {
        "INAPPLICABLE", "ACCEPT", "ACCEPT_WITH_FLAG", "ACCEPT_WITH_OVERRIDE"
    }

    state = dict(policy)
    if attempted:
        state["external_call_attempted"] = bool(external_calls)
        state["external_call_count"] = external_calls
        state["reason_not_attempted"] = ""
        state["no_data_sent"] = not bool(external_calls)
        state["final_workflow_state"] = (
            "MULTIMODAL_FAILED" if unresolved else "MULTIMODAL_ATTEMPTED")
    elif decision == "HUMAN_REVIEW" or not eligible:
        state["reason_not_attempted"] = (
            "human review required by governor" if decision == "HUMAN_REVIEW"
            else "not eligible under field policy")
        state["final_workflow_state"] = "HUMAN_REVIEW_REQUIRED"
    return {
        "page": page,
        "field_name": field["field_name"],
        "multimodal_eligible": eligible,
        **state,
    }


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
    empty_extraction = not fields
    provider_policy = _provider_policy_snapshot()
    result = {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": "unstructured",
        "page_count": len(pages),
        "processing_status": _document_status(len(fields), 0),
        "processing_stage": _document_status(len(fields), 0),
        "last_stage_message": ("Limited unstructured extraction completed"
                               if fields else "No meaningful fields were extracted"),
        "fields": [{"page": 1, "fields": fields}],
        "validations": [],
        "governor_summary": {"ACCEPT_WITH_FLAG": len(fields)},
        "retry_summary": {"fields_retried": 0},
        "escalation_summary": {
            "fields_escalated": 0,
            "pending_multimodal": 0,
            "multimodal_attempted": 0,
            "multimodal_failed": 0,
            "pending_human_review": 0,
            "external_provider_calls": 0,
        },
        "provider_state": provider_policy,
        "provider_escalations": [],
        "review_audit": [],
        "human_review_summary": {"required": 0, "completed": 0},
        "unresolved_fields": 0,
        "latency": {"milliseconds": round(latency_ms, 3)},
        "measured_cost": {"usd": round(_local_cost(latency_ms), 9)},
        "projected_cost": {"usd": round(_local_cost(latency_ms), 9)},
        "warnings": [
            "Tier D uses limited label-driven extraction.",
            *(["Tier D label-driven extraction produced no fields; "
               "the page decoded but nothing was resolved."] if empty_extraction else []),
        ],
        "evaluation": None,
        "evidence_semantics": "official_unstructured_adapter",
        "_group_key": item.group_key,
        "_linkage_text": " ".join(texts),
    }
    result["coverage"] = coverage_metrics(result)
    return result


def _process_official_item(item: IntakeFile, tier: str, mode: str,
                           *, form: str | None = None,
                           require_detection: bool = False,
                           progress: Callable[[dict], None] | None = None) -> dict | None:
    started = time.perf_counter()
    stage_latency = new_stage_latency()
    try:
        _stage(progress, ProcessingStage.DECODING, "Decoding document pages")
        decode_started = time.perf_counter()
        pages = decode_pages(item.content, item.source_format)
        record_stage(stage_latency, "tiff_decode", decode_started)
        words_by_page, texts = [], []
        for page_number, page in enumerate(pages, 1):
            _stage(progress, ProcessingStage.PRIMARY_OCR, "Running primary local OCR",
                   current_page=page_number, total_pages=len(pages))
            words, text, ocr_ms = local_ocr(page)
            stage_latency["primary_ocr"] += ocr_ms
            words_by_page.append(words)
            texts.append(text)
        if tier == "D":
            return _official_unstructured_result(
                item, pages, texts, (time.perf_counter() - started) * 1000)
        selection_tier = tier
        _stage(progress, ProcessingStage.ROUTING, "Detecting form and claim pages",
               current_page=1, total_pages=len(pages))
        if form == "auto":
            cms_score = max((_score(text, CMS_MARKERS) for text in texts), default=0)
            ub_score = max((_score(text, UB_MARKERS) for text in texts), default=0)
            form = "ub04" if ub_score > cms_score else "cms1500"
            selection_tier = "C" if form == "ub04" else "auto"
        selection = select_claim_pages(texts, selection_tier)
        if selection.status != "deterministic" or not selection.claim_pages:
            if require_detection:
                return None
            result = _failed_result(
                item, "Claim-page selection abstained; no page was extracted.",
                status="FAILED_EXTRACTION",
            )
            result.update({
                "page_count": len(pages),
                "evidence_semantics": "official_monochrome_adapter",
                "_group_key": item.group_key,
                "_linkage_text": " ".join(texts),
            })
            return result
        page_index = selection.claim_pages[0]
        form = form or ("ub04" if tier == "C" else "cms1500")
        _stage(progress, ProcessingStage.VALIDATING_PRIMARY,
               "Mapping fields and validating primary OCR",
               current_page=page_index + 1, total_pages=len(pages))
        page_result = structured_page(
            pages[page_index], words_by_page[page_index], form,
            item.safe_source_id, preset=mode, run_retry=form != "cms1500",
            stage_latency=stage_latency,
        )
        if form == "cms1500":
            _mark_inactive_cms1500_service_lines(page_result)
            retry_fields = sum(field.state == FieldState.RETRY
                               for field in page_result.fields.values())
            _stage(progress, ProcessingStage.LOCAL_RETRY, "Running local OCR retry",
                   current_page=page_index + 1, total_pages=len(pages),
                   fields_processed=0, applicable_fields=len(page_result.fields),
                   retry_fields=retry_fields)
            retry_cms1500_page(
                page_result, pages[page_index], mode, stage_latency=stage_latency)
            _stage(progress, ProcessingStage.VALIDATING_RETRY,
                   "Revalidating retry candidates",
                   current_page=page_index + 1, total_pages=len(pages),
                   fields_processed=len(page_result.fields),
                   applicable_fields=len(page_result.fields))
        elapsed_ms = (time.perf_counter() - started) * 1000
        cost = _local_cost(elapsed_ms)
        receipt = service.build_receipt(
            page_result,
            [{"operation": "official_local_compute", "cost_usd": cost,
              "latency_ms": elapsed_ms, "meta": {}}],
            mode, elapsed_ms, source_kind="local_workspace",
        )
        reporting_started = time.perf_counter()
        result = _unify_receipts(item, [receipt])
        result["page_count"] = len(pages)
        result["evidence_semantics"] = "official_monochrome_adapter"
        result["_linkage_text"] = " ".join(texts)
        if selection.attachment_pages:
            result["warnings"].append(
                f"{len(selection.attachment_pages)} attachment page(s) excluded from extraction.")
        record_stage(stage_latency, "reporting", reporting_started)
        total_ms = (time.perf_counter() - started) * 1000
        attributed_ms = sum(stage_latency.values())
        result["latency"] = {
            "milliseconds": round(total_ms, 3),
            "stages_ms": {name: round(value, 3)
                          for name, value in stage_latency.items()},
            "unattributed_ms": round(max(0.0, total_ms - attributed_ms), 3),
        }
        if result["escalation_summary"].get("pending_multimodal"):
            _stage(progress, ProcessingStage.MULTIMODAL_PENDING,
                   "Unresolved fields are pending multimodal policy review")
        return result
    except Exception:
        if require_detection:
            return None
        return _failed_result(item, "Official document processing failed; batch continued.")


def _failed_result(item: IntakeFile, warning: str, *, status: str = "FAILED") -> dict:
    final_stage = status if status in ProcessingStage.__members__ else "FAILED"
    return {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": "unknown",
        "page_count": item.page_count or 0,
        "processing_status": status,
        "processing_stage": final_stage,
        "last_stage_message": warning,
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
    fields, validations, provider_escalations, review_evidence = [], [], [], []
    governor = Counter()
    retried = escalated = unresolved = 0
    accepted_without_retry = accepted_after_retry = accepted_with_flag = 0
    inapplicable = pending_local_retry = pending_multimodal = pending_human_review = 0
    multimodal_failed = external_provider_calls = 0
    measured = projected = latency = 0.0
    linkage_values = []
    field_count = 0
    provider_policy = _provider_policy_snapshot()
    for page_number, receipt in enumerate(receipts, 1):
        receipt_mode = receipt.get("operating_mode", {}).get("key", service.DEFAULT_MODE)
        routing_policy = mode_policy(receipt_mode)
        page_fields = receipt["final_output"]
        field_count += len(page_fields)
        fields.append({"page": page_number, "fields": page_fields})
        for field in receipt["fields"]:
            validations.append({
                "page": page_number,
                "field_name": field["field_name"],
                "results": field["validation"],
            })
            governor[field["decision"]] += 1
            review_evidence.append({
                "page": page_number,
                "field_name": field["field_name"],
                "criticality": field["criticality"],
                "bbox": field["bbox"],
                "primary_candidate": field["primary_candidate"],
                "retry_candidate": field["retry_candidate"],
                "multimodal_candidate": field["escalation_candidate"],
                "confidence": field["confidence"],
                "validation_failures": [row for row in field["validation"]
                                        if row["verdict"] == "FAIL"],
                "reason": (field["governor_decisions"][-1]["reason"]
                           if field["governor_decisions"] else "Unresolved field"),
                "state": field["decision"],
            })
            retried += int(field["retry_count"] > 0)
            escalated += int(field["escalated"])
            accepted_without_retry += int(
                field["decision"] == "ACCEPT" and not field["retry_count"])
            accepted_after_retry += int(
                field["decision"] == "ACCEPT" and field["retry_count"] > 0)
            accepted_with_flag += int(field["decision"] == "ACCEPT_WITH_FLAG")
            inapplicable += int(field["decision"] == "INAPPLICABLE")
            pending_local_retry += int(field["decision"] == "RETRY")
            pending_multimodal += int(
                field["decision"] == "ESCALATE" and not field["escalated"])
            pending_human_review += int(field["decision"] == "HUMAN_REVIEW")
            unresolved += int(field["decision"] not in {
                "INAPPLICABLE", "ACCEPT", "ACCEPT_WITH_FLAG", "ACCEPT_WITH_OVERRIDE"
            })
            if field["decision"] not in {
                    "INAPPLICABLE", "ACCEPT", "ACCEPT_WITH_FLAG", "ACCEPT_WITH_OVERRIDE"
            } or field["escalated"]:
                provider_state = _provider_escalation(
                    page_number, field, provider_policy, routing_policy)
                provider_escalations.append(provider_state)
                external_provider_calls += provider_state["external_call_count"]
                multimodal_failed += int(
                    provider_state["final_workflow_state"] == "MULTIMODAL_FAILED")
            if field.get("final_value") not in (None, ""):
                linkage_values.append(str(field["final_value"]))
        measured += float(receipt["costs"]["measured_total_automated"]["value_usd"])
        projected += float(receipt["costs"]["projected_total_automated"]["value_usd"])
        latency += float(receipt["latency_ms"])
    document_type = next(iter(document_types)) if len(document_types) == 1 else "mixed"
    empty_extraction = field_count == 0
    warnings = ([f"Document classified as {document_type}; the page decoded but no "
                 "fields were extracted, so it was not successfully processed."]
                if empty_extraction else [])
    if pending_multimodal:
        warnings.append(
            f"{pending_multimodal} field(s) pending escalation; external providers are "
            "disabled and no data was sent."
        )
    if pending_human_review:
        warnings.append(f"{pending_human_review} field(s) require human review.")
    if pending_local_retry:
        warnings.append(f"{pending_local_retry} field(s) remain pending local retry.")
    result = {
        "document_id": item.safe_source_id,
        "safe_source_id": item.safe_source_id,
        "source_file": item.filename,
        "source_format": item.source_format,
        "source_role": item.role.value,
        "document_type": document_type,
        "page_count": len(receipts),
        "processing_status": _document_status(field_count, unresolved),
        "processing_stage": _document_status(field_count, unresolved),
        "last_stage_message": (
            "Processing completed" if not unresolved and field_count
            else "Processing completed with unresolved fields" if field_count
            else "No meaningful fields were extracted"),
        "fields": fields,
        "validations": validations,
        "governor_summary": dict(sorted(governor.items())),
        "retry_summary": {"fields_retried": retried},
        "resolution_summary": {
            "accepted_without_retry": accepted_without_retry,
            "accepted_after_local_retry": accepted_after_retry,
            "accepted_with_flag": accepted_with_flag,
            "inapplicable": inapplicable,
            "pending_local_retry": pending_local_retry,
            "pending_multimodal": pending_multimodal,
            "multimodal_attempted": escalated,
            "pending_human_review": pending_human_review,
            "external_provider_calls": external_provider_calls,
        },
        "escalation_summary": {
            "fields_escalated": escalated,
            "pending_multimodal": pending_multimodal,
            "multimodal_attempted": escalated,
            "multimodal_failed": multimodal_failed,
            "pending_human_review": pending_human_review,
            "external_provider_calls": external_provider_calls,
        },
        "provider_state": provider_policy,
        "provider_escalations": provider_escalations,
        "unresolved_fields": unresolved,
        "latency": {"milliseconds": round(latency, 3)},
        "measured_cost": {"usd": round(measured, 9)},
        "projected_cost": {"usd": round(projected, 9)},
        "warnings": warnings,
        "evaluation": None,
        "review_audit": [],
        "human_review_summary": {"required": pending_human_review + pending_multimodal,
                                 "completed": 0},
        "_review_evidence": review_evidence,
        "_group_key": item.group_key,
        "_linkage_text": " ".join(linkage_values),
    }
    result["coverage"] = coverage_metrics(result)
    return result


def _red_router_abstains(item: IntakeFile) -> bool:
    """True when the colour form-grid router cannot classify the first page."""
    from engine.router import route
    try:
        first = decode_pages(item.content, item.source_format)[0]
    except Exception:
        return False
    try:
        return route(first)["document_type"] not in {"cms1500", "ub04"}
    except Exception:
        return False


def process_item(item: IntakeFile, mode: str = service.DEFAULT_MODE,
                 *, page_processor: PageProcessor | None = None,
                 progress: Callable[[dict], None] | None = None) -> dict:
    """Process every decoded page without consulting expected output."""
    def finish(result: dict) -> dict:
        stage = _final_stage(result["processing_status"])
        result["processing_stage"] = stage.value
        result.setdefault("last_stage_message", result["processing_status"])
        _stage(progress, stage, result["last_stage_message"])
        return result

    if item.role != FileRole.CLAIM_DOCUMENT:
        return finish(_failed_result(
            item, "File role is not a claim document.", status="SKIPPED"))
    if item.status == "ERROR":
        return finish(_failed_result(item, item.warning or "Document intake failed."))
    if page_processor is None and _red_router_abstains(item):
        # The red-ink router only fingerprints colour dropout forms, so a
        # monochrome scan reaches it with an empty mask and is dismissed as
        # unstructured. Route by content instead of by parent folder name.
        official = _process_official_item(
            item, "auto", mode, form="auto", require_detection=True,
            progress=progress)
        if official is not None:
            return finish(official)
    processor = page_processor or _default_page_processor
    try:
        _stage(progress, ProcessingStage.DECODING, "Decoding document pages")
        pages = decode_pages(item.content, item.source_format)
        receipts = []
        for index, page in enumerate(pages, 1):
            _stage(progress, ProcessingStage.ROUTING,
                   "Routing document and preparing local extraction",
                   current_page=index, total_pages=len(pages))
            _stage(progress, ProcessingStage.PRIMARY_OCR,
                   "Running primary OCR and governed local retry",
                   current_page=index, total_pages=len(pages))
            receipts.append(processor(page, f"{item.safe_source_id}-p{index}", mode))
        return finish(_unify_receipts(item, receipts))
    except Exception:
        return finish(_failed_result(
            item, "Document processing failed; other batch items continued."))


def _job_id(items: list[IntakeFile], mode: str) -> str:
    material = "|".join([mode, *(item.safe_source_id for item in items)])
    return f"batch-{hashlib.sha256(material.encode()).hexdigest()[:12]}"


def _batch_status(results: list[dict]) -> str:
    """A batch never claims clean success while any document needs attention."""
    statuses = {result["processing_status"] for result in results}
    if statuses & {"FAILED", "FAILED_EXTRACTION"}:
        return "COMPLETED_WITH_ERRORS"
    if statuses & {"PARTIAL"}:
        return "COMPLETED_WITH_REVIEW"
    return "COMPLETED"


def summarize_results(results: list[dict]) -> dict:
    counts = Counter(result["processing_status"] for result in results)
    processed = [result for result in results
                 if result["processing_status"] in PRODUCED_OUTPUT]
    page_results = [result for result in results if result["processing_status"] not in {
        "SKIPPED", "DUPLICATE", "CANCELLED"
    }]
    pages = sum(int(result.get("page_count") or 0) for result in page_results)
    latency = sum(result["latency"]["milliseconds"] for result in processed)
    types = Counter(result["document_type"] for result in processed)
    resolutions = [result.get("resolution_summary") or {} for result in processed]
    escalations = [result.get("escalation_summary") or {} for result in processed]
    governors = [result.get("governor_summary") or {} for result in processed]
    retries = [result.get("retry_summary") or {} for result in processed]
    coverages = [result.get("coverage") or coverage_metrics(result) for result in processed]
    human_reviews = [result.get("human_review_summary") or {} for result in processed]

    def total(rows: list[dict], key: str) -> int:
        return sum(int(row.get(key) or 0) for row in rows)

    return {
        "files": len(results),
        "pages": pages,
        "success": counts["COMPLETED"],
        "partial": counts["PARTIAL"],
        "failed_extraction": counts["FAILED_EXTRACTION"],
        "failed": counts["FAILED"],
        "skipped": counts["SKIPPED"] + counts["DUPLICATE"],
        "cancelled": counts["CANCELLED"],
        "document_types": dict(sorted(types.items())),
        "total_fields": sum(
            len(page.get("fields") or {})
            for result in processed for page in (result.get("fields") or [])),
        "accepted": total(governors, "ACCEPT"),
        "accepted_with_flag": total(governors, "ACCEPT_WITH_FLAG"),
        "retry_attempted": total(retries, "fields_retried"),
        "retry_resolved": total(resolutions, "accepted_after_local_retry"),
        "primary_resolved": total(resolutions, "accepted_without_retry"),
        "unresolved_fields": sum(
            int(result.get("unresolved_fields") or 0) for result in processed),
        "inapplicable": total(resolutions, "inapplicable"),
        "pending_multimodal": total(escalations, "pending_multimodal"),
        "multimodal_attempted": total(escalations, "multimodal_attempted"),
        "multimodal_failed": total(escalations, "multimodal_failed"),
        "human_review_required": total(escalations, "pending_human_review"),
        "human_review_completed": total(human_reviews, "completed"),
        "external_calls": total(escalations, "external_provider_calls"),
        "applicable_fields": total(coverages, "applicable_fields"),
        "fields_produced": total(coverages, "fields_produced"),
        "validated_fields": total(coverages, "validated_fields"),
        "measured_cost_usd": round(sum(
            result["measured_cost"]["usd"] for result in processed), 9),
        "projected_cost_usd": round(sum(
            result["projected_cost"]["usd"] for result in processed), 9),
        "latency_ms": round(latency, 3),
        "mean_latency_ms": round(latency / len(processed), 3) if processed else 0.0,
        "throughput_pages_per_minute": round(pages * 60000 / latency, 6) if latency else 0.0,
        "accuracy": None,
        "critical_accuracy": None,
    }


def coverage_metrics(result: dict) -> dict:
    """Coverage is extraction completeness, never measured accuracy."""
    pages = result.get("fields") or []
    fields = [field for page in pages for field in (page.get("fields") or {}).values()]
    known_schema = result.get("document_type") in {"cms1500", "ub04"} and bool(fields)
    if not known_schema:
        return {
            "available": False,
            "message": "Coverage unavailable â€” document schema not established",
        }
    inapplicable = sum(field.get("state") == "INAPPLICABLE" for field in fields)
    applicable_fields = [field for field in fields if field.get("state") != "INAPPLICABLE"]
    produced = sum(field.get("value") not in (None, "") for field in applicable_fields)
    validated = sum(field.get("state") in RESOLVED_FIELD_STATES
                    for field in applicable_fields)
    confidence = {"high": 0, "medium": 0, "low": 0}
    for field in applicable_fields:
        value = float(field.get("confidence") or 0)
        confidence["high" if value >= .85 else "medium" if value >= .60 else "low"] += 1
    denominator = len(applicable_fields)
    return {
        "available": True,
        "schema_fields": len(fields),
        "applicable_fields": denominator,
        "inapplicable_fields": inapplicable,
        "fields_produced": produced,
        "validated_fields": validated,
        "unresolved_fields": sum(
            field.get("state") not in RESOLVED_FIELD_STATES
            for field in applicable_fields),
        "extraction_coverage": produced / denominator if denominator else None,
        "validated_coverage": validated / denominator if denominator else None,
        "confidence_distribution": confidence,
    }


def build_review_queue(result: dict) -> list[dict]:
    provider_by_field = {
        (row["page"], row["field_name"]): row
        for row in result.get("provider_escalations", [])
    }
    queue = []
    for evidence in result.get("_review_evidence", []):
        if evidence["state"] in RESOLVED_FIELD_STATES:
            continue
        provider = provider_by_field.get((evidence["page"], evidence["field_name"]), {})
        queue.append({
            "document_id": result["safe_source_id"],
            **evidence,
            "provider_state": provider.get("final_workflow_state", "HUMAN_REVIEW_REQUIRED"),
        })
    return sorted(queue, key=lambda row: (row["page"], row["field_name"]))


def _refresh_result(result: dict) -> None:
    all_fields = [field for page in result.get("fields", [])
                  for field in page.get("fields", {}).values()]
    result["unresolved_fields"] = sum(
        field.get("state") not in RESOLVED_FIELD_STATES for field in all_fields)
    result["processing_status"] = _document_status(
        len(all_fields), result["unresolved_fields"])
    result["processing_stage"] = result["processing_status"]
    result["last_stage_message"] = (
        "Human review correction saved" if result.get("review_audit")
        else result["processing_status"])
    result["coverage"] = coverage_metrics(result)
    pending_multimodal = sum(
        field.get("state") == "ESCALATE" for field in all_fields)
    pending_human = sum(field.get("state") == "HUMAN_REVIEW" for field in all_fields)
    result.setdefault("escalation_summary", {})["pending_multimodal"] = pending_multimodal
    result["escalation_summary"]["pending_human_review"] = pending_human
    result.setdefault("resolution_summary", {})["pending_multimodal"] = pending_multimodal
    result["resolution_summary"]["pending_human_review"] = pending_human
    governor = Counter(field.get("state") for field in all_fields
                       if field.get("state") != "INAPPLICABLE")
    if sum(field.get("state") == "INAPPLICABLE" for field in all_fields):
        governor["INAPPLICABLE"] = sum(
            field.get("state") == "INAPPLICABLE" for field in all_fields)
    result["governor_summary"] = dict(sorted(governor.items()))
    result["resolution_summary"].update({
        "inapplicable": governor["INAPPLICABLE"],
        "accepted_with_flag": governor["ACCEPT_WITH_FLAG"],
    })
    reviewed = {(row["page"], row["field_name"])
                for row in result.get("review_audit", [])}
    completed = 0
    for page in result.get("fields", []):
        completed += sum(
            (page["page"], name) in reviewed
            and field.get("state") in RESOLVED_FIELD_STATES
            for name, field in page.get("fields", {}).items()
        )
    result["human_review_summary"] = {
        "required": len(build_review_queue(result)),
        "completed": completed,
    }


def apply_human_review(result: dict, *, page: int, field_name: str, action: str,
                       value, reason: str, reviewer_id: str = "local-reviewer") -> dict:
    """Apply one session-local correction without writing field values to logs."""
    if not reason.strip():
        raise ValueError("A review reason is required.")
    updated = copy.deepcopy(result)
    page_row = next((row for row in updated.get("fields", []) if row["page"] == page), None)
    if not page_row or field_name not in page_row["fields"]:
        raise KeyError("Review field was not found in this document.")
    field = page_row["fields"][field_name]
    if action == "REJECT_DOCUMENT":
        updated["processing_status"] = "FAILED"
        updated["processing_stage"] = ProcessingStage.FAILED.value
    elif action == "LEAVE_UNRESOLVED":
        field["state"] = "HUMAN_REVIEW"
    elif action == "MARK_NOT_APPLICABLE":
        field.update({"value": None, "state": "INAPPLICABLE", "confidence": None,
                      "stamps": [{"validator": "human_review",
                                  "verdict": "INAPPLICABLE"}]})
    else:
        final_value = None if action == "MARK_BLANK" else value
        context = {name: candidate.get("value")
                   for name, candidate in page_row["fields"].items()}
        context[field_name] = final_value
        stamps = validate_field(field_name, final_value, context)
        failed = any(stamp.verdict == Verdict.FAIL for stamp in stamps)
        field.update({
            "value": final_value,
            "state": "HUMAN_REVIEW" if failed else "ACCEPT_WITH_OVERRIDE",
            "stamps": [{"validator": stamp.validator, "verdict": stamp.verdict.value,
                        "detail": stamp.detail} for stamp in stamps],
            "override": {
                "reviewer_id": reviewer_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "resolution": "HUMAN_CORRECTED" if not failed else "VALIDATION_FAILED",
            },
        })
    audit = {
        "page": page,
        "field_name": field_name,
        "action": action,
        "reviewer_id": reviewer_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "resulting_state": field.get("state"),
    }
    updated.setdefault("review_audit", []).append(audit)
    for evidence in updated.get("_review_evidence", []):
        if evidence["page"] == page and evidence["field_name"] == field_name:
            evidence["state"] = field.get("state")
    for validation in updated.get("validations", []):
        if validation["page"] == page and validation["field_name"] == field_name:
            validation["results"] = field.get("stamps", [])
    for provider in updated.get("provider_escalations", []):
        if provider["page"] == page and provider["field_name"] == field_name:
            provider["final_workflow_state"] = (
                ProcessingStage.HUMAN_REVIEW_COMPLETED.value
                if field.get("state") in {"INAPPLICABLE", "ACCEPT_WITH_OVERRIDE"}
                else ProcessingStage.HUMAN_REVIEW_REQUIRED.value)
    _refresh_result(updated)
    if action == "REJECT_DOCUMENT":
        updated["processing_status"] = "FAILED"
        updated["processing_stage"] = ProcessingStage.FAILED.value
        updated["last_stage_message"] = "Document rejected during human review"
    return updated


def retry_document(batch: dict, item: IntakeFile, *, mode: str | None = None,
                   processor: Callable[[IntakeFile, str], dict] | None = None) -> dict:
    """Retry one document, retaining prior attempts only in session memory."""
    updated = copy.deepcopy(batch)
    selected_mode = mode or updated.get("operating_mode") or service.DEFAULT_MODE
    process = processor or process_item
    replacement = process(item, selected_mode)
    old = next((row for row in updated["documents"]
                if row["safe_source_id"] == item.safe_source_id), None)
    if old is None:
        raise KeyError("Retry document is not part of this batch.")
    prior = copy.deepcopy(old)
    prior.pop("_prior_results", None)
    replacement["_prior_results"] = [*old.get("_prior_results", []), prior]
    replacement["retry_count"] = int(old.get("retry_count") or 0) + 1
    replacement["retry_history"] = [*old.get("retry_history", []), {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from_status": old["processing_status"],
        "to_status": replacement["processing_status"],
        "external_calls": int(
            (replacement.get("escalation_summary") or {}).get(
                "external_provider_calls") or 0),
    }]
    updated["documents"] = [replacement if row is old or (
        row["safe_source_id"] == item.safe_source_id) else row
        for row in updated["documents"]]
    updated["processing_status"] = _batch_status(updated["documents"])
    updated["operating_mode"] = selected_mode
    updated["mode_policy"] = mode_policy(selected_mode)
    updated["summary"] = summarize_results(updated["documents"])
    updated["evaluation"] = None
    return updated


def run_batch(items: list[IntakeFile], mode: str = service.DEFAULT_MODE,
              *, processor: Callable[[IntakeFile, str], dict] | None = None,
              progress: Callable[[int, int, dict], None] | None = None,
              stop_requested: Callable[[], bool] | None = None,
              existing_results: dict[str, dict] | None = None,
              stage_progress: Callable[[dict], None] | None = None,
              evaluate: bool = False) -> dict:
    """Process deterministically, skip duplicates, and continue after failures."""
    ordered = sorted(items, key=lambda item: (item.filename.casefold(), item.safe_source_id))
    process = processor or (lambda item, selected_mode: process_item(item, selected_mode))
    existing_results = existing_results or {}
    seen = set()
    results = []
    for index, item in enumerate(ordered, 1):
        def document_progress(event: dict) -> None:
            if stage_progress:
                stage_progress({
                    "document_number": index,
                    "total_documents": len(ordered),
                    "document": item.filename,
                    **event,
                })

        document_progress({"stage": ProcessingStage.QUEUED.value,
                           "message": "Document queued"})
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
                result = (process_item(item, mode, progress=document_progress)
                          if processor is None else process(item, mode))
            except Exception:
                result = _failed_result(
                    item, "Document processing failed; other batch items continued.")
        document_progress({
            "stage": _final_stage(result["processing_status"]).value,
            "message": result.get("last_stage_message") or result["processing_status"],
        })
        seen.add(item.safe_source_id)
        results.append(result)
        if progress:
            progress(index, len(ordered), result)
    batch = {
        "batch_job_id": _job_id(ordered, mode),
        "processing_status": _batch_status(results),
        "operating_mode": mode,
        "mode_policy": mode_policy(mode),
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
        "denominator": len(comparisons),
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

    expected_keys = {
        (group, "record", record.ordinal)
        for group, records in expected_by_group.items() for record in records
    } | {(group, "synthetic", doc_id) for group, doc_id in synthetic_by_id}
    all_comparisons = []
    all_critical = []
    pairing_statuses = Counter()
    matched_expected = set()
    documents_found = sum(
        result.get("source_role") == FileRole.CLAIM_DOCUMENT.value
        and result.get("processing_status") not in {"DUPLICATE", "CANCELLED"}
        for result in batch["documents"])
    for result in batch["documents"]:
        if result["processing_status"] not in PRODUCED_OUTPUT:
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
            matched_key = (group, "synthetic", result["source_file"].rsplit(".", 1)[0])
        else:
            records = expected_by_group.get(group, [])
            link = link_record(result.get("_linkage_text", ""), records)
            linkage = link.safe_receipt()
            record = next((row for row in records if row.ordinal == link.record_ordinal), None)
            expected = claimroute_expected(record) if record else {}
            matched_key = ((group, "record", link.record_ordinal)
                           if record is not None else None)
        comparisons = compare_fields(expected, actual) if expected else []
        result["evaluation"] = _comparison_receipt(comparisons, linkage)
        pairing_statuses[linkage["status"]] += 1
        if linkage["status"] == "deterministic" and matched_key is not None:
            matched_expected.add(matched_key)
        all_comparisons.extend(comparisons)
        all_critical.extend(row for row in comparisons
                            if field_policy(row["field_name"]).get("criticality") == "high")
    evaluation = {
        "documents_found": documents_found,
        "expected_records_found": len(expected_keys),
        "deterministic_pairs": pairing_statuses["deterministic"],
        "ambiguous_pairs": pairing_statuses["ambiguous"],
        "unmatched_documents": documents_found - pairing_statuses["deterministic"],
        "unmatched_expected_records": max(0, len(expected_keys) - len(matched_expected)),
        "documents_linked": pairing_statuses["deterministic"],
        "evaluated_fields": len(all_comparisons),
        "denominator": len(all_comparisons),
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
