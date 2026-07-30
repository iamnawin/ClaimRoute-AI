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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import yaml

from engine.ocr.base import normalize_text

_PRICES = yaml.safe_load(open("configs/prices.yaml"))

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
    raw: str = ""
    parse_error: str = ""
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
    """Strict-ish JSON parse. A model that answers with prose fails HERE, and a
    parse failure is a rejection, not a silent fallback to raw text."""
    blob = text.strip()
    m = re.search(r"\{.*\}", blob, re.DOTALL)
    if not m:
        return VisionResponse(None, "", 0.0, model=model, raw=text,
                              parse_error="no JSON object in response")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return VisionResponse(None, "", 0.0, model=model, raw=text,
                              parse_error=f"invalid JSON: {e}")
    if not isinstance(d, dict) or "value" not in d:
        return VisionResponse(None, "", 0.0, model=model, raw=text,
                              parse_error="missing required key 'value'")
    try:
        conf = float(d.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return VisionResponse(
        value=normalize_text(d.get("value") or "") or None,
        visible_text=normalize_text(d.get("visible_text") or ""),
        confidence=max(0.0, min(1.0, conf)),
        reason=str(d.get("reason", ""))[:120],
        model=model, raw=text,
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
