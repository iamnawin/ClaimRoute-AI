"""OCR-text document classification and Tier-B claim-page selection."""
from __future__ import annotations

from dataclasses import dataclass
import re


CMS_MARKERS = ("HEALTHINSURANCECLAIMFORM", "CMS1500", "HCFA1500", "PATIENT", "INSURED")
UB_MARKERS = ("UB04", "UNIFORMBILL", "STATEMENTCOVERS", "REVENUE", "MEDICALRECORD")


def _score(text: str, markers: tuple[str, ...]) -> int:
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    return sum(marker in compact for marker in markers)


@dataclass(frozen=True)
class PageSelection:
    status: str
    claim_pages: list[int]
    attachment_pages: list[int]
    detected_format: str
    scores: list[int]


def select_claim_pages(page_texts: list[str], tier: str) -> PageSelection:
    tier = tier.upper()
    if tier == "C":
        scores = [_score(text, UB_MARKERS) for text in page_texts]
        return PageSelection("deterministic" if len(page_texts) == 1 else "ambiguous",
                             [0] if len(page_texts) == 1 else [], [], "UB-04", scores)
    if tier == "A":
        scores = [_score(text, CMS_MARKERS) for text in page_texts]
        return PageSelection("deterministic" if len(page_texts) == 1 else "ambiguous",
                             [0] if len(page_texts) == 1 else [], [], "CMS-1500", scores)
    if tier == "D":
        return PageSelection("deterministic", list(range(len(page_texts))), [],
                             "unstructured", [0] * len(page_texts))
    scores = [_score(text, CMS_MARKERS) for text in page_texts]
    top = max(scores, default=0)
    winners = [index for index, score in enumerate(scores) if score == top]
    if top < 2 or len(winners) != 1:
        return PageSelection("ambiguous", [], list(range(len(page_texts))), "CMS-1500", scores)
    selected = winners[0]
    return PageSelection("deterministic", [selected],
                         [index for index in range(len(page_texts)) if index != selected],
                         "CMS-1500", scores)

