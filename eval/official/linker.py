"""Expected-record linkage from local OCR evidence, with abstention."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from eval.official.parsers import OfficialRecord


def _compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


@dataclass(frozen=True)
class LinkResult:
    status: str
    record_ordinal: int | None
    score: int
    margin: int
    evidence_count: int
    method: str = "unique normalized exact anchors from local OCR"

    def safe_receipt(self) -> dict:
        return {"status": self.status, "record_ordinal": self.record_ordinal,
                "score": self.score, "margin": self.margin,
                "evidence_count": self.evidence_count, "method": self.method}


def _anchors(record: OfficialRecord) -> set[str]:
    values = {_compact(value) for value in record.fields.values()}
    for line in record.service_lines:
        values.update(_compact(value) for value in line.values())
    return {value for value in values if len(value) >= 5 and not set(value) <= {"0"}}


def link_record(ocr_text: str, records: list[OfficialRecord]) -> LinkResult:
    haystack = _compact(ocr_text)
    anchors = [_anchors(record) for record in records]
    frequency = Counter(value for row in anchors for value in row)
    scored = []
    for record, row in zip(records, anchors):
        hits = [value for value in row if value in haystack]
        score = sum(3 if frequency[value] == 1 else 1 for value in hits)
        scored.append((score, len(hits), record.ordinal))
    scored.sort(reverse=True)
    if not scored or scored[0][0] == 0:
        return LinkResult("no_match", None, 0, 0, 0)
    best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    margin = best[0] - second_score
    if margin <= 0:
        return LinkResult("ambiguous", None, best[0], margin, best[1])
    return LinkResult("deterministic", best[2], best[0], margin, best[1])

