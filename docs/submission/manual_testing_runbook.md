# ClaimRoute AI manual testing runbook

Status: local workspace validated on `feat/local-intake-workspace` from baseline `1cc8d0b` on
2026-08-01.

This runbook separates safe synthetic and declared development work from protected organiser
inputs. It never requires a real provider, OpenRouter, a network call, or a holdout rerun.

## Safety boundary

Use the repository only from:

```text
D:\AI-Workspace\hackathon 2026\claims-engine
```

Treat the organiser dataset as local, read-only input:

```text
D:\AI-Workspace\hackathon 2026\Images & Output
```

Do not:

- open, preview, copy, hash, OCR, upload, or otherwise access Tier A holdout documents;
- execute the consumed Tier C holdout runner;
- run the organiser-wide benchmark command, because it has no tier filter and would touch Tier A
  and Tier C protected inputs;
- upload any organiser document to Streamlit, including a local instance used for a public demo;
- copy organiser TIFFs, crops, OCR text, fixed-width records, or extracted values into Git;
- configure a live provider or pass any provider other than `offline-oracle` to a synthetic harness;
- edit `eval/frozen/`, official receipts, manifests, templates, policies, thresholds, validators,
  evaluators, or holdout artifacts.

Aggregate counts and correctness booleans in committed receipts are safe evidence. Raw organiser
field values and source filenames are not.

## Prerequisites

Open PowerShell and establish the repository state:

```powershell
Set-Location "<repository-root>"
git status --short --branch
git branch --show-current
git log --oneline -8
```

Expected branch: `integrate/final-submission`. Existing untracked `submission/` and `tmp/` content
may be present; do not delete or stage it.

If the checked-in virtual environment is unavailable, create it and install the locked
requirements with `uv`:

