# Project completion status

Updated: 2026-08-01 on `feat/local-intake-workspace`.

## Local document workspace

Status: complete for the P0 localhost intake and batch scope.

Implemented and tested:

- content-aware PNG, JPEG, TIFF/CCITT, multipage TIFF, PDF, and numeric-extension detection;
- exact file-role classification and mixed recursive inventory without symlink traversal;
- single, multiple, and selected folder processing with deterministic ordering;
- duplicate hashes, continue-on-error, per-document progress callbacks, and in-memory retry reuse;
- unified document results with evidence, validations, governor/retry/escalation summaries, costs,
  latency, warnings, and nullable evaluation;
- JSON/CSV document and batch exports without absolute paths;
- explicit process-only versus post-extraction evaluation workflows;
- local-only folder access through `CLAIMROUTE_APP_MODE=local_workspace`;
- retained public synthetic mode and disabled external escalation;
- existing official TIFF reader, fixed-width parsers, linkage, monochrome adapters, and Tier D
  label extraction reused without holdout or frozen-benchmark execution.

Validation receipt:

- focused intake/workspace/public UI/official reader tests passed;
- full suite: 233 passed, one Windows symlink test skipped;
- synthetic manual proof: four documents/five pages completed across PNG, TIFF, multipage TIFF,
  PDF, and numeric-extension content; one corrupt TIFF failed without aborting the batch;
- post-extraction synthetic evaluation: 44/44 normalized fields and 21/21 critical fields;
- JSON and CSV exports parsed, excluded absolute paths, and recorded zero external calls;
- three Tier A and two Tier C development containers matched their manifest hashes and were
  recognized as numeric-extension TIFF claim documents; protected holdout access remained zero.

## Known limitations

- Streamlit runs a batch synchronously; stop is honored between documents, not during an OCR call.
- Retry-safe reuse is in memory for the current session; there is no persistent job database.
- Folder scanning is an explicit finite pass, not watching or automatic ingestion.
- Text-native PDFs are rasterized and OCRed; native PDF text extraction is not implemented.
- TIFF/PDF page limits protect local memory but there is no production queue or concurrency layer.
- Tier D remains limited label-driven extraction, and unrecognized documents may route as
  unstructured rather than a structured claim form.
