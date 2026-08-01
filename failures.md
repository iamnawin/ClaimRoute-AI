# failures.md — PHI-safe defect register

Active defect register for the local intake/extraction workspace.

**Recording rules.** This file records only safe metadata: safe document identifiers
(content hash prefixes), statuses, counts, latencies, root causes and fix status. It must
never contain extracted patient values, OCR text, organiser filenames, crops, images,
expected records, or API keys.

---

## D-001 — Monochrome claim scans were routed as `unstructured` and reported `COMPLETED`

| Attribute | Value |
|---|---|
| Safe document id | `5858cb1e596e` |
| Observed status (before) | `COMPLETED` |
| Document type (before) | `unstructured` |
| Page count | 1 |
| Extracted fields (before) | 0 |
| Validations (before) | 0 |
| Retry count (before) | 0 |
| Unresolved fields (before) | 0 |
| Pending escalation (before) | 0 |
| External provider calls | 0 |
| Stage latency (before) | ~2–3 s total (decode + router only; no OCR ladder ran) |
| Severity | High — a silent false success |
| Fix status | **FIXED** (routing + status contract) |

### Root cause

Two independent defects compounded into a silent false success.

1. **Routing.** `engine/router.py` fingerprints claim forms by their *red dropout ink*
   (`red_mask`, `router.py:29` requires `r-g>20 and r-b>20`). A monochrome or 1-bit scan has
   `R==G==B`, so the mask is empty and the red-ink fraction is exactly `0.000000`, below
   `RED_FRACTION_MIN = 0.0015`. The router therefore returns `unstructured`
   (`router.py:118-121`), and `engine/extract.py:61-62` returns an **empty page immediately**,
   before any OCR runs.

   The monochrome-capable adapter (`eval/official/extraction.py`) that exists precisely for
   these scans was reachable **only** when the containing folder was named `Group A`–`Group D`
   (`app/workspace.py:_official_tier`). Routing therefore depended on a filesystem path
   convention rather than on document content.

2. **Status semantics.** `_unify_receipts` hardcoded `processing_status: "COMPLETED"`, and
   `unresolved_fields` was computed by iterating the extracted fields — so a document with
   zero fields reported zero unresolved fields and clean success.

Measured on the authorized development document: red-ink fraction `0.000000`, router verdict
`unstructured`.

### Fix

- `app/workspace.py` — when the red-ink router abstains on page 1, route by content through
  the official monochrome adapter instead of by parent folder name (`_red_router_abstains`,
  and `form="auto"` resolved from CMS/UB marker scores).
- `app/workspace.py` — `_document_status()` makes an empty extraction `FAILED_EXTRACTION` and
  an extraction with unresolved required fields `PARTIAL`. `COMPLETED` now means what it says.
- `app/workspace.py` — `_batch_status()` returns `COMPLETED_WITH_REVIEW` when any document is
  `PARTIAL` or `FAILED_EXTRACTION`; `COMPLETED_WITH_ERRORS` is retained for hard failures.
- `app/workspace.py` / `app/streamlit_app.py` — `PARTIAL` documents keep contributing to batch
  summary metrics, evaluation and the result selector rather than disappearing from the UI.
- Claim-page abstention now reports `FAILED_EXTRACTION` instead of `COMPLETED`.

### Validation

| Attribute | Value (after) |
|---|---|
| Document type | `cms1500` |
| Processing status | `PARTIAL` |
| Extracted fields | 41 (36 with non-empty values) |
| Validation rows | 41 — verdicts `PASS` 24, `FAIL` 17, `INAPPLICABLE` 4 |
| Governor summary | `ACCEPT` 17, `ACCEPT_WITH_FLAG` 6, `ESCALATE` 18 |
| Fields retried | 29 |
| Unresolved fields | 18 |
| External provider calls | 0 |
| Evidence semantics | `official_monochrome_adapter` |
| Regression tests | `tests/test_workspace_status_contract.py` — 7 tests |

---

## D-002 — Retry OCR dominates latency (OPEN, not fixed here)

| Attribute | Value |
|---|---|
| Safe document id | `5858cb1e596e` |
| Observed status | `PARTIAL` (correct) |
| Total latency | ~130 s |
| Fix status | **OPEN — blocked by the frozen-evidence restriction** |