```powershell
uv venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Safe contract tests (synthetic/masked fixtures only):

```powershell
uv run --python .venv\Scripts\python.exe python -m pytest tests\test_day10.py tests\test_day11_ui.py tests\test_official_dataset.py tests\test_day8.py -q
```

These tests do not read the organiser folder. They cover upload validation, UI workflows, final and
audit JSON separation, multipage TIFF decoding, Tier B selection logic, structured output, and
resumable synthetic batch receipts.

Local-workspace focused tests:

```powershell
uv run --python .venv\Scripts\python.exe python -m pytest tests\test_local_intake.py tests\test_local_workspace.py tests\test_day10.py tests\test_day11_ui.py tests\test_official_dataset.py -q
```

Full regression suite:

```powershell
uv run --python .venv\Scripts\python.exe python -m pytest -q
```

Validated result: `233 passed, 1 skipped`. The skip is the Windows symbolic-link test when link
creation privileges are unavailable; traversal still uses `followlinks=False`.

## Manual validation receipt

The receipt below records what was executed from the submission branch. `AppTest` means the
repository's installed Streamlit test runtime rendered and interacted with the real app module; it
does not mean a frozen evaluator was rerun. No extracted field values were printed or retained.

Validation commands used:

```powershell
uv run --python .venv\Scripts\python.exe python -m pytest tests\test_day10.py tests\test_day11_ui.py tests\test_official_dataset.py tests\test_day8.py -q
```

Result: `39 passed in 61.27s`.

The three-tier UI pass used `streamlit.testing.v1.AppTest` against `app/streamlit_app.py`, selected
the named bundled example in each tier, clicked **Run extraction**, parsed the final and audit JSON
payloads, and asserted the visible tabs, download controls, dashboard headings, and frozen-evidence
warning. The local launch command was separately started on port `8511`; `/_stcore/health`
returned HTTP `200` with body `ok`, after which the process was stopped.

| Test | Exact input | Command or UI steps | Expected result | Actual result | Status | Output path | Warning | Demo screenshot needed |
|---|---|---|---|---|---|---|---|---|
| Streamlit clean workflow | Bundled synthetic `cms1500_42_0000 / clean` | Start Streamlit; choose bundled sample and Balanced; click **Run extraction**. Validation used the equivalent `AppTest` selection and click. | Five result tabs and a completed synthetic receipt | No UI exception; 46 fields; five tabs; two download controls | PASS | Session receipt; optional browser Downloads | Screenshot-safe mode must remain on | Yes: Results plus safe-data banner |
| Streamlit noisy workflow | Bundled synthetic `cms1500_42_0000 / noisy` | Same steps with the noisy selector | Fresh degraded-tier receipt | No UI exception; 46 fields; five tabs; two download controls | PASS | Session receipt; optional browser Downloads | Offline-oracle usage estimates may be nonzero; they are not external calls | Yes: Results or field evidence |
| Streamlit ugly workflow | Bundled synthetic `cms1500_42_0000 / ugly` | Same steps with the ugly selector | Fresh difficult-tier receipt | No UI exception; 46 fields; five tabs; two download controls | PASS | Session receipt; optional browser Downloads | Routing may differ with local OCR; do not overwrite frozen evidence | Yes: routing/evidence path |
| Final JSON download contract | Any of the three completed bundled runs | Click **Download final JSON**; validation parsed the exact payload supplied to that control | Valid JSON with `document`, `fields`, and `operating_mode` only | Control present on all three runs; payload parsed with exactly those top-level keys | PASS | Browser-configured Downloads folder; `*-final.json` | Contains synthetic values; do not treat it as official evidence | No; show the button, not file contents |
| Audit JSON download contract | Any of the three completed bundled runs | Click **Download audit JSON**; validation parsed the exact payload supplied to that control | Audit sections present; duplicate `final_output` absent | Control present on all three runs; required sections present and duplicate absent | PASS | Browser-configured Downloads folder; `*-audit.json` | Keep exported synthetic values out of official evidence | No; show the button, not file contents |
| Accuracy dashboard | Same three completed runs | Open **Operating modes** and **Benchmark** | Accuracy tables/frontier and frozen-evidence boundary are visible | `Accuracy-cost frontier` rendered and frozen synthetic warning appeared on all runs | PASS | Rendered UI only; data comes from committed summaries | Not official or real-claim accuracy | Yes: Benchmark with warning visible |
| Cost dashboard | Same three completed runs | Open **Cost & performance** | Measured local/API and projected API/automated bases remain separated | Dashboard rendered on all runs; local/measured bases were `MEASURED`, forecasts `PROJECTED` | PASS | Rendered UI only; audit JSON contains cost detail | Noisy/ugly may record offline-oracle token estimates | Yes: cost cards with basis badges |
| Supported raster uploads | In-memory 12x12 no-PHI synthetic PNG, JPEG, and one-page TIFF | Call the existing `service.inspect_upload(..., synthetic_confirmed=True)` contract | All three supported formats accepted as one page | PNG, JPEG, and TIFF accepted; detected format and one page matched | PASS | Console only; temporary decoder storage self-deletes | UI still requires the synthetic/no-PHI checkbox and 10 MB maximum | No |
| PDF rejection | In-memory placeholder named `synthetic.pdf` | Pass to the existing upload validator | Rejected before decoding as unsupported | Rejected with the supported-type guidance | PASS | Console only | PDF is not an accepted upload type | No |
| Multipage TIFF boundary | In-memory three-frame no-PHI synthetic TIFF | Pass to the Streamlit upload validator, then the official adapter decoder | UI rejects three pages; adapter returns three decoded frames | UI reported the one-page limit; adapter decoded three RGB pages | PASS | Console only | Adapter capability does not make multipage TIFF a UI feature | No |
| Existing fixed-folder batch contract | Synthetic fixtures exercised by `tests/test_day8.py` | Run the focused pytest command above | Filtering, limits, resume keys, JSONL, JSON, and CSV behavior pass | All Day 8 contract tests passed within the 39-test run | PASS | Pytest console; test outputs use temporary paths | This is fixed-tree finite evaluation, not arbitrary-folder ingestion or watching | No |
| Tier A control | Manifest-declared development subset; protected holdout remains unopened | Inspect runner and split contract only; allowed command is in the A/B/C/D matrix below | Development-only command identified; holdout has no authorized command | Boundary verified from source; development evaluator not run; holdout documents not accessed | PASS | None from this validation | Never resolve or open holdout entries | No |
| Tier B control | Masked selection fixtures and committed aggregate receipt | Run focused pytest; parse only `per_tier.B` presence read-only | Selection/attachment contracts pass; receipt remains readable | Tests passed and Tier B committed section parsed | PASS | Pytest console; committed receipt unchanged | No Tier-B-only official runner exists | No |
| Tier C control | Frozen aggregate receipt only | Parse the frozen receipt fields read-only; do not invoke the holdout module | Existing receipt readable with external-call field; no rerun | Receipt parsed; no Tier C document or holdout runner accessed | PASS | `eval/results/official_ub04_holdout_summary.json` unchanged | Consumed holdout must never be rerun | No |
| Tier D control | Committed aggregate receipt only | Parse only `per_tier.D` presence read-only | Existing limited Tier D aggregate remains readable | Tier D committed section parsed; no fresh official evaluator run | PASS | `eval/official/results/official_sample_summary.json` unchanged | No split or Tier-D-only development command exists | No |
| Synthetic automated folder demo | Temporary folder containing converted bundled synthetic files | Start `local_workspace`; scan folder; select files; process; download JSON/CSV | Finite recursive discovery, processing, continue-on-error, and summary | Four documents/five pages completed; corrupt file isolated; exports parsed | PASS | Browser downloads only; temporary proof folder auto-deleted | Not a watcher; keep demo inputs synthetic | Yes: inventory, queue, and summary |
| Visual browser capture during this validation | Local Streamlit app only | Connect the integrated validation browser | Interactive screenshots can be captured | Browser runtime exited because a user-level Node ESM setting conflicts with its bootstrap; app health and `AppTest` remained successful | BLOCKED | None | Configuration issue in validation tooling, not ClaimRoute | Yes: capture manually before demo |

No ClaimRoute test failed. The remaining `BLOCKED` row affects only the integrated validation
browser bootstrap and is a tooling configuration issue, not an application defect.

### Local workspace validation receipt

| Test | Exact input | Expected result | Actual result | Status | Output/warning |
|---|---|---|---|---|---|
| Single PNG | Bundled no-PHI clean synthetic page | One document/page completes locally | Completed; zero external calls | PASS | In-memory result; local download available |
| Single TIFF | CCITT Group 4 conversion of the bundled synthetic page | TIFF signature detected and one page processed | Detected `TIFF`, one page, completed | PASS | No extension trust |
| Multipage TIFF | Two-frame CCITT conversion of the bundled synthetic page | Both pages decode and process | Two pages completed | PASS | UI page limit defaults to 100 in local mode |
| PDF | One-page PDF rendered from the bundled synthetic page | PDF rasterizes and processes through OCR | One page completed | PASS | Raster OCR only; no native text extraction claim |
| Numeric extension | Byte-for-byte TIFF content named with `.001` | TIFF accepted by signature without rename | Detected as TIFF claim document and completed | PASS | Duplicate content is processed once per batch |
| Mixed inventory | PNG, TIFF, multipage TIFF, PDF, numeric TIFF, generated expected JSON, synthetic specification, corrupt TIFF | Every file receives one role/status before processing | Claim, expected-output, specification, duplicate, and error states displayed correctly | PASS | Temporary directory auto-deleted |
| Continue on error | Corrupt TIFF plus valid documents | Corrupt item fails; later items continue | One failed; four succeeded/five pages completed | PASS | Decoder error is value-free |
| Dataset evaluation | Generated expected JSON matching the bundled PNG | Ground truth enters after extraction; safe accuracy receipt emitted | 44/44 fields and 21/21 critical fields; stage labelled `post_extraction_only` | PASS | Synthetic proof only |
| JSON/CSV exports | Same mixed batch | Both exports parse and omit absolute paths/private linkage text | Valid JSON, eight CSV rows, absolute path excluded | PASS | Raw synthetic fields remain local |
| Approved organiser development inventory | Three Tier A and two Tier C manifest-declared development containers only | Numeric extensions recognized as TIFF claims; hashes match | Five/five recognized; hashes matched; five pages | PASS | Holdout containers opened: zero; filenames/values not recorded |

The first fixture-generation attempt used RGB pixels with CCITT Group 4 and failed before
ClaimRoute ran. Recreating the synthetic fixture as 1-bit pixels resolved it. Classification:
fixture-generation user error, not an application defect.

## Localhost workspace workflow

Start the local workspace in PowerShell:

```powershell
Set-Location "<repository-root>"
$env:CLAIMROUTE_APP_MODE = "local_workspace"
uv run --python .venv\Scripts\python.exe python -m streamlit run app\streamlit_app.py
```

Open `http://localhost:8501`.

