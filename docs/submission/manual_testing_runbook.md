# ClaimRoute AI manual testing runbook

Status: documentation-only guidance for `integrate/final-submission` at `829b2eb`.

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
Set-Location "D:\AI-Workspace\hackathon 2026\claims-engine"
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

### Actual upload support

| Input or behavior | Current support | Evidence from code |
|---|---|---|
| PNG | Yes | Uploader and service allow PNG |
| JPEG/JPG | Yes | Uploader and service allow JPEG/JPG |
| TIFF | Yes, single page only | TIFF allowed; service rejects page counts above one |
| Multipage TIFF in Streamlit | No | `MAX_PAGE_COUNT = 1` and validation rejects additional frames |
| PDF | No | PDF is absent from allowed extensions and formats |
| Organiser-data upload | No safe support | UI requires synthetic/no-PHI attestation; organiser documents are prohibited |
| Multiple-file upload | No | `file_uploader` is configured for one file |
| Batch folder upload | No | No folder selector, multi-file uploader, or batch UI path exists |

The local official adapter can decode multipage TIFFs, but that does not make multipage TIFF a
Streamlit feature.

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
| Process a single file by path | PARTIAL | `read_tiff_pages(path)` accepts a TIFF path and diagnostics open fixed paths, but there is no generic end-to-end single-file CLI |
| Process an entire folder | PARTIAL | Official benchmark consumes fixed `Group A`-`Group D` directories and synthetic harnesses consume a fixed generated-data layout; no arbitrary-folder CLI exists |
| Recursively discover files | NOT_IMPLEMENTED | Official discovery uses one-level `iterdir`; synthetic evaluation uses split IDs and fixed paths; no `rglob` ingestion path exists |
| Multipage TIFF page extraction | IMPLEMENTED_AND_TESTED | `read_tiff_pages()` copies every frame; `test_tiff_reader_decodes_all_frames_without_retaining_file_handle` covers three frames |
| Resumable batch processing | IMPLEMENTED_AND_TESTED | Day 8 and Day 11 use append-once JSONL keys and skip completed targets; both have resumability tests |
| Structured JSON output | IMPLEMENTED_AND_TESTED | UI final JSON and evaluator JSON/JSONL contracts have tests |
| Audit JSON output | IMPLEMENTED_AND_TESTED | `service.export_json(..., audit=True)` and UI download buttons are tested |
| CSV output | IMPLEMENTED_AND_TESTED | Day 8 summary CSV shape is tested; frozen Day 11 also emits CSV receipts |
| EDI output | NOT_IMPLEMENTED | NSF-320 and UB-192 are input parsers only; no 837/835 or other EDI writer exists |
| Folder watching or automatic ingestion | NOT_IMPLEMENTED | No watcher, polling loop, filesystem event handler, queue consumer, or new-file daemon exists |

Do not call fixed-folder batch evaluation a real-time folder watcher. It is an explicitly invoked,
finite evaluation pass.

## Demo-safe batch workflow

The closest existing automation is the Day 8 synthetic calibration harness. It discovers document
IDs from the calibration split, resolves their files in the fixed generated-data tree, skips
completed keys, processes pages, writes one JSON record per page/field to JSONL, and produces
aggregate JSON/CSV accuracy and cost summaries.

It does **not** accept an arbitrary folder argument and does **not** write one standalone JSON file
per document. A line in `day8_escalation_pages.jsonl` is the per-document/page JSON record.

Because its output paths are fixed and this branch already contains committed evidence, demonstrate
a fresh run only inside a disposable copy of the repository. In that copy, preserve or move aside
the copied Day 8 receipts, ensure the same synthetic `data/generated` tree is present, then run:

```powershell
uv run --python .venv\Scripts\python.exe python -m eval.day8_escalation --tiers clean noisy ugly --limit 6 --provider offline-oracle
uv run --python .venv\Scripts\python.exe python -m eval.day8_escalation --tiers clean noisy ugly --summarize --provider offline-oracle
```

Expected disposable-copy outputs:

```text
eval/results/day8_escalation_rows.jsonl
eval/results/day8_escalation_pages.jsonl
eval/results/day8_escalation_ledger.jsonl
eval/results/day8_escalation_summary.json
eval/results/day8_escalation_summary.csv
```

This is the safest existing demonstration of finite discovery, processing, resumability, structured
records, and aggregate accuracy/cost. It is not arbitrary-folder ingestion, per-document file
emission, or continuous watching. Do not use the frozen Day 11 runner for this demo.

## Expected output interpretation

- Final JSON: document metadata, selected operating-mode label, and normalized field output.
- Audit JSON: receipt metadata, operating-mode assumptions, funnel, cost bases, projections, token
  usage, latency, field candidates, validators, processing paths, governor decisions, and escalation
  records.
- Day 8 rows JSONL: one line per escalated field receipt.
- Day 8 pages JSONL: one line per processed document-tier page with accuracy, routing, cost, and
  latency aggregates.
- Day 8 ledger JSONL: append-only operation costs and timings.
- Day 8 summary JSON/CSV: per-tier and blended aggregate results.
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

### A batch command reports zero pages

The harness is resumable and skips keys already present in its JSONL outputs. This is expected in a
copy that still contains completed Day 8 receipts. Use a disposable copy prepared for the demo; do
not delete or truncate evidence in the submission branch.

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