### Measured stage latency

| Stage | Latency | Share |
|---|---|---|
| retry OCR | 115.2 s | 97.3 % |
| preprocessing | 2.8 s | 2.3 % |
| crop generation | 0.22 s | 0.2 % |
| registration | 0.21 s | 0.2 % |
| normalization / validation / governor | < 0.02 s | ~0 % |

Retry OCR decomposes into a **second full-page pass** (`shared_page` profile, 55.6 s) plus
per-field crop retries (58.4 s across 20 fields that actually invoked; 9 fields already
early-exit at ~0 ms via `should_stop_retry`). A separate primary full-page pass costs 13.6 s.

### Root cause

Two full-page OCR passes run per document, and the per-field crop retries use the `paddle`
engine. On this machine a small crop measures ~2.3 s under paddle versus ~0.25 s under
tesseract — roughly 9× — so crop-level engine choice, not process launch overhead, is the cost.

### Why it is not fixed here

The three files that would have to change — `eval/official/extraction.py`,
`eval/official/ocr_retry.py` and `eval/official/ocr_retry_profiles.yaml` — are all listed in
`FREEZE_FILES` (`eval/official/freeze_readiness.py:8-20`). Editing them changes
`eval/results/official_cms1500_freeze_manifest_candidate.json` and therefore modifies frozen
benchmark evidence, which the current task explicitly forbids. Optimization needs an explicit
decision to re-freeze.

### Candidate optimizations (for that decision)

1. Reuse the primary OCR word list for the `shared_page` retry pass instead of re-running a
   second full-page OCR (~55 s).
2. Use tesseract rather than paddle for small field crops (~9× on measured crops).
3. Cache preprocessing per crop/profile pair.

---

## COLLEAGUE ENVIRONMENT DIVERGENCE

Investigated on the assumption that this checkout was stale. **It was not.**

| Attribute | Expected | Actual on this system | Verdict |
|---|---|---|---|
| Canonical base | `2350bb6` | present (`merge-base --is-ancestor` → 0) | match |
| OpenRouter final | `2f695c9` | present — it *is* `HEAD` | match |
| Branch | current work branch | `feat/openrouter-live-routing-final` | match |
| `app/` sources | Naveen's latest | **byte-identical** (`git diff 2350bb6 HEAD -- app/` empty) | match |
| Working tree | clean | clean; `git diff --check` → 0 | match |
| Python executable | project venv | `.venv\Scripts\python.exe`, 3.12.13 | match |
| Loaded app path | this repository | `…\ClaimRoute-AI\app\streamlit_app.py` | match |
| `CLAIMROUTE_APP_MODE` | as needed | unset in Process/User/Machine scopes | n/a |
| Stale Streamlit process | none | none; no listener on port 8501 | clean |
| Streamlit cache reuse | none | no process was running; not a factor | clean |
| OCR stack | functional | paddle OK, tesseract 5.4.0 OK, official template loads (7 entries) | healthy |

### Configuration differences found

- `python` on `PATH` resolves to `C:\Python313\python.exe` (3.13.7), **not** the venv, and that
  interpreter has **none** of the project dependencies installed. `python -m streamlit run …`
  therefore only works with the venv activated. This did not cause the reported defect — a bare
  system-python run cannot start at all — but it is a real footgun. Prefer
  `.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py`.
- `engine/extract.py:26-27` opens `configs/*.yaml` via **relative** paths at import time, so the
  process must be started from the repository root.

### Resolution performed

No branch switch, fetch or environment repair was required. The behavioural divergence was not
a code-version difference at all: it was **document placement**. The monochrome adapter was
gated behind a `Group A`–`Group D` folder name, so the same bytes extracted correctly on one
machine and silently produced nothing on another. Routing is now content-based, so folder
naming no longer changes the result. See D-001.

### Safety note

The authorized development document was initially placed inside the repository working tree,
where it was **not ignored** and could have been committed by a `git add -A`. It has since been
**moved outside the repository** (content verified unchanged by SHA-256 before and after the
move), as `docs/submission/manual_testing_runbook.md` requires. The ignore rule for
`authorized-development/`, `*.tif` and `*.tiff` is retained in `.gitignore` as a standing guard
so a future local placement cannot be staged by accident.
