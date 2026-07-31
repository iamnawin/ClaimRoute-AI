# Official CMS-1500 OCR failure analysis

This development-only analysis covers all 45 baseline normalized misses and all 37 unresolved
local retries. It contains classes, counts, confidence bands, crop dimensions, and policy outcomes;
it contains no OCR text, expected values, source IDs, filenames, crops, or PHI. Historical per-field
latency was not persisted, so latency is reported honestly at the measured page level rather than
fabricated per row.

## Highest-impact clusters

| Priority | Cluster | Affected | Expected gain | Latency | Risk |
|---:|---|---:|---:|---|---|
| 1 | Repeated crop OCR/registration | 60 retries | 0 fields | high reduction | low |
| 2 | Six-digit date separation | 5 | 5 fields | neutral | low |
| 3 | Label-contaminated typed candidates | 17 | up to 7 fields | small reduction | medium |
| 4 | Checkbox mark misclassification | 6 | 0 measured | neutral | high |

The baseline output classes were 32 mixed, 6 blank, 4 alphabetic, and 3 numeric. Retry outputs
were 19 mixed, 14 numeric, and 12 blank. The safe row-level receipt is available in JSON and CSV.
Four checkbox thresholds were tested and recovered zero cases, so checkbox logic was not changed.

## Decision

Implement deterministic six-digit date normalization, shared page OCR, bounded field-family
profiles, typed candidate ranking, validated early stop, and registration reuse. Do not change
coordinates, thresholds, dictionaries, or holdout state.
