"""Provider-independent request/result contract for Tier-2 escalation.

Every provider speaks these types or it does not play. Transport lives in an
adapter; parsing, grounding, usage normalisation and costing live HERE, once, so
a second provider cannot quietly disagree with the first about what a valid
answer is.

THE ANSWER IS A CANDIDATE, NEVER TRUTH. This module decides only whether a
response is well-formed and evidence-backed enough to compete. Healthcare
validation (NPI checksum, ICD/CPT dictionaries, cross-field arithmetic) is
deliberately NOT performed here — that is engine/validators/, applied by the
caller on governor re-entry.

Expected provider response, exactly these three keys:

    {"value": "visible field value or null", "visible": true, "confidence": 0.97}
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Optional

from engine.cropper import crop_png_bytes
from engine.ocr.base import normalize_text

# Field shape patterns are owned by engine/grounding.py. They are imported rather
# than restated so a type rule cannot drift between the two escalation paths;
# that module is out of scope for edits in this task, hence the private import.
from engine.grounding import _TYPE_PATTERNS, _type_key

REQUIRED_KEYS = frozenset({"value", "visible", "confidence"})
UNKNOWN = "unknown"

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


# --------------------------------------------------------------- crop input

@dataclass(frozen=True)
class CropImage:
    """PNG bytes of ONE field crop, plus the provenance needed to prove it is a
    crop and not a page.

    `png_bytes` is payload: it is never logged, never placed in an audit record,
    and never included in a repr. Everything downstream identifies this image by
    `sha256` alone.
    """
    png_bytes: bytes
    width: int
    height: int
    sha256: str
    source_page_px: Optional[tuple] = None      # (page_w, page_h) when known
    # Size of the region actually taken FROM the page, before any upscaling.
    # engine/cropper.py enlarges small boxes so a model can see them, which would
    # otherwise make a tiny field look like a large share of the page.
    region_px: Optional[tuple] = None

    @classmethod
    def from_pil(cls, crop, *, source_page_px: Optional[tuple] = None,
                 region_px: Optional[tuple] = None) -> "CropImage":
        data = crop_png_bytes(crop)             # reuses the PHI-boundary encoder
        return cls(png_bytes=data, width=crop.width, height=crop.height,
                   sha256=hashlib.sha256(data).hexdigest(),
                   source_page_px=tuple(source_page_px) if source_page_px else None,
                   region_px=tuple(region_px) if region_px else None)

    def __repr__(self) -> str:                  # never leak pixels into a traceback
        return (f"CropImage(sha256={self.sha256[:16]}, {self.width}x{self.height}, "
                f"bytes={len(self.png_bytes)})")

    @property
    def b64(self) -> str:
        return base64.b64encode(self.png_bytes).decode("ascii")

    @property
    def page_fraction(self) -> Optional[float]:
        """Area share of the source page, or None when provenance is unrecorded.

        Measured on the region taken from the page, not on the encoded image:
        upscaling a small box must not be mistaken for capturing more of the page.
        """
        if not self.source_page_px:
            return None
        pw, ph = self.source_page_px
        if pw <= 0 or ph <= 0:
            return None
        rw, rh = self.region_px or (self.width, self.height)
        return (rw * rh) / float(pw * ph)

    def safe_dict(self) -> dict:
        return {"crop_sha256": self.sha256, "crop_px": [self.width, self.height],
                "crop_bytes": len(self.png_bytes),
                "region_px": list(self.region_px) if self.region_px else None,
                "source_page_px": list(self.source_page_px) if self.source_page_px
                else None,
                "page_fraction": (round(self.page_fraction, 6)
                                  if self.page_fraction is not None else None)}


@dataclass(frozen=True)
class MultimodalRequest:
    """One field, one crop, one question. Provider-independent by construction."""
    field_name: str
    crop: CropImage
    expectation: str = ""
    doc_id: str = ""
    page_id: str = ""
    synthetic: bool = True

    @property
    def request_id(self) -> str:
        """Deterministic: identical crop + field = identical id, so an audit trail
        can be correlated across runs without storing anything identifying."""
        return hashlib.sha256(
            f"{self.field_name}|{self.crop.sha256}".encode()).hexdigest()[:16]

    def safe_dict(self) -> dict:
        return {"request_id": self.request_id, "field_name": self.field_name,
                "doc_id": self.doc_id, "page_id": self.page_id,
                "synthetic_data": self.synthetic, **self.crop.safe_dict()}


# --------------------------------------------------------------- usage & cost

@dataclass
class UsageMetadata:
    """Normalised token counts. None means UNKNOWN and stays unknown.

    Providers report wildly different subsets. Defaulting a missing count to 0
    would silently understate spend and fabricate precision, so absent values are
    preserved as unknown all the way into the audit record. In particular:
    IMAGE TOKENS ARE NEVER INVENTED — no provider in scope reports them
    separately, so `image_tokens` stays None unless one actually does.
    """
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    image_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None

    @property
    def billable_known(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None

    def to_dict(self) -> dict:
        """Serialise WITHOUT changing the type of what is being serialised.

        Unknown counts stay None, which is `null` in JSON — the same "unknown"
        the dataclass above declares and the audit record has always meant.

        This used to substitute the string "unknown" for None. The intent was
        right and is unchanged: an absent count must never become 0, because a
        zero reads as a measurement and an unmetered call that appears to cost
        nothing is how a budget check passes something it should have stopped.
        The ENCODING was wrong: it put a string in a field typed Optional[int],
        so every reader that trusted the schema and did arithmetic on it raised
        ValueError. The Cost dashboard is the one that found it.

        None carries "unknown" without lying about the type. Consumers keep
        using `is None` to test availability, exactly as they do on the
        dataclass fields themselves.
        """
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "image_tokens": self.image_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass
class CostBreakdown:
    """Measured, reported and estimated spend, never blended into one number.

    `reported_usd` = the amount the PROVIDER says it charged, when the provider
    returns one (OpenRouter does; OpenAI does not). This is the only figure that
    is an actual billed amount, so it outranks every local calculation and is
    kept in its own field rather than overwriting `measured_usd`.

    `measured_usd` = provider-reported tokens priced from configs/prices.yaml. It
    is a LIST-PRICE COMPUTATION OVER REPORTED USAGE, not a billed invoice amount;
    the distinction is kept in `basis` so no report can quietly promote it. It is
    populated alongside `reported_usd` when a verified price row exists, so the
    two can be compared — a large gap means our price row has drifted.

    `estimated_usd` is used only when the provider reported no usage. It covers
    text tokens alone and excludes image tokens (which are unknown), so it is an
    explicit LOWER BOUND — flagged as such rather than padded with a guess.
    """
    # provider_reported | measured_usage | estimated_usage | unknown
    basis: str = "unknown"
    measured_usd: Optional[float] = None
    estimated_usd: Optional[float] = None
    reported_usd: Optional[float] = None
    price_row: str = ""
    estimate_excludes_image_tokens: bool = False

    @property
    def billed_usd(self) -> Optional[float]:
        """The best available figure for money actually spent, or None.

        Prefers the provider's own number. Never falls back to `estimated_usd`:
        an estimate that excludes image tokens is a lower bound, and treating a
        lower bound as spend would let a budget be overrun silently.
        """
        if self.reported_usd is not None:
            return self.reported_usd
        return self.measured_usd

    def to_dict(self) -> dict:
        return {"basis": self.basis, "price_row": self.price_row,
                "measured_usd": self.measured_usd,
                "estimated_usd": self.estimated_usd,
                "reported_usd": self.reported_usd,
                "billed_usd": self.billed_usd,
                "estimate_excludes_image_tokens": self.estimate_excludes_image_tokens,
                "estimate_is_lower_bound": self.estimate_excludes_image_tokens}


# --------------------------------------------------------------- answer

@dataclass
class ParsedAnswer:
    """A structurally valid, grounded candidate. Not yet healthcare-validated."""
    value: Optional[str]
    visible: bool
    confidence: float

    def safe_dict(self) -> dict:
        """Audit-safe: reports THAT a value exists and how long it is, never what
        it says. Extracted values are PHI-adjacent and never leave the process."""
        return {"has_value": self.value is not None,
                "value_chars": len(self.value or ""),
                "visible": self.visible,
                "confidence": self.confidence}


@dataclass
class MultimodalResult:
    """The single return type of the adapter. Success and every failure mode."""
    request_id: str
    provider: str = ""
    model: str = ""                              # the model REQUESTED
    actual_model: str = ""                       # what the provider says it served
    model_substituted: bool = False
    field_name: str = ""
    answer: Optional[ParsedAnswer] = None
    rejects: list = field(default_factory=list)
    error: Optional[str] = None                  # ErrorCategory value
    error_detail: str = ""
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    cost: CostBreakdown = field(default_factory=CostBreakdown)
    latency_ms: float = 0.0                      # wall time across all attempts
    provider_latency_ms: list = field(default_factory=list)
    attempts: int = 0
    called_provider: bool = False
    raw_sha256: str = ""                         # hash of the raw body; body discarded
    audit: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """A usable candidate: no transport error, no rejection, an answer."""
        return self.error is None and not self.rejects and self.answer is not None


# --------------------------------------------------------------- parsing

def _strip_fence(text: str) -> str:
    m = _FENCE.match(text.strip())
    return m.group(1) if m else text.strip()


def parse_answer(raw: str) -> tuple[Optional[dict], list]:
    """Structural parse only. -> (payload, rejects).

    Strict on purpose. The body must BE a JSON object; a JSON object buried in
    commentary is rejected rather than fished out with a regex, because a model
    that explains itself has not followed the contract and its next answer cannot
    be trusted to be parseable either.
    """
    text = _strip_fence(raw or "")
    if not text:
        return None, ["empty response body"]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        head = "prose or non-JSON body" if not text.lstrip().startswith(("{", "[")) \
            else "malformed JSON body"
        return None, [f"invalid JSON: {head}"]

    if not isinstance(payload, dict):
        return None, [f"expected a JSON object, got {type(payload).__name__}"]

    keys = set(payload)
    missing = REQUIRED_KEYS - keys
    if missing:
        return None, [f"missing required keys: {sorted(missing)}"]

    extra = keys - REQUIRED_KEYS
    if extra:
        # More than the asked-for field came back. One crop, one field, one answer:
        # anything else means the model read neighbouring boxes.
        return None, [f"unexpected keys (multiple unrelated fields): {sorted(extra)}"]

    return payload, []


def ground_answer(payload: dict, field_name: str,
                  *, max_value_chars: int = 120) -> tuple[Optional[ParsedAnswer], list]:
    """Semantic checks against the crop's own evidence. -> (answer, rejects).

    Mechanical and predictable, in the spirit of engine/grounding.py:
      1. typed      - primitives match the schema's declared types
      2. bounded    - confidence is a real probability
      3. consistent - a model that says it saw nothing cannot also report a value
      4. no-invention - one form box cannot hold a paragraph
      5. shaped     - the value looks like the field it claims to be
    """
    rejects: list = []

    raw_value = payload.get("value")
    visible = payload.get("visible")
    confidence = payload.get("confidence")

    # 1. Typed. bool is a subclass of int in Python, so `visible` and `confidence`
    #    are checked explicitly rather than by duck-typing.
    if raw_value is not None and not isinstance(raw_value, str):
        rejects.append(f"'value' must be a string or null, got {type(raw_value).__name__}")
    if not isinstance(visible, bool):
        rejects.append(f"'visible' must be a boolean, got {type(visible).__name__}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        rejects.append(
            f"'confidence' must be a number, got {type(confidence).__name__}")
    if rejects:
        return None, rejects

    # 2. Bounded.
    conf = float(confidence)
    if not 0.0 <= conf <= 1.0:
        rejects.append(f"confidence {conf} outside 0-1")
        return None, rejects

    # Normalise at the schema boundary (repo-wide rule: full-width punctuation
    # from a multilingual model head must never reach a validator).
    value = normalize_text(raw_value) if isinstance(raw_value, str) else None
    if value == "":
        value = None                    # an empty string is an absent value

    # 3. Consistent.
    if not visible and value is not None:
        rejects.append("visible=false with a non-null value")
        return None, rejects

    if value is None:
        # A legitimately blank box. Whether blank is ACCEPTABLE for this field is
        # a field-policy question the governor answers, not this adapter.
        return ParsedAnswer(None, bool(visible), conf), rejects

    # 4. No-invention.
    if len(value) > max_value_chars:
        rejects.append(
            f"value too long ({len(value)} chars) for one field box")
        return None, rejects

    # 5. Shaped.
    tk = _type_key(field_name)
    if tk and not _TYPE_PATTERNS[tk].match(value.replace(" ", "")):
        # Deliberately reports the TYPE, not the value: rejection reasons are
        # written to audit records and must stay free of extracted content.
        rejects.append(f"type mismatch: value is not a valid {tk}")
        return None, rejects

    return ParsedAnswer(value, True, conf), rejects
