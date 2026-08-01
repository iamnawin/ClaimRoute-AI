# Local intake and batch workspace design

## Purpose and boundary

The workspace is a localhost operator surface for processing judge-provided documents and folders.
It reuses ClaimRoute's extraction and official-data components; it is not a new OCR engine, model
adapter, public upload service, benchmark runner, or holdout evaluator.

The environment boundary is explicit:

- `CLAIMROUTE_APP_MODE=local_workspace`: local folder paths, unrestricted local file selection,
  batch processing, and dataset evaluation are enabled.
- unset or `public_synthetic`: the existing bundled-synthetic and attested single-file workflow is
  retained. Local folder access is absent.

External escalation is disabled in the local workspace. Raw values may appear in the authorized
local UI and downloads, but application errors and logs contain no field values.

## Reused flow

```text
bytes
  -> content signature and role classification
  -> page decoding
  -> existing synthetic or official extraction path
  -> validators, Cost Governor, and local retry
  -> unified application result
  -> optional post-extraction linkage and comparison
  -> JSON/CSV export
```

`app/intake.py` owns detection, decoding, role classification, and recursive inventory.
`app/workspace.py` owns process-only, batch, post-extraction evaluation, summary, and export
contracts. `app/service.py` remains the adapter for the existing image pipeline.

Official containers under a recognized `Group A` through `Group D` directory reuse the local OCR,
page-selection, monochrome CMS-1500/UB-04 registration, structured extraction, local retry, and
unstructured Tier D components under `eval/official/`. Results carry
`official_monochrome_adapter` or `official_unstructured_adapter` evidence semantics rather than
pretending to be synthetic-template evidence.

## Detection and file roles

Signatures are checked before extensions:

| Detected content | Handling |
|---|---|
| PNG signature | One raster page |
| JPEG signature | One raster page |
| little- or big-endian TIFF signature | All frames through the existing Pillow/CCITT reader |
| PDF header in the first 1,024 bytes | All pages rasterized locally |
| 320-byte fixed-width records | NSF-320 expected output |
| 192-byte fixed-width records | UB-192 expected output |
| generated ClaimRoute JSON with `fields` | Synthetic expected output |
| recognized matrix/specification text | Specification |
| ZIP or unknown binary | Unsupported |
| unrecognized text/empty content | Unknown |

Every item receives exactly one role: `CLAIM_DOCUMENT`, `EXPECTED_OUTPUT`, `SPECIFICATION`,
`ATTACHMENT`, `UNSUPPORTED`, or `UNKNOWN`. A numeric suffix such as `.001` has no special trust;
it is accepted only when its bytes identify a supported container. Expected output and
specifications never enter document OCR.

## PDF behavior

`pypdfium2==5.12.1` is pinned in `requirements.txt`. It is permissively licensed under
BSD-3-Clause or Apache-2.0 terms and wraps liberal-licensed PDFium. Each page is rendered to an RGB
image at scale 2.0 and then follows the same image/OCR path as other pages.

- Scanned PDF: embedded page pixels are rendered and OCRed.
- Text-native PDF: text is rendered to pixels and OCRed; native text objects are not extracted.
- Default page limit: 100, configurable through `CLAIMROUTE_MAX_PAGES` in local operation.
- Empty, corrupt, encrypted/unreadable, or over-limit PDFs return a value-free intake error.
- No raw PDF or rendered page is permanently stored by the workspace.

## Folder and batch behavior

Folder inventory uses deterministic recursive traversal with symbolic-link following disabled.
The UI displays the inventory before processing and lets the operator select a subset. Related
claim and expected-output files share a relative group label. Exports contain basenames and opaque
content hashes, never absolute local paths.

Batch ordering is deterministic by filename and content hash. Repeated hashes are processed once;
later copies are marked `DUPLICATE`. One corrupt or failed document produces a value-free failure
result and does not abort later documents. In-memory completed results can be supplied for
retry-safe reuse. Streamlit processing is synchronous, so the UI can honor a preselected stop
between documents but cannot interrupt OCR in the middle of a document.

The workspace is a finite explicit scan and process pass. It is not a filesystem watcher, daemon,
queue service, or automatic ingestion system.

## Unified result contract

Each document result contains:

- document and safe source IDs, basename, detected format/role, document type, and page count;
- processing status, per-page structured fields, validation results, and evidence provenance;
- governor, retry, escalation, unresolved-field, latency, and cost summaries;
- warnings and nullable evaluation evidence.

Private in-memory linkage text and group data use underscore-prefixed keys and are removed from
JSON exports. CSV exports contain document summaries or local field output, never absolute paths.

## Process Documents versus Evaluate Dataset

`Process Documents` never calls an expected-output parser. It completes extraction without ground
truth and leaves `evaluation` null.

`Evaluate Dataset` runs the identical extraction pass first. Only after the batch completes does it
parse expected-output items, perform deterministic linkage, normalize and compare fields, and add
PHI-safe correctness booleans/counts. Expected values cannot affect page selection, crops, OCR,
normalization, validation, governor routing, retries, or escalation.

## Benchmark protections

The workspace does not invoke the organiser-wide benchmark, the consumed Tier C holdout runner, or
frozen Day 11 commands. Development testing uses synthetic data and only explicitly approved
organiser development containers. Frozen artifacts remain read-only and unchanged.
