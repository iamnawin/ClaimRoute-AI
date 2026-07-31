# Official Tier C UB-04 readiness

Recommendation: **PROVISIONAL FREEZE AUTHORIZED; HOLDOUT NOT YET RUN**.

## Provisional freeze update

Organiser denominator clarification was unavailable before the deadline. The versioned policy now
scores only the 14 visible, supported, unambiguous development fields per page; conditional fields
enter only with independent visible-population confirmation. Every nonblank organiser-expected
field remains in a separate extended coverage denominator. Exclusions never count as correct.

The UTF-8/LF-stable frozen manifest is
`eval/results/official_ub04_freeze_manifest.json`. It covers the field map, official template,
registration, normalization, denominator policy, ICD dictionary/version, retry implementation and
profiles, validators/policies, governor/pipeline configuration, extraction/evaluation, one-time
holdout runner, and immutable development/holdout split. The three holdout documents remain
untouched. The freeze authorizes the separately invoked one-time run; it is not a holdout result.

## Freeze-review update

The accepted-wrong FL 10 DOB path is resolved with a DOB-specific validator and required independent
local confirmation. The development rerun is 28/28 normalized, validator, and governed correct, with
28 ACCEPT outcomes. Retry candidate accuracy is now explicitly 27/27 expected-value matches; zero
fields are unresolved. The candidate denominator and stable freeze hashes are recorded separately.
Freeze remains blocked by unanswered organiser semantics for FL 3b, FL 5, record-only repeated rows,
and parser-absent/conditional fields. Candidate hashes do not authorize holdout access.

## Development expansion update

The official template now records 25 concrete regions with form locator, canonical name, crop,
normalization, validators, criticality, blank policy, repeated-row behavior, and support status.
Twenty regions are new. Development geometry is 50/50; the legitimate scoring denominator is
28 instances after excluding organiser-semantic conflicts. Primary OCR is 8/28, retry is 26/26,
and final normalized, validator, and governed correctness are each 27/28. All 28 outcomes ACCEPT.
The one remaining miss is a plausible incorrect DOB that the current date validators accept.

Stage profiling identifies retry OCR as dominant: 46,485.417 ms of 53,446.639 ms total. Local
cost is $0.000371157/page. External calls and holdout access remain zero.

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

- One plausible but wrong DOB survives validation and is incorrectly ACCEPTed.
- Primary OCR is 8/28, so development accuracy remains retry-dependent.
- FL 5 has a 10-character UB-192 expectation but a nine-digit printed EIN; FL 3b is printed while
  absent from the development expected output. Both remain outside the denominator.
- Repeated line 2/3 record values are not printed on either development form.
- Provider NPI and service date need an explicit parser/evaluator decision before they can be
  claimed as officially scored.
- No untouched holdout scoring is authorized by this development proof.

Next recommendation: perform a freeze review that resolves the DOB validator false positive and
the FL 3b / FL 5 / repeated-row organiser semantics. Do not authorize holdout until that review
freezes the denominator, template hash, validator dictionary version, and stage receipt.
