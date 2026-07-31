# Official UB-04 development template expansion

Status: **development expansion complete; do not freeze; holdout untouched**.

The official CMS-1450 template now contains 25 concrete regions: 14 score-eligible regions and
11 regions retained with an explicit non-scoring status. Twenty regions are new since the
five-field proof. All 50 development crop instances were visually reviewed against the two frozen
development pages and are structurally correct.

## Coverage contract

| Category | Concrete regions | Treatment |
|---|---:|---|
| Supported | 14 | Included when populated by the evaluator |
| Blank but valid | 3 | Geometry retained; empty values are not penalized |
| Not printed | 6 | Repeated rows exist structurally, but organiser values are absent from both rendered forms |
| Pending organiser confirmation | 2 | FL 3b and FL 5 geometry retained; excluded from accuracy |
| Ambiguous | 1 source family | Patient address remains outside the template |
| Unsupported | 1 source family | Attending qualifier has no ClaimRoute policy |

Provider NPI, service date, payer name, and conditional attending-NPI semantics remain outside the
denominator pending an organiser/parser decision. No holdout document was opened or scored.

## Development measurement

| Measure | Result |
|---|---:|
| Score-eligible instances | 28 |
| Primary OCR | 8/28 |
| Local retries | 26/26 correct |
| Final normalized accuracy | 27/28 |
| Validator correctness | 27/28 |
| Final governed correctness | 27/28 |
| Governor outcomes | 28 ACCEPT |
| Wall latency | 53,446.639 ms; 26,723.320 ms/page |
| Local cost | $0.000742314; $0.000371157/page |
| External calls / cost | 0 / $0 |

The only remaining scored miss is a plausible but incorrect DOB that passes current date
validation. It is a validator false positive and remains a freeze blocker; thresholds were not
changed. The prior diagnosis false negatives came from a 20-entry, unversioned ICD allowlist that
omitted a valid FY 2026 code. The correction adds the CMS-verified code and compares dictionary
membership using punctuation-insensitive canonical form, while a synthetic negative test proves
unknown sibling codes still fail. The global ICD shape rule was not weakened.

Retry OCR is the dominant measured stage at 46,485.417 ms (87.0% of wall time). No latency
optimization was attempted. The repository-safe receipt is
`eval/results/official_ub04_development_expansion_summary.json`.