1. Choose **Process Documents** when no ground truth is present, or **Evaluate Dataset** when the
   inventory contains generated/authorized expected output.
2. Choose **Single file**, **Multiple files**, or **Local folder**.
3. For a folder, enter its absolute local path and click **Scan folder**. The path control exists
   only in `local_workspace` mode.
4. Review role, detected format, pages, status, group, and warning before processing.
5. Select all or a subset under **Files included in this run**.
6. Click **Process selected files**. One corrupt document does not stop later documents.
7. Inspect the queue, document result, validations, retries/governor, cost/latency, and summary.
8. Download document or batch JSON/CSV.

Expected-output and specification files are never sent through OCR. Evaluation parsing, linkage,
normalization, and comparison start only after document extraction completes. External escalation
is disabled. Do not expose this mode through a public URL.

## Testing matrix

| Test name | Purpose | Safe input | Class | Exact command or action | Expected output | Expected result | Rerun allowed | Risk or warning |
|---|---|---|---|---|---|---|---|---|
| Streamlit clean | Exercise the normal local path | Bundled `cms1500_42_0000 / clean` | Synthetic | Start Streamlit with the command below; select the sample; click **Run extraction** | Browser receipt; optional downloaded `*-final.json` and `*-audit.json` | Results, evidence, cost, modes, and benchmark tabs; clean receipt shows local resolution | Yes | Keep the sample bundled and synthetic; do not upload organiser data |
| Streamlit noisy | Exercise a degraded but safe page | Bundled `cms1500_42_0000 / noisy` | Synthetic | Same UI workflow | Browser receipt and optional downloads | A fresh receipt for the noisy tier; exact routing can vary with the local OCR environment | Yes | Do not present a live result as the frozen benchmark |
| Streamlit ugly | Exercise retry/escalation evidence | Bundled `cms1500_42_0000 / ugly` | Synthetic | Same UI workflow | Browser receipt and optional downloads | Retry/escalation path may appear; any escalation is the deterministic offline oracle | Yes | No real provider is called; do not call the oracle provider evidence |
| Uploaded synthetic raster | Verify local-only user upload | A known synthetic PNG, JPEG, or single-page TIFF under `data\generated\` | Synthetic | Select **Upload local document**, attest synthetic/no-PHI, choose one file, run | Browser receipt and optional downloads | Upload passes validation and runs with escalation disabled | Yes | Maximum 10 MB and one page; upload tier is treated as `clean` |
| Tier A development | Re-evaluate only the immutable three-document development subset | Manifest-selected development entries in organiser `Group A` | Official development | `uv run --python .venv\Scripts\python.exe python -m eval.official.diagnostics.run_full_development` | `eval/official/diagnostics/full_development_safe.json` | PHI-safe aggregate/boolean development receipt; holdout count remains zero | Yes, locally | Script has hard-coded development selection and local organiser root; output is Git-ignored |
| Tier A holdout | Protect reserved documents | `holdout` entries in `eval/official/splits/tier_a_split_v1.json` | Holdout | No execution command is authorized | None | No file access and no new receipt | No | Do not use the organiser-wide benchmark runner; it is not split-aware |
| Tier B selection contract | Verify claim-page selection and attachment rejection without organiser data | Synthetic text fixtures in `tests/test_official_dataset.py` | Synthetic test | `uv run --python .venv\Scripts\python.exe python -m pytest tests\test_official_dataset.py -q` | Console test result only | Selection isolates one claim page, rejects attachments, and abstains on ties | Yes | This verifies logic, not a new official-data measurement |
| Tier B frozen evidence | Inspect the already-recorded organiser result | `eval/official/results/official_sample_summary.json` | Official frozen evidence | `$r = Get-Content eval\official\results\official_sample_summary.json -Raw | ConvertFrom-Json; $r.per_tier.B | ConvertTo-Json -Depth 6` | Console only | Displays committed page-selection and attachment-rejection aggregates | Yes, read-only | No Tier B development split or Tier-B-only runner exists |
| Tier C development proof | Re-evaluate only the two immutable development documents using the narrow proof | Manifest-selected development entries in organiser `Group C` | Official development | `uv run --python .venv\Scripts\python.exe python -m eval.official.diagnostics.run_ub04_five_field_proof` | `eval/official/diagnostics/ub04_five_field_proof_safe.json` | PHI-safe proof receipt; holdout access remains zero | Yes, locally | Use the narrow proof; the expansion script overwrites tracked development evidence and is not the safe manual command |
| Tier C frozen evidence | Inspect the consumed one-time receipt | `eval/results/official_ub04_holdout_summary.json` | Consumed holdout evidence | `$r = Get-Content eval\results\official_ub04_holdout_summary.json -Raw | ConvertFrom-Json; $r | Select-Object result_label,split_id,documents,primary_correct,primary_denominator,extended_correct,extended_denominator,external_provider_calls | Format-List` | Console only | Shows the frozen aggregate result and zero external calls | Yes, read-only | Never invoke the Tier C holdout module; missing telemetry must remain unavailable |
| Tier D routing contract | Verify that Tier D routes all supplied pages as unstructured | `eval/official/pages.py` and committed safe receipt | Official frozen evidence | `$r = Get-Content eval\official\results\official_sample_summary.json -Raw | ConvertFrom-Json; $r.per_tier.D | ConvertTo-Json -Depth 5` | Console only | Displays the committed limited Tier D aggregate | Yes, read-only | No Tier D split, development-only runner, or confirmed scoring denominator exists |
| Synthetic resumable batch | Process several calibration documents through the existing batch harness | Fixed synthetic `data/generated/<form>/<tier>/images` tree plus ground truth | Synthetic development | In a disposable repository copy: `uv run --python .venv\Scripts\python.exe python -m eval.day8_escalation --tiers clean noisy ugly --limit 6 --provider offline-oracle` | `eval/results/day8_escalation_rows.jsonl`, `day8_escalation_pages.jsonl`, and `day8_escalation_ledger.jsonl` in that copy | At most six unfinished document-tier pages are discovered and processed; completed keys are skipped | Yes, in a disposable copy | Output paths are fixed; do not run a fresh demo over the committed receipts in this branch |
| Synthetic batch summary | Generate aggregate accuracy and cost from the prior batch | Same disposable-copy receipts | Synthetic development | `uv run --python .venv\Scripts\python.exe python -m eval.day8_escalation --tiers clean noisy ugly --summarize --provider offline-oracle` | `eval/results/day8_escalation_summary.json` and `.csv` in that copy | Per-tier and blended accuracy, routing, cost, and latency summary | Yes, after batch rows exist | Offline-oracle cost is projected; measured external spend remains zero |
| Final/audit JSON | Verify the two UI export contracts | Any bundled synthetic UI run | Synthetic | Click **Download final JSON**, then **Download audit JSON** | Browser download folder; names end in `-final.json` and `-audit.json` | Both files parse as JSON; final is normalized output, audit carries funnel/evidence/cost | Yes | Downloads contain synthetic values; keep them out of organiser evidence |

## Streamlit synthetic workflow

Start the local application:

```powershell
Set-Location "D:\AI-Workspace\hackathon 2026\claims-engine"
uv run --python .venv\Scripts\python.exe python -m streamlit run app\streamlit_app.py
```

Open `http://localhost:8501`. Leave **Screenshot-safe mode** enabled until the selected bundled
sample is confirmed.

