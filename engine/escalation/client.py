"""The multimodal escalation client — one bounded, governed transaction.

    disabled? -> crop-only gate -> call (bounded retries) -> hash raw
              -> strict parse -> grounding -> usage/cost -> safe audit record

This is NOT an agent framework and NOT a pipeline stage. It generates ONE
candidate for ONE field crop and hands back a MultimodalResult. It performs no
healthcare validation, keeps no state between calls, and is not wired into
engine/extract.py — integration is a separate, reviewable task.

Two ordering decisions are load-bearing:

1. The enabled check and the crop-only gate run BEFORE anything else. A disabled
   adapter must be unable to open a socket, and an image that cannot be proven to
   be a field crop must never reach a provider.
2. The raw body is hashed and discarded in the same breath. Provider responses
   can contain transcribed claim values, so persisting them would move PHI into
   logs; the hash preserves reproducibility without the payload.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import yaml

from engine.cropper import MARGIN_PX, crop_field
from engine.escalation.contract import (CostBreakdown, CropImage, MultimodalRequest,
                                        MultimodalResult, UsageMetadata,
                                        ground_answer, parse_answer)
from engine.escalation.errors import ErrorCategory, MultimodalError
from engine.escalation.providers import MultimodalProvider, build_provider
from engine.vision.base import expectation_for, price_call
import hashlib

CONFIG_PATH = Path("configs/multimodal_providers.yaml")

# Env override so an operator can enable the adapter for one process without
# editing tracked config. Absent or unset means "use the file", and the file says
# disabled — the default stays off through every path.
ENABLE_ENV = "CLAIMROUTE_MULTIMODAL_ENABLED"

_TRUE = {"1", "true", "yes", "on"}


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        raise MultimodalError(ErrorCategory.CONFIGURATION_ERROR,
                              f"missing config {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # Attach the operating-mode -> model table so the loaded config is
    # self-contained. ModelRouter reads it from here rather than from disk,
    # so a hand-built config keeps whatever model its author intended.
    from engine.escalation.model_router import load_models_config
    cfg.setdefault("operating_mode_models", load_models_config())
    return cfg


def build_request(crop, field_name: str, *, source_page_px=None, region_px=None,
                  doc_id: str = "", page_id: str = "",
                  synthetic: bool = True) -> MultimodalRequest:
    """Wrap an existing crop image. Prefer request_from_page() when you have the
    page — it routes through the structural PHI boundary."""
    return MultimodalRequest(
        field_name=field_name,
        crop=CropImage.from_pil(crop, source_page_px=source_page_px,
                                region_px=region_px),
        expectation=expectation_for(field_name),
        doc_id=doc_id, page_id=page_id, synthetic=synthetic)


def request_from_page(img, bbox, field_name: str, *, doc_id: str = "",
                      page_id: str = "", synthetic: bool = True) -> MultimodalRequest:
    """Build a request from a page + bbox through engine/cropper.py.

    This is the preferred constructor: the crop is produced by the same bounded,
    policy-checked cropper the rest of the pipeline uses, so the crops-only rule
    is enforced structurally rather than restated here. Raises CropPolicyError if
    the requested region is not a legitimate field crop.
    """
    crop = crop_field(img, bbox)
    # The region the cropper actually takes, using its own margin constant so the
    # two cannot drift. Recorded separately because crop_field upscales small
    # boxes, and an upscaled box must not read as a larger share of the page.
    x0, y0, x1, y1 = (float(v) for v in bbox)
    rx0, ry0 = max(0, int(x0) - MARGIN_PX), max(0, int(y0) - MARGIN_PX)
    rx1, ry1 = min(img.width, int(x1) + MARGIN_PX), min(img.height, int(y1) + MARGIN_PX)
    return build_request(crop, field_name, source_page_px=(img.width, img.height),
                         region_px=(rx1 - rx0, ry1 - ry0),
                         doc_id=doc_id, page_id=page_id, synthetic=synthetic)


class MultimodalClient:
    """Provider-independent escalation client. Disabled unless explicitly enabled."""

    def __init__(self, *, config: Optional[dict] = None,
                 provider: Optional[MultimodalProvider] = None,
                 enabled: Optional[bool] = None,
                 sleep=time.sleep, ledger=None, env: Optional[dict] = None):
        self.config = config if config is not None else load_config()
        self._provider = provider
        self._sleep = sleep
        self._ledger = ledger
        self._env = env if env is not None else None
        self.enabled = self._resolve_enabled(enabled)

        self.request_policy = self.config.get("request_policy") or {}
        self.transport = self.config.get("transport") or {}
        self.response_policy = self.config.get("response_policy") or {}

    # ------------------------------------------------------------- config

    def _getenv(self, name: str) -> Optional[str]:
        if self._env is not None:
            return self._env.get(name)
        import os
        return os.environ.get(name)

    def _resolve_enabled(self, override: Optional[bool]) -> bool:
        if override is not None:
            return bool(override)
        raw = self._getenv(ENABLE_ENV)
        if raw is not None and str(raw).strip():
            return str(raw).strip().lower() in _TRUE
        return bool(self.config.get("enabled", False))

    @property
    def provider(self) -> MultimodalProvider:
        if self._provider is None:
            name = self.config.get("active_provider")
            specs = self.config.get("providers") or {}
            if name not in specs:
                raise MultimodalError(
                    ErrorCategory.CONFIGURATION_ERROR,
                    f"active_provider {name!r} not present in providers")
            self._provider = build_provider(name, specs[name])
        return self._provider

    # -------------------------------------------------------------- gates

    def check_request(self, request: MultimodalRequest) -> Optional[MultimodalError]:
        """Pre-call policy. Returns the blocking error, or None to proceed."""
        policy = self.request_policy
        crop = request.crop

        if policy.get("synthetic_data_only", True) and not request.synthetic:
            return MultimodalError(
                ErrorCategory.CONFIGURATION_ERROR,
                "request is not marked synthetic and synthetic_data_only is set")

        max_bytes = int(policy.get("max_crop_bytes", 2_000_000))
        if len(crop.png_bytes) > max_bytes:
            return MultimodalError(
                ErrorCategory.UNSUPPORTED_IMAGE,
                f"crop is {len(crop.png_bytes)} bytes (limit {max_bytes})")

        if not policy.get("crop_only", True):
            return None

        fraction = crop.page_fraction
        if fraction is None:
            if policy.get("require_page_provenance", True):
                # No source page recorded, so this image cannot be shown to be a
                # crop. Unverifiable provenance is refused, not assumed benign.
                return MultimodalError(
                    ErrorCategory.UNSUPPORTED_IMAGE,
                    "no source page size recorded; cannot prove the image is a field crop")
            return None

        limit = float(policy.get("max_page_fraction", 0.25))
        if fraction > limit:
            return MultimodalError(
                ErrorCategory.UNSUPPORTED_IMAGE,
                f"image covers {fraction:.1%} of the page (limit {limit:.0%}); "
                "full pages are never sent")
        return None

    # --------------------------------------------------------------- call

    def read_field(self, request: MultimodalRequest) -> MultimodalResult:
        """One governed escalation attempt. Never raises on provider failure —
        every outcome is encoded in the result."""
        started = time.perf_counter()
        result = MultimodalResult(request_id=request.request_id,
                                  field_name=request.field_name)

        if not self.enabled:
            # Disabled by default: no provider is constructed, so a missing key or
            # a typo in an endpoint cannot cause a call either.
            return self._finish(result, request, started, MultimodalError(
                ErrorCategory.CONFIGURATION_ERROR,
                f"multimodal adapter is disabled (set {ENABLE_ENV}=1 or "
                "enabled: true to allow calls)"))

        blocked = self.check_request(request)
        if blocked is not None:
            return self._finish(result, request, started, blocked)

        try:
            provider = self.provider
        except MultimodalError as e:
            return self._finish(result, request, started, e)

        result.provider = provider.name
        result.model = provider.model

        call, error = self._call_with_retries(provider, request, result)
        if call is None:
            return self._finish(result, request, started, error)

        # Hash and drop. The body is never persisted or logged.
        result.raw_sha256 = hashlib.sha256(call.raw_text.encode("utf-8",
                                                                "replace")).hexdigest()
        result.usage = call.usage or UsageMetadata()
        result.cost = self._cost(provider, request, result.usage, call)
        if call.actual_model and call.actual_model != result.model:
            # An aggregator served something other than what was asked for.
            # Recorded, never silently accepted as equivalent.
            result.model_substituted = True
            result.actual_model = call.actual_model

        payload, rejects = parse_answer(call.raw_text)
        if payload is None:
            result.rejects = rejects
            return self._finish(result, request, started, None)

        answer, rejects = ground_answer(
            payload, request.field_name,
            max_value_chars=int(self.response_policy.get("max_value_chars", 120)))
        result.answer = answer
        result.rejects = rejects
        return self._finish(result, request, started, None)

    def _call_with_retries(self, provider, request, result):
        """Bounded attempts on transient categories only."""
        max_attempts = max(1, int(self.transport.get("max_attempts", 3)))
        timeout_s = float(self.transport.get("timeout_seconds", 30))
        delay = float(self.transport.get("backoff_initial_seconds", 0.5))
        multiplier = float(self.transport.get("backoff_multiplier", 2.0))
        max_delay = float(self.transport.get("backoff_max_seconds", 8.0))
        retry_invalid = bool(self.transport.get("retry_on_invalid_response", False))

        last: Optional[MultimodalError] = None
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            result.called_provider = True
            try:
                call = provider.invoke(request, timeout_s=timeout_s)
            except MultimodalError as e:
                last = e
                result.provider_latency_ms.append(0.0)
                retryable = e.retryable or (
                    retry_invalid and e.category == ErrorCategory.INVALID_RESPONSE)
                if not retryable or attempt >= max_attempts:
                    return None, e
                # Honour Retry-After when the provider supplied one; it knows
                # better than our backoff curve does.
                wait = e.retry_after_s if e.retry_after_s is not None else delay
                self._sleep(min(wait, max_delay))
                delay = min(delay * multiplier, max_delay)
                continue
            except Exception as e:                # a provider bug is still ours to categorise
                last = MultimodalError(ErrorCategory.UNKNOWN_PROVIDER_ERROR,
                                       f"{type(e).__name__}")
                return None, last
            result.provider_latency_ms.append(round(call.latency_ms, 2))
            return call, None
        return None, last

    # --------------------------------------------------------------- cost

    def _cost(self, provider, request, usage: UsageMetadata,
              call=None) -> CostBreakdown:
        """Reported, measured and estimated spend, kept apart.

        Precedence is deliberate. A cost the PROVIDER reports is an actual
        charge and wins outright; when it exists we still compute the local
        list-price figure alongside it (when a verified price row exists) so the
        two can be compared rather than one quietly replacing the other.

        Measured means provider-reported tokens priced from configs/prices.yaml.
        It is a list-price computation over reported usage, NOT a billed invoice
        amount. When usage is absent we fall back to a text-only estimate that
        excludes image tokens and is labelled a lower bound — because inventing an
        image-token count to make the number look complete would be a cost lie.
        """
        price_row = provider.price_row or provider.model
        reported = getattr(call, "reported_cost_usd", None) if call else None

        def _local() -> Optional[float]:
            """List price over reported usage, or None when either is missing."""
            if not usage.billable_known:
                return None
            try:
                return price_call(price_row, usage.input_tokens, usage.output_tokens)
            except KeyError:
                return None

        if reported is not None:
            return CostBreakdown(basis="provider_reported", price_row=price_row,
                                 reported_usd=reported, measured_usd=_local())

        try:
            if usage.billable_known:
                return CostBreakdown(
                    basis="measured_usage", price_row=price_row,
                    measured_usd=price_call(price_row, usage.input_tokens,
                                            usage.output_tokens))
            est_in = provider.estimate_text_tokens(request)
            return CostBreakdown(
                basis="estimated_usage", price_row=price_row,
                estimated_usd=price_call(price_row, est_in, 0),
                estimate_excludes_image_tokens=True)
        except KeyError:
            # No price row: report unknown rather than guessing a rate.
            return CostBreakdown(basis="unknown", price_row=price_row)

    # -------------------------------------------------------------- audit

    def _finish(self, result: MultimodalResult, request: MultimodalRequest,
                started: float, error: Optional[MultimodalError]) -> MultimodalResult:
        if error is not None:
            result.error = error.category.value
            result.error_detail = error.detail
        result.latency_ms = round((time.perf_counter() - started) * 1000, 2)

        result.audit = {
            **request.safe_dict(),
            "provider": result.provider,
            "model": result.model,
            "actual_model": result.actual_model,
            "model_substituted": result.model_substituted,
            "enabled": self.enabled,
            "called_provider": result.called_provider,
            "attempts": result.attempts,
            "latency_ms": result.latency_ms,
            "provider_latency_ms": result.provider_latency_ms,
            "error": result.error,
            "error_detail": result.error_detail,
            "rejects": list(result.rejects),
            "raw_sha256": result.raw_sha256,
            "usage": result.usage.to_dict(),
            "cost": result.cost.to_dict(),
            "answer": result.answer.safe_dict() if result.answer else None,
            "ok": result.ok,
        }

        if self._ledger is not None:
            # billed_usd prefers the provider's own charge and never falls back
            # to the image-excluding estimate, which is only a lower bound.
            measured = result.cost.billed_usd or 0.0
            self._ledger.log(
                doc_id=request.doc_id or "unknown", page_id=request.page_id,
                field_name=request.field_name,
                operation=(f"multimodal_{result.provider or 'none'}"
                           if result.called_provider else "multimodal_blocked"),
                cost_usd=measured, latency_ms=result.latency_ms,
                meta={k: v for k, v in result.audit.items() if k != "field_name"})
        return result
