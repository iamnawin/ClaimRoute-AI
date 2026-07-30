"""Grounding check — a multimodal answer is a CANDIDATE, not truth.

A paid model that returns a confident, well-formatted, validator-passing value
it never actually saw is the most expensive failure mode in this architecture:
it costs money AND corrupts the output, and high confidence hides it. So every
response is tested against evidence before it is allowed to compete with the
OCR candidates.

Deliberately mechanical rules (a judge can predict every verdict):
  1. structured   - parsed as JSON with the required keys
  2. typed        - matches the field's expected shape
  3. grounded     - the value's characters appear in the model's own visible_text
  4. no-invention - visible_text is not wildly longer than what a box can hold
  5. validated    - required validators PASS (checked by the caller, on re-entry)

A rejected response still costs money — the call was made. Rejections are
counted and reported; hiding them would flatter the cost story.
"""
from __future__ import annotations

import re

from engine.governor import field_policy
from engine.vision.base import VisionResponse

MAX_VISIBLE_CHARS = 120        # one form box; more than this means it read the page
_NON_ALNUM = re.compile(r"[^a-z0-9]")

# Expected shape per field family. Only enforced when we have a real expectation;
# absent means "no type claim", not "anything goes" (validators still run).
_TYPE_PATTERNS = {
    "npi": re.compile(r"^\d{10}$"),
    "zip": re.compile(r"^\d{5}(-?\d{4})?$"),
    "cpt": re.compile(r"^[0-9A-Z]{5}$"),
    "rev_code": re.compile(r"^\d{3,4}$"),
    "currency": re.compile(r"^\$?\s*[\d,]+(\.\d{1,2})?$"),
    "date": re.compile(r"^[\d]{1,4}[-/ ]?[\d]{1,2}[-/ ]?[\d]{1,4}$"),
    "icd10": re.compile(r"^[A-TV-Z][0-9][0-9A-Z]\.?[0-9A-Z]{0,4}$"),
}


def _type_key(field_name: str) -> str | None:
    b = re.sub(r"^line\d+_", "", field_name)
    if b.endswith("npi"):
        return "npi"
    if b in ("patient_zip",):
        return "zip"
    if b in ("cpt_code", "hcpcs"):
        return "cpt"
    if b == "rev_code":
        return "rev_code"
    if b in ("total_charge", "total_charges", "charges", "amount_paid"):
        return "currency"
    if b.startswith("diagnosis_code") or b == "principal_dx":
        return "icd10"
    if "date" in b or b == "patient_dob":
        return "date"
    return None


def _squash(s: str) -> str:
    return _NON_ALNUM.sub("", str(s or "").lower())


def check(resp: VisionResponse, field_name: str) -> list[str]:
    """-> list of rejection reasons. Empty list means the answer may compete."""
    rejects: list[str] = []

    if not resp.ok:
        return [f"unstructured: {resp.parse_error}"]

    value = (resp.value or "").strip()
    visible = (resp.visible_text or "").strip()
    p = field_policy(field_name)

    # An empty answer is only legitimate where the form permits a blank box.
    if not value:
        if not p.get("optional"):
            rejects.append("empty value on a non-optional field")
        return rejects

    # 3. Grounded: the answer must be backed by what the model says it saw.
    #    Squashed comparison tolerates punctuation/spacing normalisation (which
    #    we WANT the model to do) while still catching invented characters.
    sv, svis = _squash(value), _squash(visible)
    if not svis:
        rejects.append("no visible_text evidence supplied")
    elif sv not in svis:
        rejects.append(f"ungrounded: value {value!r} not present in visible_text {visible!r}")

    # 4. No-invention: a single form box cannot contain a paragraph.
    if len(visible) > MAX_VISIBLE_CHARS:
        rejects.append(f"visible_text too long ({len(visible)} chars) for one field box")

    # 2. Typed: the value must look like the field it claims to be.
    tk = _type_key(field_name)
    if tk and not _TYPE_PATTERNS[tk].match(value.replace(" ", "")):
        rejects.append(f"type mismatch: {value!r} is not a valid {tk}")

    return rejects
