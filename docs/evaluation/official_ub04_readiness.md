# Official Tier C UB-04 readiness

Recommendation: **DO NOT FREEZE TIER C**.

## Population and contract

Tier C contains six items: five deterministic links and one ambiguous link. The immutable split
uses two joint-highest-margin items for development, preserves three deterministic items as
untouched holdout, and excludes the ambiguous item. Holdout access remains zero. The authoritative
UB-192 crosswalk represents 28 possible evaluator names: 19 scored/supported source families plus
explicit unsupported or absent-output cases. `attending_qualifier` can reach scoring without a
ClaimRoute policy; provider NPI and service date are supported concepts but absent from the current
parser output.

## What is ready

- Official CMS-1450 and synthetic UB-04 template families are separate.
- Deterministic structural registration, orientation correction, artifact rejection, confidence,
  normalized coordinates, crop padding, and abstention are tested.
- Five development fields have fixed coordinates and 10/10 verified geometry.
- The existing primary OCR → typed retry → normalization → validation → governor path reaches
  10/10 final normalized accuracy and 4/4 critical accuracy on the narrow proof.
- External provider calls remain disabled; no multimodal files or configuration were touched.

## Remaining blockers

- Only five of 19 scored/supported field families have official coordinates.
- Primary OCR is 4/10, so the proof depends heavily on the local retry rung.
- Two correctly extracted diagnosis fields remain `ESCALATE` because the current ICD dictionary
  does not accept them; thresholds were deliberately not changed.
- Provider NPI and service date need an explicit parser/evaluator decision before they can be
  claimed as officially scored.
- No untouched holdout scoring is authorized by this development proof.

Next recommendation: expand coordinates only for the remaining scored, supported, geometrically
unambiguous development fields; measure them on the same two development IDs; then perform a
separate freeze review before any holdout access.
