# ClaimRoute integration defect register

This register contains PHI-safe engineering evidence only. Record statuses, counts,
latencies, commit identifiers, and safe hash prefixes. Never record extracted values,
OCR text, organiser filenames, source images, crops, expected records, credentials, or
machine-specific absolute paths.

Safety boundaries:

- Tier A holdout documents are protected and must not be opened or evaluated.
- The consumed Tier C holdout must not be rerun; inspect only its frozen receipt.
- Authorized development documents remain outside the repository.
- External providers remain disabled unless a separate, explicit live-test approval is given.

## Current integration baseline

- Integration commit: `43b5ee65842d6c5b5110b2d9243f0ef1be1b833f`
- Test reconciliation commit: `ccc3ea292fcca01d719f7c510d92d87d659b8375`
- Full regression result: **451 passed, 3 skipped**
- External calls during integration validation: **0**
- Protected holdout access during integration validation: **0**

## Historical evidence attribution

### Naveen local-intake branch at `e31fcd0`

- Automated result: **233 passed, 1 skipped**.
- Synthetic-safe intake verified PNG, JPEG, TIFF, multipage TIFF, PDF,
  numeric-extension TIFF, recursive folder discovery, duplicate detection,
  corrupt-file isolation, and JSON/CSV exports.
- The first authorized-development manual run decoded a one-page TIFF but returned
  `document_type=unstructured`, no fields, and `COMPLETED`. That run exposed D-001;
  it was not a successful extraction.
- External provider calls: **0**.

### Bhavya status/routing branch at `d022c54`

- Added content-based monochrome form routing and removed the Group A-D folder-name
  dependency.
- Added honest document status semantics and PARTIAL-result visibility.
- Authorized-development verification produced a CMS-1500 result with non-empty fields,
  validations, governor decisions, and zero external calls. Only safe aggregate counts
  were retained.
- This branch also exposed retry OCR as the dominant latency stage; see D-002.

## D-001 - Monochrome claim routed as `unstructured` and falsely completed

Status: **RESOLVED**

### Root cause

The color router fingerprints red dropout ink. Monochrome scans have no red-channel
separation, so the router returned `unstructured`. The monochrome-capable adapter was
reachable only through a Group A-D folder convention. Separately, the workspace hardcoded
`COMPLETED`, so an empty field set produced a false success with zero unresolved fields.

### Resolution

- Route red-router abstentions through content-based CMS-1500/UB-04 marker detection.
- Use `form="auto"`; folder names never decide claim form type.
- Zero meaningful fields -> `FAILED_EXTRACTION`.
- Fields with unresolved applicable values -> `PARTIAL`.
- Fully resolved fields -> `COMPLETED`.
- A batch containing `FAILED` or `FAILED_EXTRACTION` -> `COMPLETED_WITH_ERRORS`.
- A PARTIAL-only batch -> `COMPLETED_WITH_REVIEW`.
- PARTIAL outputs remain selectable and evaluable.
- INAPPLICABLE fields do not inflate unresolved counts.

### Current verification

Synthetic routing and status contracts pass for monochrome CMS-1500 pages in arbitrary,
Group A, and nested folders, plus a color CMS-1500 inside a folder named `group c`.
The authorized-development receipt reports CMS-1500, `PARTIAL`, 41 produced fields,
11 unresolved, 14 inapplicable, 11 pending multimodal, and zero external calls. No
extracted values were retained here.

## D-002 - Retry OCR dominates local latency

Status: **OPEN - frozen evaluation files prevent an in-scope optimization**

The current authorized-development receipt records 50.469 seconds total latency, of
which 46.729 seconds is retry OCR. Earlier branch measurements showed the same pattern:
a second full-page OCR pass and per-field crop retries dominate processing time.

The likely optimization points are in files covered by the official freeze manifest.
Changing them would invalidate frozen evidence and therefore requires an explicit re-freeze
decision. No optimization was attempted during integration.

Candidate work after re-freeze approval:

1. Reuse primary full-page OCR words instead of repeating the shared-page pass.
2. Benchmark the existing local OCR engines for small retry crops.
3. Cache preprocessing by crop/profile only if measurement still justifies it.

## D-003 - Local UI omits full provider-state visibility

Status: **OPEN - presentation limitation**

The result shows pending multimodal, pending human review, and external-call counts, but
does not expose all requested provider-state fields: eligibility, enabled policy, provider,
configured model, credential availability, attempted flag, and reason not attempted.
The local policy remains safe: provider calls are disabled and no data is sent.

## D-004 - Batch summary and empty-evaluation display are incomplete

Status: **OPEN - presentation/contract limitation**

The batch UI shows files, pages, completed, partial, combined failures, unresolved, cost,
and throughput. It does not separately display failed extraction, inapplicable, pending
multimodal, human review, or external calls. When evaluation has zero valid pairs, the UI
currently formats the missing accuracy as `0.00%`; it should instead state:

`Accuracy unavailable - no valid evaluation pairs`

The underlying unresolved count is numeric and does not display `Unknown` in current
workspace results.

## Environment-divergence finding

The reported behavioral difference was not caused by stale application code. It was caused
by the former folder-name routing gate: identical monochrome bytes followed different paths
depending on placement. Content-based routing resolved that divergence.

Two local execution constraints remain:

- Start Streamlit with the project virtual-environment interpreter.
- Start from the repository root because configuration paths are relative.

The authorized development document was moved outside the repository after hash verification.
Standing ignore rules for `authorized-development/`, TIFF inputs, generated submission outputs,
and `tmp/` reduce the chance of accidental staging.
