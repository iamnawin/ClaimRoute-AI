"""Vision adapter interface — Tier-2 escalation, model-agnostic.

Every adapter speaks the same request/response contract or it doesn't play,
exactly like engine/ocr/base.py. Adding a provider is a new subclass plus a
price row; no pipeline code changes. That is the "model-agnostic orchestration"
claim, kept honest by the interface rather than asserted in a slide.

The response is a CANDIDATE, never truth. It is grounded, revalidated, and
re-enters the governor alongside the OCR candidates.
"""
from __future__ import annotations

import json
import re
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from engine.ocr.base import normalize_text

def _load_prices() -> dict:
    """Frozen benchmark prices, overlaid with live-provider prices.

    configs/prices.yaml is hashed into the benchmark candidate manifest
    (eval/official/freeze_readiness.py), so a vendor price change must never be
    written there. Live rows live in configs/live_provider_prices.yaml, which is
    not frozen, and are merged on top here. The overlay is optional: if the file
    is absent, the frozen table is used unchanged.

    Rows are namespaced (`openrouter_*`) rather than overwriting frozen rows, so
    the overlay adds models rather than silently repricing a benchmarked one.
    """
    # encoding is explicit: bare open() uses the ANSI codepage on Windows, which
    # mangles non-ASCII characters in the price-row notes.
    prices = yaml.safe_load(
        Path("configs/prices.yaml").read_text(encoding="utf-8"))
    overlay_path = Path("configs/live_provider_prices.yaml")
    if not overlay_path.exists():
        return prices
    overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    for section, rows in overlay.items():
        if isinstance(rows, dict) and isinstance(prices.get(section), dict):
            prices[section].update(rows)
    return prices


_PRICES = _load_prices()

# Strict, field-scoped, and deliberately boring: one box, one value, no prose.
PROMPT = """You are reading ONE field box cropped from a US healthcare claim form.

Field: {field_name}
Expected content: {expectation}

Return ONLY a JSON object, no markdown, with exactly these keys:
  "value"        - the field's value, transcribed exactly as printed. Use "" if the box is empty.
  "visible_text"  - every character you can actually see in the crop, verbatim.
  "confidence"    - your confidence from 0.0 to 1.0.
  "reason"        - at most 12 words.

Rules:
- Transcribe only what is printed. Never infer, complete, or correct a value.
- If the box is blank or unreadable, return "" for value. Do not guess.
- Do not add characters that are not visible in the crop."""

# What each field is, in the model's terms. Keeps the prompt field-scoped so a
# model cannot answer with a neighbouring box's content.
EXPECTATIONS = {
    "patient_name": "a person's name, usually LAST, FIRST MI",
    "insured_name": "a person's name, usually LAST, FIRST MI",
    "billing_provider_name": "an organisation or practice name",
    "provider_name": "an organisation or practice name",
    "patient_dob": "a date of birth, MM DD YYYY",
    "insured_id": "an insurance member/policy identifier",
    "billing_provider_npi": "a 10-digit NPI number",
    "provider_npi": "a 10-digit NPI number",
    "attending_npi": "a 10-digit NPI number",
    "rendering_npi": "a 10-digit NPI number",
    "referring_provider_npi": "a 10-digit NPI number",
    "federal_tax_id": "a federal tax ID (EIN or SSN format)",
    "federal_tax_no": "a federal tax ID (EIN or SSN format)",
    "total_charge": "a dollar amount",
    "total_charges": "a dollar amount",
    "charges": "a dollar amount",
    "cpt_code": "a 5-character CPT/HCPCS procedure code",
    "hcpcs": "a 5-character CPT/HCPCS procedure code",
    "rev_code": "a 3-4 digit revenue code",
    "patient_zip": "a US ZIP code",
}


class VisionErrorType(str, Enum):
    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


def expectation_for(field_name: str) -> str:
    if field_name in EXPECTATIONS:
        return EXPECTATIONS[field_name]
    base = re.sub(r"^line\d+_", "", field_name)
    if base in EXPECTATIONS:
        return EXPECTATIONS[base]
    if "date" in base:
        return "a date, MM DD YYYY"
    if "code" in base or base.startswith("diagnosis"):
        return "an ICD-10 diagnosis code"
    return "a short printed value"


@dataclass
class VisionResponse:
    """One structured answer from one model about one crop."""
    value: Optional[str]
    visible_text: str
    confidence: float
    reason: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    raw_sha256: str = ""
    parse_error: str = ""
    error_type: VisionErrorType | None = None
    cached: bool = False
    rejects: list = field(default_factory=list)   # filled by the grounding check

    @property
    def ok(self) -> bool:
        return not self.parse_error


def price_call(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost from configs/prices.yaml. Single source of truth for model spend."""
    p = _PRICES["vision_models"].get(model)
    if p is None:
        raise KeyError(f"no price row for model {model!r} — add it to configs/prices.yaml")
    return input_tokens / 1e6 * p["input"] + output_tokens / 1e6 * p["output"]


def parse_response(text: str, model: str) -> VisionResponse:
    """Strict JSON parse. A model that answers with prose fails HERE, and a
    parse failure is a rejection, not a silent fallback to raw text."""
    blob = text.strip()
    raw_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        return VisionResponse(None, "", 0.0, model=model, raw_sha256=raw_sha256,
                              parse_error=f"invalid JSON: {e}",
                              error_type=VisionErrorType.INVALID_RESPONSE)
    required = {"value", "visible_text", "confidence", "reason"}
    if not isinstance(d, dict) or set(d) != required:
        return VisionResponse(
            None, "", 0.0, model=model, raw_sha256=raw_sha256,
            parse_error=f"response keys must be exactly {sorted(required)}",
            error_type=VisionErrorType.INVALID_RESPONSE,
        )
    try:
        conf = float(d.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return VisionResponse(
        value=normalize_text(d.get("value") or "") or None,
        visible_text=normalize_text(d.get("visible_text") or ""),
        confidence=max(0.0, min(1.0, conf)),
        reason=str(d.get("reason", ""))[:120],
        model=model, raw_sha256=raw_sha256,
    )


class VisionEngine(ABC):
    name: str = "base"

    @abstractmethod
    def read_field(self, crop, field_name: str) -> VisionResponse:
        """One crop in, one structured candidate out. Must never raise on a
        bad model answer — encode the failure in VisionResponse.parse_error."""


_REGISTRY: dict = {}


def get_vision_engine(name: str) -> VisionEngine:
    if name not in _REGISTRY:
        if name == "offline-oracle":
            from engine.vision.offline_engine import OfflineOracleEngine
            _REGISTRY[name] = OfflineOracleEngine()
        elif name in ("gpt-5-nano", "gpt-5-mini"):
            from engine.vision.openai_engine import OpenAIVisionEngine
            _REGISTRY[name] = OpenAIVisionEngine(name)
        elif name.startswith("gemini-"):
            from engine.vision.gemini_engine import GeminiVisionEngine
            _REGISTRY[name] = GeminiVisionEngine(name)
        else:
            raise ValueError(f"unknown vision engine: {name}")
    return _REGISTRY[name]
