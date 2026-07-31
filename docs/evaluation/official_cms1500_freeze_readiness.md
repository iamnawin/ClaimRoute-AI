# Official CMS-1500 freeze readiness

## Decision

**DO NOT FREEZE.** Coordinate authoring is complete, but the development extraction system is
not accurate or fast enough for an honest Tier A holdout run.

## Ready

- 41/41 eligible official names have normalized coordinates.
- 123/123 development crop instances are geometrically correct.
- Official and synthetic template paths remain separate.
- The evaluated service-line cap is explicitly three; lines 4-6 are absent.
- Ambiguous, unsupported, unscored, and no-expected-output fields are absent.
- Retry evidence now re-enters fusion, validation, and the governor.
- Candidate SHA-256 generation is deterministic.
- Holdout access remains zero.

## Blocking freeze

- Normalized development accuracy is 32/77 (41.5584%).
- Critical-field accuracy is 17/41 (41.4634%).
- Retry resolves 23/60 attempts (38.3333%).
- 45 populated instances remain unresolved.
- Full local processing takes 265.075 seconds/page and $0.003682/page.
- Checkbox extraction, dates, diagnosis codes, identifiers, and multi-word provider fields need
  measured field-policy/OCR work on the same three development pages.
- Two correctly normalized retry cases remain below the unchanged Balanced accept threshold;
  retain them as calibration questions until extraction confidence is improved.

## Candidate freeze inputs

`eval/results/official_cms1500_freeze_manifest_candidate.json` records deterministic SHA-256
hashes for the template, registration, extraction, normalization, field map, OCR/governor policy,
validators, evaluator, prices, and split manifest. It is explicitly `candidate_only_not_frozen`.
The hashes define what would be reviewed later; they do not authorize or execute holdout scoring.

## Required next gate

Improve the measured OCR/normalization clusters using only the three development documents,
rerun the development report, review the resulting accuracy and latency, then create a separate
freeze commit. Do not open the holdout before that commit is approved.
