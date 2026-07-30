"""Framework-neutral adapter between the demo UI and the extraction engine."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from PIL import Image, ImageDraw

from engine.extract import run_page
from engine.governor import field_policy
from engine.ledger import CostLedger
from engine.schemas import FieldState, PageResult

ROOT = Path(__file__).resolve().parents[1]
MODES_PATH = ROOT / "configs" / "operating_modes.yaml"
CALIBRATION_PATH = ROOT / "eval" / "results" / "day9_calibration_summary.json"
BENCHMARK_PATH = ROOT / "eval" / "frozen" / "final_benchmark_summary.json"
SYNTHETIC_ROOT = ROOT / "data" / "generated"

DEFAULT_MODE = "balanced"
MODE_LABELS = {"economy": "Economy", "balanced": "Balanced", "accuracy": "Strict Accuracy"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
ALLOWED_FORMATS = {"PNG", "JPEG", "TIFF"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGE_COUNT = 1
PROCESSING_TIMEOUT_SECONDS = 120


class UploadValidationError(ValueError):
    pass


class AppProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentInput:
    filename: str
    image: Image.Image
    file_format: str
    size_bytes: int
    page_count: int
    sha256: str


def load_operating_modes(path: Path = MODES_PATH) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    modes = data.get("modes", {})
    if DEFAULT_MODE not in modes:
        raise ValueError("Balanced operating mode is missing")
    return modes


def load_calibration_summary(path: Path = CALIBRATION_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_benchmark_summary(path: Path = BENCHMARK_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def list_synthetic_examples(root: Path = SYNTHETIC_ROOT) -> list[dict]:
    examples = []
    for image_path in sorted(root.glob("*/[a-z]*/images/*.png")):
        tier = image_path.parents[1].name
        if tier not in {"clean", "noisy", "ugly"}:
            continue
        examples.append({
            "label": f"{image_path.stem} / {tier}",
            "doc_id": image_path.stem,
            "tier": tier,
            "path": image_path,
        })
    return examples


def inspect_upload(filename: str, content: bytes, *, max_bytes: int = MAX_UPLOAD_BYTES,
                   max_pages: int = MAX_PAGE_COUNT) -> DocumentInput:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            "Unsupported file type. Use PNG, JPEG, or single-page TIFF.")
    if not content:
        raise UploadValidationError("The uploaded file is empty.")
    if len(content) > max_bytes:
        raise UploadValidationError(
            f"File size exceeds the {max_bytes / 1024 / 1024:g} MB limit.")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            file_format = (probe.format or "").upper()
            page_count = int(getattr(probe, "n_frames", 1))
            probe.verify()
        with Image.open(io.BytesIO(content)) as source:
            source.seek(0)
            image = source.convert("RGB").copy()
    except Exception as exc:
        raise UploadValidationError("The file is not a readable claim image.") from exc
    if file_format not in ALLOWED_FORMATS:
        raise UploadValidationError("The detected file type is not supported.")
    if page_count > max_pages:
        raise UploadValidationError(
            f"Document page limit is {max_pages}; received {page_count} pages.")
    return DocumentInput(
        filename=Path(filename).name,
        image=image,
        file_format=file_format,
        size_bytes=len(content),
        page_count=page_count,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def load_synthetic(example: dict) -> DocumentInput:
    path = Path(example["path"])
    content = path.read_bytes()
    document = inspect_upload(path.name, content)
    return document


def _same_value(left, right) -> bool:
    return "".join(str(left or "").split()).lower() == "".join(str(right or "").split()).lower()


def _source_attempt(field):
    matching = [attempt for attempt in field.attempts if _same_value(attempt.value, field.value)]
    return matching[-1] if matching else (field.attempts[-1] if field.attempts else None)


def _status_label(field) -> str:
    if field.state == FieldState.HUMAN_REVIEW:
        return "Human review"
    if field.state == FieldState.ACCEPT_WITH_FLAG:
        return "Flagged"
    if any(attempt.rung == "multimodal" for attempt in field.attempts):
        return "AI escalated"
    if any(attempt.rung == "retry_ocr" for attempt in field.attempts):
        return "Retried locally"
    return "Accepted"


def _field_row(name: str, field, decisions: list, escalation: dict | None) -> dict:
    source = _source_attempt(field)
    retry_count = field.attempts_used("retry_ocr")
    escalated = field.attempts_used("multimodal") > 0
    measured_cost = sum(a.cost_usd for a in field.attempts if a.engine != "offline-oracle")
    projected_cost = sum(a.cost_usd for a in field.attempts if a.engine == "offline-oracle")
    attempts = [{
        "rung": attempt.rung,
        "engine": attempt.engine,
        "value": attempt.value,
        "confidence": round(attempt.confidence, 4),
        "latency_ms": round(attempt.latency_ms, 2),
        "cost_usd": round(attempt.cost_usd, 8),
    } for attempt in field.attempts]
    return {
        "field_name": name,
        "final_value": field.value,
        "confidence": round(field.confidence, 4),
        "criticality": field_policy(name).get("criticality", "med"),
        "source_engine": source.engine if source else "unknown",
        "decision": field.state.value,
        "status": _status_label(field),
        "validation_status": ", ".join(
            sorted({stamp.verdict.value for stamp in field.stamps})) or "NOT_APPLICABLE",
        "validation": [{
            "validator": stamp.validator,
            "verdict": stamp.verdict.value,
            "detail": stamp.detail,
        } for stamp in field.stamps],
        "retry_count": retry_count,
        "escalated": escalated,
        "latency_ms": round(sum(a.latency_ms for a in field.attempts), 2),
        "measured_cost_usd": round(measured_cost, 8),
        "projected_cost_usd": round(projected_cost, 8),
        "bbox": list(field.bbox) if field.bbox else None,
        "primary_candidate": next((a.value for a in field.attempts if a.rung == "primary_ocr"), None),
        "retry_candidate": next((a.value for a in field.attempts if a.rung == "retry_ocr"), None),
        "escalation_candidate": next((a.value for a in field.attempts if a.rung == "multimodal"), None),
        "processing_path": attempts,
        "governor_decisions": [{"state": state, "reason": reason}
                               for state, reason in decisions],
        "escalation_record": escalation,
    }


def build_receipt(page: PageResult, ledger_entries: list[dict], mode: str,
                  elapsed_ms: float, *, source_kind: str) -> dict:
    field_rows = [_field_row(name, field, page.decisions.get(name, []),
                             page.escalations.get(name))
                  for name, field in page.fields.items()]
    escalated = sum(row["escalated"] for row in field_rows)
    retried = sum(row["retry_count"] > 0 for row in field_rows)
    flagged = sum(row["decision"] == FieldState.ACCEPT_WITH_FLAG.value for row in field_rows)
    human = sum(row["decision"] == FieldState.HUMAN_REVIEW.value for row in field_rows)
    accepted_locally = sum(
        row["decision"] == FieldState.ACCEPT.value and not row["retry_count"] and not row["escalated"]
        for row in field_rows)

    local_entries = [entry for entry in ledger_entries
                     if not entry.get("operation", "").startswith("escalate_")]
    oracle_entries = [entry for entry in ledger_entries
                      if entry.get("operation") == "escalate_offline-oracle"]
    live_entries = [entry for entry in ledger_entries
                    if entry.get("operation", "").startswith("escalate_")
                    and entry.get("operation") not in {
                        "escalate_offline-oracle", "escalate_intent", "escalate_blocked"}]
    local_cost = sum(float(entry.get("cost_usd", 0)) for entry in local_entries)
    projected_api = sum(float(entry.get("cost_usd", 0)) for entry in oracle_entries)
    measured_api = sum(float(entry.get("cost_usd", 0)) for entry in live_entries)
    input_tokens = sum(int(entry.get("meta", {}).get("input_tokens") or 0)
                       for entry in oracle_entries + live_entries)
    output_tokens = sum(int(entry.get("meta", {}).get("output_tokens") or 0)
                        for entry in oracle_entries + live_entries)

    modes = load_operating_modes()
    return {
        "document": {
            "document_id": page.doc_id,
            "page_id": page.page_id,
            "document_type": page.doc_type,
            "page_count": 1,
            "quality_score": round(page.quality_score, 4),
            "source_kind": source_kind,
            "local_only": True,
        },
        "operating_mode": {
            "key": mode,
            "label": MODE_LABELS[mode],
            "basis": "CONFIGURED ASSUMPTION",
            "configuration": modes[mode],
        },
        "funnel": {
            "fields_detected": len(field_rows),
            "accepted_locally": accepted_locally,
            "accepted_with_flag": flagged,
            "locally_retried": retried,
            "escalated": escalated,
            "human_review": human,
            "api_calls_avoided": len(field_rows) - escalated,
        },
        "costs": {
            "local_compute": {"basis": "MEASURED", "value_usd": round(local_cost, 8)},
            "api": {"basis": "PROJECTED", "value_usd": round(projected_api, 8)},
            "measured_api": {"basis": "MEASURED", "value_usd": round(measured_api, 8)},
            "measured_total_automated": {
                "basis": "MEASURED", "value_usd": round(local_cost + measured_api, 8)},
            "projected_total_automated": {
                "basis": "PROJECTED", "value_usd": round(local_cost + projected_api, 8)},
        },
        "projections": {
            str(pages): round((local_cost + projected_api) * pages, 4)
            for pages in (1_000, 1_000_000, 10_000_000)
        },
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "latency_ms": round(elapsed_ms, 2),
        "fields": field_rows,
        "final_output": page.to_json_dict(),
    }


def process_document(image: Image.Image, doc_id: str, mode: str, *, source_kind: str,
                     tier: str = "clean", runner: Callable = run_page,
                     ledger_dir: Path | None = None,
                     timeout_seconds: int = PROCESSING_TIMEOUT_SECONDS) -> dict:
    if mode not in load_operating_modes():
        raise ValueError(f"Unknown operating mode: {mode}")
    if source_kind not in {"upload", "bundled_synthetic"}:
        raise ValueError(f"Unknown document source: {source_kind}")
    run_escalate = source_kind == "bundled_synthetic"
    model = "offline-oracle" if run_escalate else None
    try:
        with tempfile.TemporaryDirectory(prefix="claimroute-", dir=ledger_dir) as temp_dir:
            ledger = CostLedger(Path(temp_dir) / "ledger.jsonl")
            started = time.perf_counter()
            page = runner(image, doc_id, ledger, preset_name=mode,
                          run_escalate=run_escalate, escalate_model=model, tier=tier)
            elapsed_ms = (time.perf_counter() - started) * 1000
            entries = ledger.entries()
        if elapsed_ms > timeout_seconds * 1000:
            raise AppProcessingError("Extraction exceeded the processing timeout.")
        return build_receipt(page, entries, mode, elapsed_ms, source_kind=source_kind)
    except AppProcessingError:
        raise
    except Exception as exc:
        raise AppProcessingError(
            "Extraction failed. The document was not retained; review local diagnostics.") from exc


def export_json(receipt: dict, *, audit: bool) -> str:
    if audit:
        payload = {key: value for key, value in receipt.items() if key != "final_output"}
    else:
        payload = {
            "document": receipt["document"],
            "operating_mode": receipt["operating_mode"]["label"],
            "fields": receipt["final_output"],
        }
    return json.dumps(payload, indent=2, sort_keys=True)


def draw_overlay(image: Image.Image, fields: list[dict]) -> Image.Image:
    result = image.convert("RGB").copy()
    draw = ImageDraw.Draw(result)
    colors = {
        "Accepted": "#087f5b", "Flagged": "#b26a00", "Retried locally": "#146c94",
        "AI escalated": "#7048a8", "Human review": "#c92a2a",
    }
    for row in fields:
        if not row["bbox"]:
            continue
        box = tuple(round(value) for value in row["bbox"])
        color = colors.get(row["status"], "#334155")
        draw.rectangle(box, outline=color, width=3)
    return result


def crop_field(image: Image.Image, bbox: list | None) -> Image.Image | None:
    if not bbox:
        return None
    x0, y0, x1, y1 = (round(value) for value in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.width, x1), min(image.height, y1)
    return image.crop((x0, y0, x1, y1)) if x1 > x0 and y1 > y0 else None
