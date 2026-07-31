# Official UB-04 five-field development proof

Status: **complete for the frozen development subset; holdout untouched**.

The official monochrome CMS-1450 family is separate from the synthetic `ub04_v2/v3` templates.
Registration uses the outer horizontal-rule group, the 23-line revenue grid, and stable rule
endpoints. It corrects cardinal orientation, rejects page-edge scan artifacts, records revision and
confidence, and abstains below 0.70 confidence. Expected values were consulted only after the five
regions were fixed and visually checked.

| Measure | Result |
|---|---:|
| Development documents | 2 |
| Registration confidence | 0.933–0.935 |
| Geometrically correct / visibly populated crops | 10/10 |
| Primary normalized OCR | 4/10 |
| Local retries attempted / correct | 9/9 |
| Final normalized accuracy | 10/10 |
| Critical accuracy | 4/4 |
| Validator pass | 8/10 |
| Governor outcomes | 8 ACCEPT / 2 ESCALATE |
| Measured latency | 49,583.060 ms total; 24,791.530 ms/page |
| Measured local cost | $0.000688650 total; $0.000344325/page |
| External calls / cost | 0 / $0 |
| Holdout access | 0 |

The five fields are FL 3a `patient_control_no`, FL 12 `admission_date`, FL 46 `line1_units`,
FL 47 Totals `total_charges`, and FL 67 `principal_dx`. They exercise text, date, quantity, money,
and code normalization in different geometric regions.

Two diagnosis instances normalize exactly and pass ICD shape validation but fail the existing
dictionary validator, so the unchanged governor conservatively emits `ESCALATE`. This is a
validator-coverage limitation, not an OCR or geometry miss. The proof also fixed two reusable retry
defects: UB-04 `principal_dx` now enters diagnosis-code candidate parsing, and money candidates
preserve the validator-compatible typed representation before normalized-key deduplication.

The repository-safe row-level receipt is
`eval/results/official_ub04_five_field_proof_summary.json`. It contains safe IDs, coordinates,
booleans, validator states, governor states, latency, and cost only—no page pixels, crops, filenames,
OCR text, expected values, or PHI.
