"""Batched local retry OCR for the localhost CMS-1500 workspace."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import time

import numpy as np
from PIL import Image

from engine.fusion import fuse
from engine.governor import apply
from engine.layout.official_cms1500_registration import load_official_template
from engine.ocr import get_engine
from engine.schemas import Attempt, FieldState, Verdict
from eval.official.extraction import (
    official_retry_candidate,
    record_stage,
    validate_official_field,
)
from eval.official.normalization import normalize_value
from eval.official.ocr_retry import (
    RetryCandidate,
    candidate_values,
    load_retry_profiles,
    preprocess_crop,
    select_best_candidate,
)


_ATLAS_PADDING = 24
_ATLAS_MAX_WIDTH = 1800
_TARGETED_FALLBACK_FAMILIES = frozenset({"date", "quantity"})


@dataclass(frozen=True)
class RetrySpec:
    field_name: str
    family: str
    crop: Image.Image
    prepared: Image.Image
    profile: dict
    blank_crop: bool
    preprocessing_ms: float


def _crop_key(image: Image.Image, profile: dict) -> str:
    material = (
        image.mode.encode(),
        str(image.size).encode(),
        json.dumps(profile, sort_keys=True).encode(),
        image.tobytes(),
    )
    digest = hashlib.sha256()
    for part in material:
        digest.update(part)
    return digest.hexdigest()


def _retry_specs(page, image: Image.Image) -> list[RetrySpec]:
    template = load_official_template()["fields"]
    profiles = load_retry_profiles()["field_families"]
    specs = []
    for name, field in page.fields.items():
        if field.state != FieldState.RETRY or not field.bbox:
            continue
        family = template[name]["field_type"]
        profile_group = profiles.get(family, profiles["text"])
        profile = profile_group["attempts"][0]
        region = list(field.bbox)
        if name == "billing_provider_npi" and page.fields.get("billing_provider_name"):
            # The NPI is a short line inside the wide billing-provider box. The
            # compact field crop loses its layout cue; one raw union crop keeps
            # that cue inside the existing atlas invocation.
            related = list(page.fields["billing_provider_name"].bbox)
            region = [
                max(0, min(region[0], related[0]) - 24),
                max(0, min(region[1], related[1]) - 24),
                min(image.width, max(region[2], related[2]) + 24),
                min(image.height, max(region[3], related[3]) + 24),
            ]
            profile = {
                **profile,
                "scale": 1,
                "threshold": "none",
                "contrast_normalization": False,
                "remove_lines": False,
            }
        crop = image.crop([round(value) for value in region])
        gray = np.asarray(crop.convert("L"))
        blank_crop = bool(gray.size == 0 or (gray < 220).mean() < .001)
        started = time.perf_counter()
        prepared = preprocess_crop(crop, profile)
        preprocessing_ms = (time.perf_counter() - started) * 1000
        specs.append(RetrySpec(
            name, family, crop, prepared, profile, blank_crop, preprocessing_ms
        ))
    return specs


def _pack_unique(specs: list[RetrySpec]) -> tuple[Image.Image | None, dict, dict]:
    unique = {}
    keys = {}
    for spec in specs:
        key = _crop_key(spec.prepared, spec.profile)
        keys[spec.field_name] = key
        unique.setdefault(key, spec.prepared)
    if not unique:
        return None, {}, keys

    width = max(
        min(_ATLAS_MAX_WIDTH, max(1024, max(image.width for image in unique.values()))),
        max(image.width for image in unique.values()) + 2 * _ATLAS_PADDING,
    )
    placements = {}
    x = y = _ATLAS_PADDING
    row_height = 0
    for key, crop in unique.items():
        if x + crop.width + _ATLAS_PADDING > width and x > _ATLAS_PADDING:
            x, y, row_height = _ATLAS_PADDING, y + row_height + _ATLAS_PADDING, 0
        placements[key] = (x, y, x + crop.width, y + crop.height)
        x += crop.width + _ATLAS_PADDING
        row_height = max(row_height, crop.height)
    atlas = Image.new("RGB", (width, y + row_height + _ATLAS_PADDING), "white")
    for key, crop in unique.items():
        atlas.paste(crop.convert("RGB"), placements[key][:2])
    return atlas, placements, keys


def _atlas_candidates(specs: list[RetrySpec], engine) -> tuple[dict, dict]:
    active = [spec for spec in specs if not spec.blank_crop]
    atlas, placements, keys = _pack_unique(active)
    if atlas is None:
        return {}, {
            "invocation_id": None,
            "engine": "paddle",
            "latency_ms": 0.0,
            "process_startups": 0,
            "unique_crops": 0,
            "deduplicated_crops": 0,
        }

    started_at = time.perf_counter()
    words = engine.extract(atlas)
    ended_at = time.perf_counter()
    latency_ms = (ended_at - started_at) * 1000
    by_name = {}
    for spec in active:
        x0, y0, x1, y1 = placements[keys[spec.field_name]]
        hits = [word for word in words
                if x0 <= word.center[0] <= x1 and y0 <= word.center[1] <= y1]
        by_name[spec.field_name] = candidate_values(
            spec.field_name,
            sorted(hits, key=lambda word: word.bbox[0]),
            source="crop_atlas_paddle",
            attempt_index=1,
            latency_ms=latency_ms,
        )
    return by_name, {
        "invocation_id": "prepared-crop-atlas",
        "engine": "paddle",
        "atlas_dimensions": list(atlas.size),
        "latency_ms": latency_ms,
        "process_startups": 0,
        "unique_crops": len(placements),
        "deduplicated_crops": len(active) - len(placements),
        "started_ms": 0.0,
        "ended_ms": latency_ms,
    }


def _rank(field_name: str, candidates: list[RetryCandidate], context: dict):
    return select_best_candidate(
        field_name,
        candidates,
        context,
        validator=lambda name, value, ctx: validate_official_field(
            "cms1500", name, value, ctx
        ),
    )


def _candidate_state(field, ranked, page_quality: float, preset: str) -> FieldState:
    if ranked is None:
        return FieldState.RETRY
    candidate = ranked.candidate
    trial = copy.deepcopy(field)
    trial.value = candidate.value
    trial.stamps = ranked.stamps
    trial.confidence = fuse(
        candidate.confidence,
        page_quality,
        candidate.n_spans,
        candidate.value,
        [stamp.validator for stamp in ranked.stamps],
    )
    trial.attempts.append(Attempt(
        "retry_ocr", candidate.source, candidate.value, trial.confidence
    ))
    return apply(trial, preset)[0]


def _needs_targeted_fallback(spec: RetrySpec, field, ranked,
                             page_quality: float, preset: str) -> bool:
    if spec.family not in _TARGETED_FALLBACK_FAMILIES:
        return False
    # Narrow service-line end-date and units cells were the two crop families
    # that lost valid candidates in the compact atlas during development profiling.
    if spec.field_name.endswith(("_date_to", "_units")):
        return True
    return _candidate_state(field, ranked, page_quality, preset) not in {
        FieldState.ACCEPT, FieldState.ACCEPT_WITH_FLAG,
    }


def retry_cms1500_page(page, image: Image.Image, preset: str = "balanced",
                       stage_latency: dict[str, float] | None = None,
                       *, engine=None) -> list[dict]:
    """Retry all pending fields with one compact atlas and bounded typed fallbacks."""
    specs = _retry_specs(page, image)
    if not specs:
        return []
    engine = engine or get_engine("paddle")
    values = {name: field.value for name, field in page.fields.items()}
    retry_started = time.perf_counter()
    candidates, atlas_trace = _atlas_candidates(specs, engine)
    retry_ocr_ms = atlas_trace["latency_ms"] + sum(
        spec.preprocessing_ms for spec in specs
    )
    fallback_traces = {}

    for spec in specs:
        ranked = _rank(spec.field_name, candidates.get(spec.field_name, []), values)
        if (not spec.blank_crop and _needs_targeted_fallback(
                spec, page.fields[spec.field_name], ranked, page.quality_score, preset)):
            started = time.perf_counter()
            fallback = official_retry_candidate(
                image,
                spec.field_name,
                shared_words=[],
                region=list(page.fields[spec.field_name].bbox),
                form="cms1500",
            )
            duration_ms = (time.perf_counter() - started) * 1000
            retry_ocr_ms += duration_ms
            fallback_traces[spec.field_name] = {
                "invocation_id": f"targeted-{spec.field_name}",
                "engine": "paddle",
                "profile": spec.profile,
                "latency_ms": duration_ms,
                "process_startups": 0,
                "started_ms": (started - retry_started) * 1000,
                "ended_ms": (time.perf_counter() - retry_started) * 1000,
            }
            if fallback and fallback.get("value") is not None:
                candidates.setdefault(spec.field_name, []).append(RetryCandidate(
                    fallback["value"],
                    fallback["confidence"],
                    fallback["n_spans"],
                    fallback.get("source", "crop_paddle"),
                    2,
                    fallback["latency_ms"],
                ))
    if stage_latency is not None:
        stage_latency["retry_ocr"] += retry_ocr_ms

    receipts = []
    for spec in specs:
        name = spec.field_name
        field = page.fields[name]
        primary_value = field.value
        primary_validator_clean = not any(
            stamp.verdict == Verdict.FAIL for stamp in field.stamps
        )
        normalization_started = time.perf_counter()
        ranked = _rank(name, candidates.get(name, []), values)
        first_normalization_ms = (time.perf_counter() - normalization_started) * 1000
        record_stage(stage_latency, "normalization", normalization_started)
        value = ranked.candidate.value if ranked else None
        raw_confidence = ranked.candidate.confidence if ranked else 0.0
        n_spans = ranked.candidate.n_spans if ranked else 0
        validation_started = time.perf_counter()
        stamps = validate_official_field(
            "cms1500", name, value, {**values, name: value}
        )
        validation_ms = (time.perf_counter() - validation_started) * 1000
        record_stage(stage_latency, "validation", validation_started)
        confidence = fuse(
            raw_confidence,
            page.quality_score,
            n_spans,
            value or "",
            [stamp.validator for stamp in stamps],
        )
        allocated_atlas_ms = atlas_trace["latency_ms"] / max(1, len(specs))
        field.attempts.append(Attempt(
            "retry_ocr",
            ranked.candidate.source if ranked else "none",
            value,
            confidence,
            latency_ms=allocated_atlas_ms + fallback_traces.get(name, {}).get(
                "latency_ms", 0.0
            ),
        ))
        primary = RetryCandidate(
            field.value or "", field.confidence, 1 if field.value else 0, "primary", -1
        )
        retry = RetryCandidate(
            value or "",
            raw_confidence,
            n_spans,
            ranked.candidate.source if ranked else "retry",
            0,
        )
        normalization_started = time.perf_counter()
        selected = _rank(name, [primary, retry], values)
        second_normalization_ms = (time.perf_counter() - normalization_started) * 1000
        record_stage(stage_latency, "normalization", normalization_started)
        retry_selected = bool(selected and selected.candidate.source != "primary")
        if retry_selected:
            field.value, field.confidence, field.stamps = value, confidence, stamps
            values[name] = value
        governor_started = time.perf_counter()
        state, reason = apply(field, preset)
        record_stage(stage_latency, "governor", governor_started)
        page.decisions[name].append((state.value, reason))
        invocations = [] if spec.blank_crop else [{
            **atlas_trace,
            "profile": spec.profile,
            "crop_dimensions": list(spec.crop.size),
            "blank_crop": False,
            "preprocessing_ms": round(spec.preprocessing_ms, 3),
        }]
        if name in fallback_traces:
            invocations.append({
                **fallback_traces[name],
                "crop_dimensions": list(spec.crop.size),
                "blank_crop": False,
                "preprocessing_ms": 0.0,
            })
        selected_source = ranked.candidate.source if ranked and retry_selected else None
        for invocation in invocations:
            invocation["candidate_outcome"] = (
                "SELECTED"
                if (invocation["invocation_id"] == "prepared-crop-atlas"
                    and selected_source == "crop_atlas_paddle")
                or (invocation["invocation_id"].startswith("targeted-")
                    and selected_source not in {None, "crop_atlas_paddle"})
                else "REJECTED" if ranked else "NO_CANDIDATE"
            )
        receipts.append({
            "field_name": name,
            "field_family": spec.family,
            "crop_dimensions": list(spec.crop.size),
            "blank_crop": spec.blank_crop,
            "invocations": invocations,
            "primary_validator_clean": primary_validator_clean,
            "candidate_selected": ranked is not None,
            "retry_selected_as_final": retry_selected,
            "retry_changed_selected_value": (
                normalize_value(name, primary_value)
                != normalize_value(name, field.value)
            ),
            "normalization_ms": round(
                first_normalization_ms + second_normalization_ms, 3),
            "validation_ms": round(validation_ms, 3),
            "state": state.value,
        })
    return receipts
