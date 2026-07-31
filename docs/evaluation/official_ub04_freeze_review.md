# Official Tier C UB-04 freeze-readiness review

Recommendation: **DO NOT FREEZE**. Development correctness is complete, but denominator semantics
still require organiser confirmation. The three holdout documents remain untouched.

## Accepted-wrong regression

The previous accepted-wrong comparison was `patient_dob` (FL 10) on safe development ID
`251f79e97f77`. The primary OCR result was wrong but calendar-valid, normalization preserved the
plausible date, the generic validators passed, and the governor ACCEPTed its high confidence.
`dob_before_service` could not protect the DOB field because its context DOB was the same candidate.

The fix adds a DOB-only validator for one complete printed date, strict calendar parsing, plausible
age, and ordering before available claim dates. Official UB-04 DOB additionally requires independent
local OCR confirmation before ACCEPT. No threshold or global date validator changed. The rerun is
28/28 normalized, validator, and governed correct; all outcomes are ACCEPT.

## Retry funnel and latency

“Retry candidate accuracy” now means the retry attempt itself matches expected after normalization;
it no longer means merely that a retried field ended correct. Of 28 eligible fields, 27 were retried:
20 primary-wrong and seven primary-correct low/medium-confidence fields. Zero blank fields were
retried. All 27 retry candidates matched expected, all 27 were selected, and zero fields remain
unresolved.

Measured wall time is 44,968.195 ms total / 22,484.098 ms per page; retry OCR is 38,096.103 ms.
There were two shared Paddle page invocations and nine crop Paddle invocations, with zero Tesseract
process startups. Shared-page OCR supplied 24 selected candidates. Four second-scale text attempts
were never selected; the quantity Paddle attempt was also not selected, while deterministic component
recovery resolved that field. Seven correct primaries were retried without changing normalized value.
Do not remove these paths before a broader frozen regression proves behavior preservation; the former
DOB miss shows that validator-clean primary OCR is not sufficient evidence.

## ICD and candidate hashes

The curated validator subset is frozen against CMS FY 2026 ICD-10-CM, effective 2025-10-01. Decimal
punctuation is optional for canonical membership; valid-shape unknown codes still fail. Dictionary
hash: `3afcae74f6bf65b02908031580e8ce0b3b67a2758923845fb05a268aadd13311`. Source:
[CMS ICD-10 files](https://www.cms.gov/medicare/coding-billing/icd-10-codes).

The candidate manifest is `eval/results/official_ub04_freeze_manifest_candidate.json`; hashes are
UTF-8/LF stable. It records reproducibility inputs but does not authorize holdout scoring.
