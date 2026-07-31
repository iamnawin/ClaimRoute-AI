# Official organiser sample benchmark

Status: **Tier C frozen holdout completed under a provisional denominator policy** (31 Jul 2026).

This evidence is separate from `eval/frozen/`, which remains the unchanged synthetic benchmark.
The organiser directory is read-only input and is not tracked by Git. No source image, fixed-width
record, parsed value, OCR text, or PHI-bearing artifact is written to this repository.

## Tier C frozen holdout update

**Official Tier C UB-04 holdout result under the provisional visible-and-supported denominator
policy.** The one-time frozen run evaluated three linked documents/pages: primary normalized
accuracy 36/42 (85.714%), extended nonblank-field coverage 36/63 (57.143%), and critical normalized
accuracy 16/18 (88.889%). Registration succeeded on 3/3 pages; external calls and measured external
cost were zero. The result uses the policy label **Provisional denominator policy due to unavailable
organiser clarification.** It is not a universal UB-04 benchmark and does not replace the frozen
synthetic benchmark. Full limitations are in `docs/evaluation/official_ub04_holdout.md`.

## What was implemented

`eval/official/` provides CCITT TIFF and multipage ingestion, NSF 320 and UB 192 parsing from the
supplied specifications, abstaining record linkage, ClaimRoute field mapping, field-aware
normalization, Tier-B page filtering, conservative Tier-D label extraction, and aggregate-only
reporting. The compatibility layer reuses ClaimRoute OCR objects, layout templates, validators,
confidence fusion, governor decisions, and configured compute pricing. External calls are disabled.

The frozen router was not changed. Its red-form fingerprint cannot classify the organiser's 1-bit
monochrome scans, so the adapter supplies OCR-text classification and a grayscale form extent.
This boundary is explicit rather than hidden as a synthetic-to-official accuracy claim.

## Measured receipt

| Tier | Containers | Pages | Records | Deterministic links | Abstained links | Field result |
|---|---:|---:|---:|---:|---:|---:|
| A | 12 | 12 | 12 NSF | 11 | 1 | 0 / 299 exact |
| B | 5 | 21 | 5 NSF | 4 | 1 | 0 / 121 exact |
| C | 6 | 6 | 6 UB | 5 | 1 | 0 / 105 exact |
| D | 7 | 28 | 7 NSF | 6 | 1 | 1 / 168 exact |

All 30 TIFF containers and 67 pages decoded. Linkage abstained on four items, so no combined
official score is calculated. Tier-B page selection was 4/4 on deterministically linked,
page-evaluable containers; 15/15 expected attachments were rejected. These denominators exclude
the ambiguous linkage item. Cost for Tier B and the overall cost/page use all organiser input
pages, including rejected attachments.

Measured local compute was approximately **$0.0000291 per input page** at the configured vCPU
price, with **28.32 input pages/minute** during this workstation run. These are prototype local
measurements, not production claims. Measured external calls and spend were zero.
The recorded terminal `HUMAN_REVIEW` rate was 0%, but this is not a resolution claim: unresolved
`RETRY`/`ESCALATE` fields were not converted to human review because this safety run disabled retry
and all external escalation.

The near-zero field accuracy is a valid failure signal: synthetic red-grid templates do not align
to the organiser's legacy monochrome CMS/UB layouts, and Tier D needs an organiser-confirmed
required-field subset. Do not quote the synthetic 99.716% result as official-dataset accuracy.

## Safety controls

- Local Tesseract only; no provider or network processing.
- Source files opened read-only and never copied into the repository.
- Expected values and OCR values compared only in memory.
- Reports contain opaque SHA-256-derived source IDs, field names, counts, booleans, and timings.
- Ambiguous and unmatched links abstain from accuracy scoring.
- Tests use generated TIFFs and masked fixed-width records only.
- Full regression result: 92 passed, 0 failed. All 36 inventoried source hashes still match.

## Remaining organiser questions

1. Provide an authoritative filename-to-record crosswalk or confirm positional ordering.
2. Confirm the exact Tier-D required-field subset and scoring denominator.
3. Provide authoritative Tier-B claim-page indexes and attachment labels.
4. Confirm optional/blank record-field inclusion rules and UB Type-80 identifier semantics.
5. Confirm permitted local retention and deletion requirements for possible PHI.

## Reproduce

```powershell
uv run python -m eval.official.benchmark inspect --dataset-root "D:\AI-Workspace\hackathon 2026\Images & Output"
uv run python -m eval.official.benchmark run --dataset-root "D:\AI-Workspace\hackathon 2026\Images & Output"
uv run pytest tests/test_official_dataset.py -q
```

The next engineering step, after organiser confirmation, is to create organiser-layout templates
on a separately declared calibration subset, freeze them, then rerun untouched evaluation items.