### Clean, noisy, and ugly runs

For each tier:

1. Set **Document source** to **Bundled synthetic example**.
2. Keep **Operating mode** at **Balanced**.
3. Select `cms1500_42_0000 / clean`, then click **Run extraction**.
4. Inspect **Results**, **Field evidence**, and **Cost & performance**.
5. Repeat with `cms1500_42_0000 / noisy`.
6. Repeat with `cms1500_42_0000 / ugly`.
7. Changing the selected file produces a new run key. Clicking **Run extraction** twice without
   changing file, mode, source, or tier reuses the current session receipt.

The clean and ugly paths are covered by `tests/test_day11_ui.py`. Noisy is available through the
same bundled selector and service path, but does not have a dedicated AppTest case; classify that
specific manual UI run as `IMPLEMENTED_NOT_TESTED` until it is performed.

### Final and audit downloads

After a run completes:

1. In **Results**, click **Download final JSON**.
2. Open the downloaded file and confirm top-level `document`, `operating_mode`, and `fields` keys.
3. Click **Download audit JSON**.
4. Confirm the audit contains `document`, `operating_mode`, `funnel`, `costs`, `projections`,
   `usage`, `latency_ms`, and per-field evidence, and does not contain the duplicate `final_output`
   object.
5. Confirm **Cost & performance** distinguishes `MEASURED` local/API cost from `PROJECTED` API and
   automated cost. The caption must say no real provider token usage was recorded when usage is zero.
