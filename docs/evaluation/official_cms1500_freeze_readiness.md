# Official CMS-1500 freeze readiness

## Decision

**DO NOT FREEZE.** OCR optimization materially improved development performance, but 31/77
populated fields remain unresolved and six checkbox values remain confidently misclassified.

## Ready

- 41/41 eligible official names have normalized coordinates.
- 123/123 development crop instances are geometrically correct.
- Official and synthetic template paths remain separate.
- The evaluated service-line cap is explicitly three; lines 4-6 are absent.
- Ambiguous, unsupported, unscored, and no-expected-output fields are absent.
- Retry evidence now re-enters fusion, validation, and the governor.
- Candidate SHA-256 generation is deterministic.
- Holdout access remains zero.
- Field-family retry profiles, shared page OCR, typed candidate ranking, and validated early stop
  are deterministic and covered by synthetic tests.
- Development normalized accuracy improved from 32/77 to 46/77; critical accuracy improved from
  17/41 to 26/41.
- Latency fell from 119,186.826 to 63,523.322 ms/page and local cost fell from $0.001655373 to
  $0.000882268/page.

## Blocking freeze

- Normalized development accuracy is 46/77 (59.7403%).
- Critical-field accuracy is 26/41 (63.4146%).
- Retry resolves 37/60 attempts (61.6667%).
- 31 populated instances remain unresolved.
- Full local processing still takes 63.523 seconds/page and $0.000882/page.
- Checkbox marks, diagnosis codes, insured IDs, dates, and label-heavy text remain blockers.
- Two correctly normalized retry cases remain below the unchanged Balanced accept threshold;
  retain them as calibration questions until extraction confidence is improved.

## Candidate freeze inputs

`eval/results/official_cms1500_freeze_manifest_candidate.json` records deterministic SHA-256
hashes for the template, registration, extraction, normalization, field map, OCR/governor policy,
validators, evaluator, prices, and split manifest. It is explicitly `candidate_only_not_frozen`.
The hashes define what would be reviewed later; they do not authorize or execute holdout scoring.

## Required next gate

Review the remaining development clusters and the refreshed candidate hashes before any separate
freeze decision. Do not open the holdout until a freeze commit is explicitly approved.
