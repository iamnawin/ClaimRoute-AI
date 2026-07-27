"""The extraction spine (Day 5): preprocess -> route -> OCR -> layout map.

Produces a PageResult of FieldResult candidates with confidence, bbox, and
provenance. No governor/validators yet (Day 6) — every field is a RETRY-state
candidate until validation exists. Every stage logs to the cost ledger.
"""
from __future__ import annotations

import time

import yaml
from PIL import Image

from engine.ledger import CostLedger
from engine.layout.mapper import map_fields
from engine.ocr import get_engine
from engine.preprocess import preprocess_page
from engine.router import route
from engine.schemas import Attempt, FieldResult, PageResult

_PRICES = yaml.safe_load(open("configs/prices.yaml"))
VCPU_HOUR = _PRICES["compute"]["vcpu_hour_usd"]


def _cpu_cost(ms: float) -> float:
    return ms / 1000 / 3600 * VCPU_HOUR


def run_page(img: Image.Image, doc_id: str, ledger: CostLedger,
             primary_engine: str = "paddle", prep: bool = True) -> PageResult:
    # Tier 0
    t0 = time.perf_counter()
    if prep:
        pre = preprocess_page(img)
        work, quality = pre["processed"], pre["quality_before"]
    else:
        work, quality = img, {"quality_score": -1.0}
    prep_ms = (time.perf_counter() - t0) * 1000
    ledger.log(doc_id=doc_id, page_id="p1", operation="preprocess",
               cost_usd=_cpu_cost(prep_ms), latency_ms=prep_ms)

    # Router (free)
    t0 = time.perf_counter()
    r = route(work)
    route_ms = (time.perf_counter() - t0) * 1000
    ledger.log(doc_id=doc_id, page_id="p1", operation="route",
               cost_usd=_cpu_cost(route_ms), latency_ms=route_ms,
               meta={"type": r["document_type"], "conf": r["confidence"]})

    page = PageResult(doc_id=doc_id, page_id="p1", doc_type=r["document_type"],
                      quality_score=quality["quality_score"])
    if r["document_type"] not in ("cms1500", "ub04"):
        return page                     # unstructured/unknown path arrives Day 7-8

    # Tier 1: primary OCR + layout mapping
    eng = get_engine(primary_engine)
    t0 = time.perf_counter()
    words = eng.extract(work)
    ocr_ms = (time.perf_counter() - t0) * 1000
    ledger.log(doc_id=doc_id, page_id="p1", operation=f"ocr_{primary_engine}",
               cost_usd=_cpu_cost(ocr_ms), latency_ms=ocr_ms)

    fields = map_fields(words, work, r["document_type"], r["variant"])
    for name, c in fields.items():
        fr = FieldResult(doc_id=doc_id, page_id="p1", field_name=name,
                         value=c["value"] or None, confidence=c["conf"],
                         bbox=tuple(c["bbox"]) if c["bbox"] else None)
        fr.attempts.append(Attempt(rung="primary_ocr", engine=primary_engine,
                                   value=c["value"] or None, confidence=c["conf"],
                                   cost_usd=0.0, latency_ms=0.0))
        page.fields[name] = fr
    return page