6. In **Benchmark**, retain the warning that the display is the frozen synthetic benchmark with an
   offline-oracle projection, not official or real-claim evidence.

### Actual upload support by environment mode

| Input or behavior | Public/synthetic mode | Local workspace mode |
|---|---|---|
| PNG | Yes, attested synthetic only | Yes, content-detected |
| JPEG/JPG | Yes, attested synthetic only | Yes, content-detected |
| TIFF | Yes, one page | Yes, all frames up to configured limit |
| Multipage TIFF | Rejected by one-page public limit | Yes |
| PDF | No | Yes, rasterized locally then OCRed |
| Numeric extension TIFF/CCITT | No | Yes, accepted by TIFF signature |
| Organiser data | Prohibited | Authorized development/local use only |
| Multiple-file upload | No | Yes |
| Recursive folder scan | No | Yes, symbolic links not followed |
| Dataset evaluation | Frozen displays only | Yes, post-extraction comparison |

Public mode intentionally remains the restricted single-file demo. Local capability must not be
used to justify uploading organiser data to a public deployment.

## Official A/B/C/D controls

### Tier A

- Safe development scope: only the three entries under `development` in
  `eval/official/splits/tier_a_split_v1.json`.
- Safe evaluator: `eval.official.diagnostics.run_full_development`.
- Safe output: Git-ignored `eval/official/diagnostics/full_development_safe.json`.
- Exact boundary: the runner scans the shared Group A fixed-width output file to locate record
  delimiters, but retains and parses only the three manifest-selected development record blocks;
  it opens only the three development images.
