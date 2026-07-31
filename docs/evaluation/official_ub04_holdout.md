# Official Tier C UB-04 frozen holdout

**Official Tier C UB-04 holdout result under the provisional visible-and-supported denominator
policy.** The required policy label is: **Provisional denominator policy due to unavailable
organiser clarification.** This is not a universal UB-04 benchmark.

## Run identity

- Frozen starting commit: `cf34b8bb6fb9d52fe0a3635c656475df639f0805`
- Manifest SHA-256: `888935e498744b1d1971fd02519057e55027ed26bda09e1f7c172f93a2308f88`
- Manifest verification: 18/18 frozen inputs matched
- Population: 3 holdout documents, 3 evaluated pages, 3 linked records, 0 abstentions
- One-time run: consumed successfully; the receipt prevents a second run
- Conditional fields independently confirmed visible: none

## Results

| Measure | Result |
|---|---:|
| Primary normalized accuracy | 36/42 (85.714%) |
| Extended nonblank-field coverage | 36/63 (57.143%) |
| Critical-field normalized accuracy | 16/18 (88.889%) |
| Structural registration success | 3/3 (100%) |
| Final normalized unresolved fields | 6 |
| Excluded-field coverage | 0/21 correct; 2/21 present |
| External calls / measured cost | 0 / $0 |

Primary failures were `patient_name` (2), `provider_name` (1), `statement_from` (1),
`statement_to` (1), and `line1_units` (1). Their form locators were FL 8b (2), FL 1 (1),
FL 6 From (1), FL 6 Through (1), and FL 46 (1).

The receipt records primary full-page OCR latency only: 5,503.402 ms total / 1,834.467 ms per
page, equivalent to 32.707 pages/minute and an OCR-only compute estimate of $0.000025479/page at
the configured $0.05/vCPU-hour. Observed end-to-end command wall time was approximately 72.6
seconds, or 24.2 seconds/page and 2.48 pages/minute; the runner did not persist an end-to-end stage
or cost receipt.

## Evidence boundary

`compare_fields` stores normalized equality only, so raw exact-match accuracy was not captured.
The frozen runner also did not retain primary correctness, retry attempts/candidate accuracy,
retry-selected count, validator correctness, terminal governor outcomes, or governed correctness
separately. These metrics are reported as unavailable rather than reconstructed by another
holdout pass. The 36/42 result is final post-retry normalized extraction correctness, not a claim
that 36 fields reached a particular governor state.

The committed receipt contains safe IDs, canonical field names, booleans, counts, and timings only.
It contains no images, crops, OCR text, expected values, organiser filenames, or absolute paths.
No frozen input changed after the run.