- Protected scope: every `holdout` entry in the manifest. Do not resolve those entries to source
  filenames and do not open the associated documents.
- The candidate freeze manifest does not authorize a holdout run.

### Tier B

- There is no Tier B split manifest and no tier-only command.
- `select_claim_pages()` chooses a unique CMS-1500-like page only when its OCR marker score is at
  least two and uniquely highest. All other pages are attachments; ties abstain.
- The organiser-wide frozen receipt already records the official result. Inspect it read-only.
- The organiser-wide `eval.official.benchmark run` path is forbidden because it iterates A, B, C,
  and D and has no `--tier` or split option.

### Tier C

- Safe development scope: only the two entries under `development` in
  `eval/official/splits/tier_c_split_v1.json`.
- Safe narrow evaluator: `eval.official.diagnostics.run_ub04_five_field_proof`.
- Safe output: Git-ignored `eval/official/diagnostics/ub04_five_field_proof_safe.json`.
- The expanded development script writes fixed tracked receipt paths; do not use it for a casual
  manual check on the submission branch.
- The one-time holdout is consumed. Inspect only `eval/results/official_ub04_holdout_summary.json`
  or `docs/evaluation/official_ub04_holdout.md`. Do not attempt to reconstruct unavailable metrics.

### Tier D

- Tier D sends every decoded page through the unstructured path and applies conservative label
  extraction.
- There is no development/holdout split, no Tier-D-only CLI, and no confirmed official required-field
  denominator.
- Use the committed aggregate receipt for official evidence. A fresh official Tier D run is not
  authorized because the only runner also accesses protected tiers.
- Do not describe the limited label extraction as complete Tier D automation.

## Automation capability matrix

Classification is based on current code and tests, not intended architecture.

| Capability | Classification | Exact boundary |
|---|---|---|
| Process a single file | IMPLEMENTED_AND_TESTED | Local UI accepts one content-detected file and exports document JSON/CSV |
| Process multiple files | IMPLEMENTED_AND_TESTED | Local UI accepts multiple files and runs a deterministic batch |
| Process an entire folder | IMPLEMENTED_AND_TESTED | Local-only path input inventories and processes a selected folder subset |
| Recursively discover files | IMPLEMENTED_AND_TESTED | `scan_folder()` traverses deterministically with symbolic-link following disabled |
| Multipage TIFF page extraction | IMPLEMENTED_AND_TESTED | `read_tiff_pages()` copies every frame; `test_tiff_reader_decodes_all_frames_without_retaining_file_handle` covers three frames |
| PDF page extraction | IMPLEMENTED_AND_TESTED | `pypdfium2` rasterizes every page; both scanned and text PDFs use OCR |
| Resumable batch processing | PARTIAL | Completed results can be reused in-session; there is no persistent job store |
| Structured JSON output | IMPLEMENTED_AND_TESTED | Document and batch JSON contracts have tests |
| Audit JSON output | IMPLEMENTED_AND_TESTED | `service.export_json(..., audit=True)` and UI download buttons are tested |
| CSV output | IMPLEMENTED_AND_TESTED | Document-field and batch-summary CSV downloads are tested |
| EDI output | NOT_IMPLEMENTED | NSF-320 and UB-192 are input parsers only; no 837/835 or other EDI writer exists |
| Folder watching or automatic ingestion | NOT_IMPLEMENTED | No watcher, polling loop, filesystem event handler, queue consumer, or new-file daemon exists |

Do not call fixed-folder batch evaluation a real-time folder watcher. It is an explicitly invoked,
finite evaluation pass.

## Demo-safe batch workflow

Use the localhost workspace rather than an evaluator harness:

1. Prepare a folder outside Git containing several generated/synthetic claims and, optionally,
   their generated expected JSON.
2. Start `local_workspace` mode with the command above.
3. Choose **Local folder**, scan, and show the mixed inventory.
4. Select the claim documents and expected JSON only.
5. Use **Process Documents** first to prove ground-truth independence.
6. Repeat with **Evaluate Dataset** to show post-extraction accuracy.
7. Show the queue, aggregate pages/success/failure/unresolved/cost/throughput, and download JSON/CSV.

This path accepts an arbitrary local folder, processes a finite selected inventory, and retains no
raw files beyond the browser session. It is not continuous watching or automatic ingestion. Do not
use Day 8 or frozen Day 11 output paths for the demo.

## Expected output interpretation

- Final JSON: document metadata, selected operating-mode label, and normalized field output.
- Audit JSON: receipt metadata, operating-mode assumptions, funnel, cost bases, projections, token
  usage, latency, field candidates, validators, processing paths, governor decisions, and escalation
  records.
- Local document JSON/CSV: one selected document's structured fields and evidence summary.
- Local batch JSON/CSV: one row/result per inventory item plus aggregate status, accuracy when
  evaluated, unresolved fields, cost, latency, and throughput.
- Official safe receipts: opaque identifiers, field names, counts, booleans, timings, and aggregate
  costs only; no raw expected or OCR values.

## Troubleshooting

### Streamlit starts but no bundled samples appear

Confirm the synthetic tree exists:

```powershell
Get-ChildItem data\generated\*\*\images\*.png | Select-Object -First 5
```

If empty, do not generate data into the submission branch during a judged run. Use the committed
screenshot and frozen synthetic receipts, or prepare a disposable copy in advance.

### Upload is rejected

- Check the synthetic/no-PHI checkbox.
- Use PNG, JPEG/JPG, or a single-page TIFF.
- Keep the file at or below 10 MB.
- A multipage TIFF or PDF is expected to fail.

### Extraction differs from a published number

OCR candidates and latency may vary by workstation. Do not overwrite evidence or retune the
pipeline. Present the live run as a manual synthetic check and use committed frozen receipts for
submission claims.

### A local batch reports zero pages

Review the inventory roles and selected IDs. Expected output, specifications, attachments,
unsupported files, unknown files, and duplicate hashes are not processed as claim pages. A corrupt
container remains visible as a failed item while later documents continue.

### Official development command cannot find the organiser root

The development diagnostics use the exact local workspace root embedded in the existing scripts.
Confirm the organiser folder remains at the path stated in prerequisites. Do not edit the script to
point at a copied folder and do not place organiser files under the repository.

### Provider or network error appears

Stop. The approved paths require no live provider. Confirm the UI is using bundled synthetic data
or a synthetic upload, and that any synthetic batch explicitly uses `--provider offline-oracle`.

## What must not be run

- The consumed Tier C holdout module, under any confirmation value.
- The organiser-wide `eval.official.benchmark run` command.
- Any Day 11 `freeze`, `run`, or `summarize` action against `eval/frozen/`.
- Any live-provider Day 8 command, including OpenAI, Gemini, OpenRouter, or another external model.
- Any command that resolves Tier A holdout manifest entries to organiser source filenames.
- Any cleanup, regeneration, or overwrite targeting official receipts or frozen evidence.

Read-only inspection of committed summaries is allowed. Synthetic/masked tests and explicitly
declared development-only diagnostics are allowed as described above.
