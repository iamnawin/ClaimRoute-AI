
# ClaimRoute project memory

## Official CMS-1500 five-field development proof - 31 Jul 2026

- Official CMS-1500 (02-12) registration is separate from synthetic red-grid registration.
- Long horizontal rules establish vertical bounds and semantic row bands; vertical segments are
  detected inside those bands for horizontal bounds. Edge-touching scanner stripes are rejected.
- Only the three frozen Tier A development items were opened; holdout access remained zero.
- Boxes 3, 24F line 1, 24G line 1, 25, and 33a achieved 15/15 correct geometry, 15/15 visible
  values, and 15/15 normalized matches after 12 field-specific local retries.
- Primary accuracy was 4/15. Frozen governor results were 12 ACCEPT and 3 ESCALATE even though all
  normalized values matched; do not weaken governor thresholds to turn those into accepts.
- Measured proof latency was 55,691.535 ms, local cost $0.000773493, external calls zero.
- Repository evidence remains PHI-safe; local crops, overlays, OCR text, and organiser values stay
  under the ignored diagnostics path.

## Official organiser sample adapter - 30 Jul 2026

- The correct local dataset root is `D:\AI-Workspace\hackathon 2026\Images & Output`.
- Implemented `eval/official/` for read-only multipage TIFF ingestion, NSF 320 and UB 192 parsing,
  record linkage with abstention, ClaimRoute field mapping, normalization, Tier-B filtering,
  conservative Tier-D extraction, and PHI-safe aggregate evaluation.
- Full local run decoded 30 containers / 67 pages and parsed 30 records. Linkage was deterministic
  for 26 and abstained for four; no combined official score is valid.
- Tier B measured 4/4 claim-page selection and 15/15 attachment rejection on linked,
  page-evaluable items. All 21 input pages remain in its cost denominator.
- Exact official results were A 0/299, B 0/121, C 0/105, D 1/168. This exposes a real layout
  incompatibility: frozen synthetic templates use red-grid coordinates while official scans are
  1-bit legacy layouts. Never substitute the 99.716% frozen synthetic result.
- Local run was approximately $0.0000291/input page at the configured vCPU price and 28.32
  pages/minute; external calls/spend remained zero.
- Repository reports contain no OCR/expected values: only opaque source IDs, field names,
  booleans, counts, and timings. Source dataset is neither copied nor committed.
- Before authoritative scoring, obtain organiser crosswalk, Tier-D required fields, Tier-B page
  labels, blank-field rules, and UB Type-80 semantics; then declare a calibration/evaluation split
  before creating organiser-layout templates.

## Day 11 frozen submission audit - 30 Jul 2026

- Frozen anchor: `8324d600fa61ad7c6a57f7c70e3126232bd4e602`; architecture v1.2 and runtime
  thresholds/policies unchanged after results.
- Test boundary: 30 held-out synthetic documents x clean/noisy/ugly = 90 pages, 3,168 fields;
  zero calibration overlap, zero duplicate rows, official data excluded, zero external calls.
- Balanced blended: 99.716% field accuracy, 99.936% critical accuracy, 93.303% primary local
  resolution, 6.697% retry, 1.905% escalation, 1.813% human review.
- Cost: $0 measured API spend; $0.0000722/page measured local usage at configured price;
  $0.0000227/page projected oracle API; $0.0000949/page projected automated total.
- Prototype throughput: 9.200 pages/minute, 6.521-second mean, 5.269-second p50,
  10.825-second p95. This is not production evidence.
- Main limitation: ugly-tier escalated fields had zero governor-accepted resolution under the
  locked policy. Do not tune after freeze; report it and retain human review.
- Created frozen manifests/rows/pages/ledger/summaries/ablations/cost projections plus methodology,
  cost, throughput, licensing, security, judging, evidence, and claims documents.
- Streamlit benchmark source now reads the final frozen synthetic summary. Netlify remains a static
  project-status page only and must never accept official claims.
- Approved headline: "Balanced achieved 99.716% exact field accuracy on the frozen synthetic
  benchmark." Never convert this into a real-claims, real-provider, or production-scale claim.
- Next: final presentation and recorded synthetic demo; fix or disclose the degraded overlay's
  processed-coordinate offset before recording.

## Day 10 UI memory

Date: 30 Jul 2026
Status: COMPLETE
Architecture: v1.2 locked and unchanged

## Objective completed

Built the working ClaimRoute hackathon prototype UI around the existing extraction pipeline.
The application is a thin Streamlit layer that calls `engine.extract.run_page`; it does not
duplicate OCR, preprocessing, validation, governor, escalation, or benchmark logic.

## Framework and entry point

- Framework: Streamlit
- Application entry: `app/streamlit_app.py`
- Framework-neutral adapter: `app/service.py`
- Pipeline entry: `engine.extract.run_page`
- Default operating mode: Balanced
- Local URL: `http://localhost:8501`
- Startup command: `.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py`

## Files created

- `.streamlit/config.toml`: restrained teal Streamlit theme and accessible control colors
- `PRODUCT.md`: product register, users, purpose, safety principles, and accessibility direction
- `app/__init__.py`: application package marker
- `app/service.py`: upload validation, pipeline invocation, receipts, cost labeling, JSON export,
  overlay rendering, crop selection, temporary cleanup, and provider safety boundary
- `app/streamlit_app.py`: upload/select workflow, mode controls, processing journey, results,
  evidence, costs, modes, benchmark, and exports
- `tests/test_day10.py`: 11 application contract tests
- `docs/operations/local_app_runbook.md`: installation, startup, safety, limitations, and fallback
- `docs/demo_script.md`: five-minute judged-demo flow and evidence wording
- `docs/screenshots/day10_home.png`: screenshot-safe synthetic start screen

## Files modified

- `.gitignore`: allows the committed non-secret Streamlit theme configuration
- `requirements.txt`: adds `streamlit>=1.41`
- `README.md`: uv installation, corrected dataset command, app startup, supported input, safety,
  and Streamlit licensing
- `HANDOFF.md`: Day 10 status, manual receipts, validation, deployment limits, and next task
- `eval/results/day7_ledger.jsonl`: preserved regenerated synthetic Day 7 ledger evidence
- `eval/results/day7_rows.jsonl`: preserved regenerated synthetic Day 7 field evidence
- `docs/MEMORY.md`: this durable Day 10 receipt

## UI capabilities completed

- Bundled zero-PHI synthetic selection or local image upload
- Actual PNG, JPEG, or TIFF detection, with 10 MB and one-page limits
- Economy, Balanced, and Strict Accuracy selection, with Balanced as default
- Real extraction-pipeline invocation using the selected locked runtime preset
- Document metadata, pipeline journey, and actual resolution funnel
- Field values, confidence, criticality, source, decisions, validation, retries, escalation,
  latency, costs, bounding boxes, crops, candidates, and processing paths
- Measured and projected cost separation, token usage, latency, and scale projections
- Day 9 mode comparison and accuracy-cost frontier loaded from generated evidence
- Day 8 clean/noisy/ugly/blended synthetic benchmark loaded from generated evidence
- Final JSON and audit JSON exports, duplicate protection, and screenshot-safe mode

## Safety decisions

- Uploads always invoke `run_page(..., run_escalate=False)`.
- Only bundled synthetic documents may use the local deterministic `offline-oracle`.
- Real-provider mode is not exposed in the UI.
- Official PHI documents are not bundled and must not be used in a public deployment.
- Uploaded bytes are processed in memory; temporary ledgers are removed after the run.
- Extracted values are not written to application logs or echoed in user-facing errors.
- Offline-oracle and scale costs are PROJECTED; local and API spend are MEASURED.
- Mode thresholds are CONFIGURED ASSUMPTION.
- Day 9 replay calibration did not retune locked runtime thresholds.

## Verification evidence

- Day 10 focused tests: 11 passed
- Full suite: 75 passed, 0 failed
- Streamlit startup, clean, and ugly AppTests: 0 exceptions
- External API calls: 0
- Measured external API spend: $0

| Balanced synthetic run | Fields | Local accepts | Flags | Retries | Offline escalation | Human review | API calls avoided |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cms1500_42_0000 / clean` | 46 | 46 | 0 | 0 | 0 | 0 | 46 |
| `cms1500_42_0000 / ugly` | 46 | 32 | 11 | 3 | 1 | 1 | 45 |

## Known limitations

- Raster images only; PDF and multi-page processing are not implemented.
- The 120-second timeout is a post-run budget, not hard worker cancellation.
- Processed-coordinate boxes may look offset over heavily degraded original pixels.
- Uploaded documents remain local-only, so fields needing Tier 2 can remain unresolved.
- No authenticated human-review queue or override workflow exists in the demo.
- Official dataset role and image-to-record mapping remain unconfirmed.

## Deployment recommendation

Run locally or on an access-controlled demo machine with synthetic data. Do not deploy publicly
for official claims until authentication, retention, worker isolation, provider approval,
official mapping, and PHI governance are verified.

## Day 10 commits

- `04e1100` feat: build ClaimRoute demo application
- `017b278` test: validate Day 10 application workflow
- `7701e49` fix: polish ClaimRoute demo presentation
- `42d49c5` docs: add local demo runbook and update handoff

## Next exact task

Run the Day 11 frozen-test evaluation and submission-readiness audit without tuning thresholds or
using official data until its governance is confirmed.

## Public Netlify project status page

Date: 30 Jul 2026
Status: LIVE
URL: `https://claimrouteai.netlify.app/`

Netlify now publishes a static, zero-PHI project status page from `site/`. It shows the Day 10
prototype screenshot, verified test and cost evidence, the extraction route, a completed-work
checklist, the next task, and local Streamlit startup commands. The public page does not execute
the Python extraction engine or accept claim uploads because Netlify is a static host and the
working Streamlit prototype requires a Python application server.

Files created:

- `netlify.toml`: publishes `site/` and applies basic security and cache headers
- `site/index.html`: responsive, accessible project status page with the verified Day 10 evidence

Verification:

- HTML validation: passed with zero errors
- Local static server: HTTP 200
- Public Netlify URL: HTTP 200 with the expected page title
- Product screenshot asset: HTTP 200, `image/png`
- Security headers: `nosniff`, frame denial, strict referrer policy, and camera/microphone/location denial
- Deployment commit: `f42d8e2` (`feat: add Netlify project status site`)

---

claude-mem
89.0k

hackathon 2026


change
hackathon 2026

facts

narrative
Day-7 audit session completed with 5 commits ready to push
Fixed two defects, synchronized dependencies, documented decisions, and updated handoff documentation
#4560 • 7/30/2026, 2:45:26 PM
change
hackathon 2026

facts

narrative
HANDOFF.md committed documenting Day-7 completion
Session handoff committed with test evidence, baseline comparison, and Day-8 resume instructions
#4559 • 7/30/2026, 2:44:54 PM
change
hackathon 2026

facts

narrative
Full test suite verified passing after Day-7 audit fixes
All 46 tests pass: 35 non-day2 in 48.34s, 11 day2 in 15.25s
#4558 • 7/30/2026, 2:44:28 PM
change
hackathon 2026

facts

narrative
CLAUDE.md environment gotchas updated with accurate runtime details
Corrected pytest timing, clarified dependencies, and added Word file-locking workaround
#4557 • 7/30/2026, 2:42:59 PM
change
hackathon 2026

facts

narrative
CLAUDE.md updated with Day-7 audit findings as hard rules
Added bbox-ink guardrail and Tesseract PSM decisions to prevent future re-litigation
#4556 • 7/30/2026, 2:42:42 PM
change
hackathon 2026

facts

narrative
Comprehensive HANDOFF.md written documenting Day-7 completion
Session handoff captures baseline audit, defect analysis, fixes, and next steps for Day-8
#4555 • 7/30/2026, 2:42:20 PM
change
hackathon 2026

facts

narrative
Documented Day-7 audit decisions with supporting evidence
Committed assumptions log updates and clean tier evaluation results showing 99.16% accuracy
#4554 • 7/30/2026, 2:41:22 PM
discovery
hackathon 2026

facts

narrative
Day-7 cost breakdown shows extremely efficient processing
Total cost $0.000115 per page with OCR and retry operations dominating expenses
#4553 • 7/30/2026, 2:40:54 PM
discovery
hackathon 2026

facts

narrative
Day-7 clean tier performance metrics
Achieved 99.16% accuracy with 60.89% fields using retry rung, only 3.21% requiring escalation
#4552 • 7/30/2026, 2:39:50 PM
change
hackathon 2026

facts

narrative
Day-7 funnel processing completed for clean tier dataset
Finished processing remaining 8 documents, completing full clean tier evaluation
#4551 • 7/30/2026, 2:39:28 PM
change
hackathon 2026

facts

narrative
Day-7 evaluation funnel executed on clean tier
Processed 12 documents through clean tier generating results and ledger output
#4550 • 7/30/2026, 2:37:49 PM
discovery
hackathon 2026

facts

narrative
Two critical Day-7 audit findings documented
Fixed bbox-ink guardrail contrast measurement and Tesseract PSM mode for field crops
#4549 • 7/30/2026, 2:35:05 PM
discovery
hackathon 2026

facts

narrative
Claims-engine design assumptions and gotchas documented
Ten critical learnings captured covering OCR normalization, validation costs, and quality metrics
#4548 • 7/30/2026, 2:34:38 PM
change
hackathon 2026

facts

narrative
Synchronized runtime dependencies and updated license documentation
Fixed missing dependencies in requirements.txt and enhanced license tracking with metadata
#4547 • 7/30/2026, 2:34:25 PM
discovery
hackathon 2026

facts

narrative
Claims-engine module structure and dependencies verified
All runtime imports successfully resolve including engine modules and data factory components
#4546 • 7/30/2026, 2:34:06 PM
discovery
hackathon 2026

facts

narrative
Python environment validated for claims-engine project
Successfully installed all dependencies from requirements.txt in clean virtual environment
#4545 • 7/30/2026, 2:33:32 PM
change
hackathon 2026

facts

narrative
Project initialization requested
User invoked /init to create CLAUDE.md documentation file for the codebase
#4544 • 7/30/2026, 2:33:15 PM
change
hackathon 2026

facts

narrative
Comprehensive licensing documentation added to README
Expanded license table includes all 10 dependencies with versions, purposes, scopes, and GitHub sources
#4543 • 7/30/2026, 2:28:07 PM
change
hackathon 2026

facts

narrative
Expanded requirements.txt with OCR dependencies and installation instructions
Added numpy, pytesseract, rapidocr-onnxruntime with minimum versions and documented Tesseract binary installation process
#4542 • 7/30/2026, 2:27:43 PM
discovery
hackathon 2026

facts

narrative
Minimal requirements.txt specifies only three core dependencies
Project declares pillow, faker, and pyyaml with minimum versions; OCR engines installed separately
#4541 • 7/30/2026, 2:27:29 PM
discovery
hackathon 2026

facts

narrative
Pillow uses MIT-CMU license and Tesseract 5.4.0 installed
Pillow 12.1.1 carries permissive MIT-CMU license; Tesseract 5.4.0 with leptonica 1.84.1 provides OCR backend
#4540 • 7/30/2026, 2:27:15 PM
discovery
hackathon 2026

facts

narrative
Project dependencies use permissive open-source licenses
All installed packages carry MIT, Apache 2.0, or BSD licenses compatible with commercial use
#4539 • 7/30/2026, 2:26:32 PM
discovery
hackathon 2026

facts

narrative
Vision engines use standard library urllib without SDK dependencies
OpenAI and Gemini integrations implemented with raw HTTP requests via urllib, avoiding vendor SDKs
#4538 • 7/30/2026, 2:26:31 PM
discovery
hackathon 2026

facts

narrative
Project dependencies enumerated from import statements
Claims engine uses minimal external dependencies: PIL, pytesseract, rapidocr, numpy, faker, pytest, yaml
#4537 • 7/30/2026, 2:26:17 PM
bugfix
hackathon 2026

facts

narrative
Retry rung PSM 6 fix committed with test coverage
Field crop block segmentation resolves all 7 single-character fields, improving accuracy from 37/44 to 44/44
#4536 • 7/30/2026, 2:25:52 PM
bugfix
hackathon 2026

facts

narrative
Bbox-ink guardrail now measures contrast relative to local background
Fixed false positives from absolute darkness threshold by comparing crops against their own 90th-percentile background
#4535 • 7/30/2026, 2:25:30 PM
discovery
hackathon 2026

facts

narrative
Tesseract binary resolution works without PATH export
Test suite passes without manual PATH configuration confirming cross-platform binary detection
#4534 • 7/30/2026, 2:24:19 PM
bugfix
hackathon 2026

facts

narrative
Full test suite passes after PSM and retry rung fixes
All 46 tests pass including day 2 baseline and day 5 single-character field extraction
#4533 • 7/30/2026, 2:23:13 PM
bugfix
hackathon 2026

facts

narrative
Perfect accuracy achieved on CMS-1500 single-character field extraction
Retry rung with PSM block segmentation achieves 100% accuracy on all 44 fields including previously failing checkboxes
#4532 • 7/30/2026, 2:20:46 PM
bugfix
hackathon 2026

facts

narrative
PSM fix resolves single-character field extraction tests
Day 5 test suite now passes after implementing block segmentation for Tesseract retry rung
#4531 • 7/30/2026, 2:20:24 PM
bugfix
hackathon 2026

facts

narrative
Fixed retry rung to use block segmentation for single-character fields
Retry OCR now forces PSM 6 for Tesseract to correctly extract isolated characters
#4530 • 7/30/2026, 2:11:29 PM
feature
hackathon 2026

facts

narrative
Added configurable PSM mode support to TesseractEngine
Extract method now accepts optional PSM parameter to override default page segmentation behavior
#4529 • 7/30/2026, 2:11:21 PM
discovery
hackathon 2026

facts

narrative
Tesseract binary resolution and adapter implementation
TesseractEngine auto-detects binary location across Windows and Unix systems with environment override support
#4528 • 7/30/2026, 2:11:09 PM
discovery
hackathon 2026

facts

narrative
Tesseract PSM mode testing on single-character fields
Evaluated different page segmentation modes for extracting checkbox and single-digit values from CMS-1500 forms
#4527 • 7/30/2026, 2:10:47 PM
discovery
hackathon 2026

facts

narrative
Project initialization requested
User invoked /init to create initial CLAUDE.md documentation file
#4526 • 7/30/2026, 2:10:28 PM
bugfix
hackathon 2026

facts

narrative
Guardrail fix resolves all Day 2 and Day 3 test failures
11 Day 2 tests passed (was 9/2 pass/fail); 7 Day 3 tests passed (including preprocessing bbox survival)
#4525 • 7/30/2026, 1:42:01 PM
bugfix
hackathon 2026

facts

narrative
Fixed bbox ink guardrail to use relative-contrast detection
Replaced absolute threshold-128 test with relative background-minus-25 contrast, eliminating false failures on photometrically transformed images
#4524 • 7/30/2026, 1:41:00 PM
discovery
hackathon 2026

facts

narrative
Relative-contrast ink test correctly validates bbox accuracy across all tiers
All tiers pass with correct bboxes (0 failures); artificial drift of 10-150px detected with 1-26 field failures
#4523 • 7/30/2026, 1:40:37 PM
discovery
hackathon 2026

facts

narrative
Documentation mentions bbox-ink guardrail as proof of preprocessing accuracy
assumptions.md line 25 states guardrail validates that preprocessing bbox transforms are sufficient
#4522 • 7/30/2026, 1:39:50 PM
discovery
hackathon 2026

facts

narrative
Day 8 test results identical to Day 7 baseline: no regressions, no fixes
Main tests: 33 passed, 2 failed; Day 2 tests: 9 passed, 2 failed; exact match with v0.3-governor baseline
#4521 • 7/30/2026, 1:39:30 PM
change
hackathon 2026

facts

narrative
Day 8 files restored and Python bytecode caches cleared
All Day 8 modules present: cropper, escalate, grounding, vision engines; __pycache__ directories removed
#4520 • 7/30/2026, 1:38:12 PM
change
hackathon 2026

facts

narrative
Forced checkout to main branch succeeded despite file unlink warning
Repository now at Day 8 HEAD (commit 07b3857) with clean working tree after force switch
#4519 • 7/30/2026, 1:37:54 PM
discovery
hackathon 2026

facts

narrative
Locked docx file matches committed blob exactly, safe to force-remove
Local file hash matches git blob 2a95887f in main branch; file content preserved in repository
#4518 • 7/30/2026, 1:37:30 PM
discovery
hackathon 2026

facts

narrative
Git checkout blocked by locked Word document from Day 8
Cannot switch to main branch due to docs/ClaimRoute_AI_Solution_Architecture.docx file lock; still at v0.3-governor detached HEAD
#4517 • 7/30/2026, 1:37:10 PM
discovery
hackathon 2026

facts

narrative
Both primary and retry OCR engines return None for small single-character fields
Paddle primary_ocr and Tesseract retry_ocr both fail with value=None, conf=0.20; field bbox attribute is None indicating layout mapping failure
#4516 • 7/30/2026, 1:36:43 PM
discovery
hackathon 2026

facts

narrative
Day 7 governor escalates 7 fields due to low confidence extraction failures
patient_sex, 3x diagnosis_pointer, 3x line_units all have conf=0.20, trigger RETRY then ESCALATE decisions, extracted as None
#4515 • 7/30/2026, 1:36:05 PM
discovery
hackathon 2026

facts

narrative
Day 5 spine test validates end-to-end extraction accuracy on clean-tier baseline
test_spine_end_to_end_clean_page requires 90% field accuracy comparing extracted values against ground truth
#4514 • 7/30/2026, 1:35:24 PM
discovery
hackathon 2026

facts

narrative
Bboxes correctly cover ink when measured by relative contrast
All 34 fields pass relative-to-background ink test with 12-67% coverage; absolute threshold-128 test is inappropriate after illumination flatten
#4513 • 7/30/2026, 1:34:48 PM
discovery
hackathon 2026

facts

narrative
Preprocessing pipeline re-lightens already-lightened JPEG text
All 34 UB-04 fields fail dark128 after preprocessing; illumination_flatten pushes minimum gray values from ~100 to 114-165
#4512 • 7/30/2026, 1:34:14 PM
discovery
hackathon 2026

facts

narrative
Day 3 test validates bbox preservation through preprocessing pipeline
test_bboxes_survive_preprocessing_on_ugly applies ugly degradation, runs preprocess_page, transforms bboxes, then validates with check_bbox_ink
#4511 • 7/30/2026, 1:32:16 PM
Prompt
hackathon 2026
Continue the ClaimRoute AI hackathon project from the current repository state.

Do not add new Day 8 functionality yet.

The immediate goal is to establish a trustworthy Day 7 baseline, determine whether the four failing tests predate the uncommitted Day 8 work, and update the project handoff accurately.

## Current known state

`CLAUDE.md` was updated successfully with the current architecture, modules, conventions and hard rules.

Current test results from the working tree:

```text
python -m pytest tests/ --ignore=tests/test_day2.py
33 passed, 2 failed

python -m pytest tests/test_day2.py
9 passed, 2 failed
```

Current failures:

```text
tests/test_day3.py::test_bboxes_survive_preprocessing_on_ugly

BBox drift after preprocessing across 34 UB-04 fields.
```

```text
tests/test_day5.py::test_spine_end_to_end_clean_page

37/44 fields correct, below the required 0.9 gate.
```

```text
tests/test_day2.py::test_all_tiers_pass_ink_guardrail

Failure: drift in tier noisy.
```

```text
tests/test_day2.py::test_build_small_dataset_end_to_end

Ink guardrail failure on cms1500_5_0000/ugly affecting 18 fields.
```

The working tree currently contains uncommitted Day 8 work on top of tag:

```text
v0.3-governor
```

Uncommitted or modified Day 8-related files include:

```text
engine/cropper.py
engine/escalate.py
engine/grounding.py
engine/vision/
engine/extract.py
engine/governor.py
engine/schemas.py
configs/
engine/ocr/tesseract_engine.py
```

`HANDOFF.md` is stale and still says to resume at Day 7.

The README license table and dependency declarations are incomplete. The project uses:

```text
numpy
pytesseract
rapidocr-onnxruntime
```

but they are missing from either `requirements.txt`, the README license table, or both.

## Objective

Complete the following in order:

1. Preserve all current uncommitted work safely.
2. Test the clean Day 7 baseline at tag `v0.3-governor`.
3. Determine which failures exist at the tag.
4. Restore the current Day 8 working tree.
5. Run the same tests again.
6. Compare baseline versus current results.
7. Fix only genuine Day 7 blockers.
8. Do not mix unrelated Day 8 feature work into the Day 7 fixes.
9. Update dependencies and licensing documentation.
10. Refresh `HANDOFF.md`.
11. Decide whether Day 7 is actually complete.
12. Decide whether Day 8 work is safe to resume.

## Step 1: Protect the current working tree

Before switching commits or tags:

```text
- inspect git status
- create a named stash including untracked files, or create a temporary WIP branch
- verify that every modified and untracked Day 8 file is preserved
```

Preferred safe approach:

```bash
git status
git switch -c wip/day8-escalation
git add -A
git commit -m "wip: preserve Day 8 escalation work before baseline audit"
```

If a WIP commit is unsuitable, use:

```bash
git stash push -u -m "day8-escalation-before-day7-baseline-audit"
```

Do not lose any untracked files.

Show the preservation method used and verify the repository is clean before testing the baseline.

## Step 2: Test the Day 7 baseline

Check out the exact Day 7 baseline:

```bash
git switch --detach v0.3-governor
```

Run:

```bash
python -m pytest tests/ --ignore=tests/test_day2.py
python -m pytest tests/test_day2.py
```

Also run the four failing tests individually with verbose output:

```bash
python -m pytest tests/test_day3.py::test_bboxes_survive_preprocessing_on_ugly -vv
python -m pytest tests/test_day5.py::test_spine_end_to_end_clean_page -vv
python -m pytest tests/test_day2.py::test_all_tiers_pass_ink_guardrail -vv
python -m pytest tests/test_day2.py::test_build_small_dataset_end_to_end -vv
```

Record for each test:

```text
PASS at Day 7 baseline
FAIL at Day 7 baseline
NOT PRESENT at Day 7 baseline
```

Do not modify code while running this comparison.

## Step 3: Restore Day 8 working state

Return to the WIP branch or restore the stash.

Run the same test commands again.

Create a comparison table:

```text
Test
Day 7 baseline result
Current Day 8 working-tree result
Regression introduced by Day 8?
Likely responsible files
```

Classify each failure as:

```text
PRE-EXISTING DAY 7 DEFECT
DAY 8 REGRESSION
TEST-DATA OR GUARDRAIL DEFECT
EXPECTED BEHAVIOUR CHANGE
UNKNOWN
```

Do not weaken test thresholds merely to get green results.

## Step 4: Address Day 7 blockers

Only fix failures that belong to the Day 7 baseline or prevent the Day 7 acceptance criteria.

Investigate these areas carefully:

### BBox drift

Determine whether preprocessing transforms the image without correctly transforming field bounding boxes.

Check:

```text
rotation transform
deskew transform
scale transform
crop offsets
coordinate-space assumptions
original-image versus processed-image dimensions
UB-04 template coordinates
rounding and clipping
```

There should be one explicit coordinate contract:

```text
original document coordinates
or
processed document coordinates
```

Do not mix them.

If preprocessing creates a transform matrix, apply it consistently to all field boxes or preserve a reversible mapping.

### Clean-page accuracy gate

For:

```text
37/44 fields correct
```

identify the seven failures individually.

For each failed field, report:

```text
field name
ground truth
extracted value
source OCR span
bounding box
validator result
governor decision
root cause
```

Do not solve the problem by lowering the 0.9 threshold.

Check likely causes such as:

```text
adjacent-field contamination
merged OCR spans
wrong field assignment
normalization
template coordinates
optional-field treatment
retry routing
```

### Ink guardrail failures

Determine whether the guardrail is exposing:

```text
dataset-generation drift
incorrect degradation transform
field text rendered outside expected regions
threshold that no longer matches generated data
image scaling mismatch
bounding-box mismatch
```

Do not change the guardrail until the intended invariant is clearly documented.

## Step 5: Dependency and licensing correctness

Inspect imports and runtime usage.

Update `requirements.txt` or the project’s dependency source so all required runtime packages are declared.

At minimum verify:

```text
numpy
pytesseract
rapidocr-onnxruntime
Pillow
Faker
PyYAML
```

Do not add packages merely because they appear in experiments or unused files.

Update the README licensing table with:

```text
package
purpose
license
runtime or development dependency
source/reference
```

Keep the wording factual. Do not claim licence compatibility without evidence.

Run a clean dependency validation after editing.

Where practical, create a fresh virtual environment or use the existing lock/install process to confirm imports succeed.

## Step 6: Update HANDOFF.md

Refresh `HANDOFF.md` after the audit.

It must accurately state:

```text
Current phase
Current day
Day 7 status
Day 8 status
Last verified commit
Current WIP branch
Tests passed
Tests failed
Known defects
Files changed
Dependency status
Architecture status
Next exact task
Resume commands
```

Do not say “resume at Day 7” if Day 8 implementation has already started.

Use one of these exact status combinations:

```text
Day 7: COMPLETE
Day 8: IN PROGRESS
```

or:

```text
Day 7: NOT COMPLETE
Day 8: PAUSED PENDING DAY 7 FIXES
```

The status must be supported by test evidence.

Add a session entry that records:

```text
CLAUDE.md updated
baseline audit performed
test comparison performed
defects identified
dependency documentation updated
next task selected
```

## Step 7: Git discipline

Keep commits separated.

Suggested commits:

```text
test: compare Day 7 baseline with Day 8 working state
fix: resolve Day 7 preprocessing and extraction regressions
chore: synchronize runtime dependencies and licence documentation
docs: refresh handoff after Day 7 verification
```

Do not combine unfinished Day 8 escalation implementation with Day 7 defect fixes unless a change is inseparable and documented.

## Required final report

At the end, provide:

### Baseline comparison

```text
Test count at v0.3-governor
Passed
Failed
Missing tests
```

### Current working-state comparison

```text
Passed
Failed
Regressions
Pre-existing failures
```

### Day 7 decision

Exactly one:

```text
DAY 7 COMPLETE
DAY 7 NOT COMPLETE
```

### Day 8 decision

Exactly one:

```text
RESUME DAY 8
PAUSE DAY 8
```

### Failure analysis

For each of the four failures:

```text
classification
root cause
files involved
fix applied or remaining action
test evidence
```

### Dependency audit

```text
requirements synchronized: YES/NO
license table synchronized: YES/NO
clean install verified: YES/NO
```

### Documentation audit

```text
CLAUDE.md reviewed
HANDOFF.md refreshed
resume command recorded
next task recorded
```

Start by protecting the uncommitted Day 8 working tree. Do not edit or discard anything before confirming it is safely preserved.
#1150 • 7/30/2026, 1:21:46 PM
Session Summary
hackathon 2026
User requested --dangerously-skip-permissions flag; clarified it's a CLI startup flag, not a runtime option
Investigated
Investigated
Examined how --dangerously-skip-permissions works in Claude Code. Reviewed available alternatives for reducing permission prompts during active session.
Learned
Learned
The --dangerously-skip-permissions flag must be passed at Claude Code startup via CLI (e.g., `claude --dangerously-skip-permissions` or `claude --resume <session-id> --dangerously-skip-permissions`). It bypasses all permission prompts for the entire session including writes, deletes, and network calls. The flag is refused when running as root or in some sandboxed contexts. Alternative approaches exist for reducing friction without removing all guardrails: /permissions command for allowlisting specific commands, or the fewer-permission-prompts skill which scans transcripts and generates targeted allowlists for .claude/settings.json.
Completed
Completed
Explained that --dangerously-skip-permissions cannot be enabled mid-session and requires CLI restart. Provided exact command syntax for restarting with the flag. Outlined safer alternatives for permission management.
Next Steps
Next Steps
Awaiting user decision on whether to restart session with --dangerously-skip-permissions flag or continue current session. If continuing, three open items remain: (1) isolate whether 4 test failures predate uncommitted Day 8 work by stashing and re-running tests, (2) refresh HANDOFF.md from "resume at Day 7" to actual Day 8 state, (3) add missing dependencies (numpy, pytesseract, rapidocr-onnxruntime) to requirements.txt and README.md license table.
Session #839
•
7/30/2026, 1:18:43 PM
Session Summary
hackathon 2026
Updated CLAUDE.md with missing modules, architecture patterns, and hard rules while preserving existing decisions
Investigated
Investigated
Reviewed existing CLAUDE.md against current codebase to identify gaps in documentation. Examined modules added since initial documentation: governor.py, retry_rung.py, cropper.py, escalate.py, grounding.py, vision/, fusion.py, validators/, ocr/, layout/. Ran full test suite to verify no documentation changes broke existing functionality.
Learned
Learned
The repo implements a "decide → spend cheapest rung → re-decide" spine pattern across extract.py, governor.py, and both OCR rungs. Cost decisions live in configs/pipeline.yaml, not governor logic. The eval harness uses --tiers/--limit/--summarize flags with resumable rows. Submission wording rules from HANDOFF.md are correctness constraints on generated prose. Optional fields are never escalated. The offline-oracle is a test double with projected costs. Requirements.txt and license table have drift with actual dependencies (numpy, pytesseract, rapidocr-onnxruntime missing).
Completed
Completed
Updated CLAUDE.md with comprehensive documentation additions: 10+ missing modules, the decision spine pattern, cost-decision guidance (config-first not code-first), eval harness conventions, submission wording rules, three new hard rules, full tag ladder, and real single-test example. All existing hard-rules and architectural decisions preserved. Test suite run confirms documentation-only change: 42/44 tests passing with 4 pre-existing failures unchanged.
Next Steps
Next Steps
Working tree contains uncommitted Day 8 escalation work (cropper.py, escalate.py, grounding.py, vision/ untracked; extract.py, governor.py, schemas.py, configs, tesseract_engine.py modified) on top of v0.3-governor tag. Need to confirm whether 4 test failures predate Day 8 changes before tagging. HANDOFF.md shows "resume at Day 7" but Day 7 committed and Day 8 in progress—needs refresh.
Session #838
•
7/30/2026, 1:18:19 PM
Prompt
hackathon 2026
--dangerously-skip-permissions
#1149 • 7/30/2026, 1:18:06 PM
Prompt
hackathon 2026
/init
#1148 • 7/30/2026, 1:09:02 PM
Prompt
hackathon 2026
Excellent. Day 7 now proves the central economic thesis with actual numbers, not architectural optimism.

The strongest result is:

> **The local-compute retry rung prevents 32.4% of would-be paid escalations while preserving accuracy.**

That is exactly the kind of evidence the 35% cost criterion rewards.

The three cost bugs are also highly valuable submission material:

* Unicode normalization prevented false failures before routing.
* Field-specific validators stopped organisation names being judged like patient names.
* Optional blank fields no longer trigger pointless paid calls.
* Red-form dropout improved crop OCR by removing labels instead of asking the retry engine to read the form itself.

The phrase worth keeping:

> **The governor’s first job is not choosing a model. It is deciding when no model should be called at all.**

## Day 8 scope

Keep it disciplined:

```text
1. Field cropper with bounded margins
2. Vision model interface
3. Two model adapters maximum
4. Model policy enforcement
5. Response caching
6. Grounding check
7. Revalidation after escalation
8. Calibration-only bake-off
9. Updated funnel and cost ledger
```

Do not build an agent framework. This is a controlled escalation boundary.

## Model policy rules

Before any external request:

```text
- crop only, never full page
- field must allow external processing
- provider must be approved
- attempt budget must remain
- synthetic-data mode must be recorded
- request hash must be checked against cache
- estimated cost must be logged before execution
```

Recommended policy shape:

```yaml
external_models:
  approved_providers:
    - provider_a
    - provider_b

  require_crop_only: true
  require_zero_retention: true
  max_multimodal_attempts_per_field: 1

fields:
  patient_name:
    external_model_allowed: true

  provider_npi:
    external_model_allowed: true

  patient_address:
    external_model_allowed: false
```

## Grounding rules

A multimodal answer should be treated as another candidate, not truth.

Require:

* strict structured output
* expected field type
* evidence that the value appears in the crop
* normalization
* validator pass where applicable
* comparison against OCR candidates
* re-entry into the governor

For example:

```json
{
  "value": "SMITH, JOHN",
  "confidence": 0.94,
  "visible_text": "SMITH, JOHN",
  "reason": "The crop contains one patient-name field."
}
```

Reject responses that:

* add unseen characters
* return explanations instead of values
* fail required validators
* contradict visible crop evidence
* exceed the expected format

## Day 8 benchmark

Run only on the unresolved calibration fields from Day 7.

Compare:

```text
Model A
Model B
Local retry result
Ground-truth value
```

Measure:

* escalation-field accuracy
* resolution rate
* grounding rejection rate
* cost per call
* latency
* tokens per crop
* unresolved human-review rate
* final total cost per page

The most important final funnel becomes:

```text
Primary acceptance
Accept with flag
Resolved by local retry
Resolved by paid escalation
Human review
```

## One important cost comparison

Your current local cost is:

```text
$0.000438/page
```

Keep the multimodal cost separate until measured:

```text
Local processing cost/page
+
Escalation API cost/page
=
Automated cost/page
```

Then report estimated human review separately.

The Day 8 headline should eventually read like:

> **Selective field-crop escalation resolved X% of the remaining uncertain fields, reducing human review to Y%, while adding only $Z per page.**

Do not claim victory based only on escalation accuracy. The true win is reducing human touch at a lower cost than the human lane.

Proceed to Day 8 with the frozen test set untouched.
#1135 • 7/28/2026, 10:23:34 AM
Prompt
hackathon 2026
36 verified green, tree clean, tags and Day 6 evidence confirmed. Building Day 7.Now wiring the governor loop into the spine — decide, retry, revalidate, decide again:Two real bugs found. The name failure isn't merged spans — PP-OCR emits a **full-width comma** (`，` U+FF0C), and the retry crop picks up red form-label ink as garbage. Both have principled fixes:100% on that page now. Checking what still escalates:Three escalations, and all three are **governor/validator bugs rather than extraction errors** — exactly what Day 7 was meant to surface. Fixing all three:Now the governor must never spend on a legitimately-blank optional box:Zero escalations on those pages now. Building the funnel eval and tests:The test caught a real mismatch: `red_mask` deliberately rejects isolated pixels (noise rejection for the router), but dropout should remove **all** form ink. Separating the two concerns:Running the funnel on calibration, chunked:Both tiers complete (40 rows). Summarizing:Now the ablation arm — retry off — to isolate what the rung actually buys:The ablation is clean. Adding the derived headline metric to the report, then finalizing:Expected — that Day-5 test asserted a pre-governor invariant that's now obsolete. Updating it to the Day-7 invariant:**Day 7 complete — committed `2af4bb5`, tagged `v0.3-governor`, 46 tests green, tree clean.**

## Verification first (as instructed)
Clean tree, HEAD was `5fa1dfb`, six tags present, 36 tests green (25 + 11 split run), Day 6 evidence confirmed (100% catch, 4.4%/1.9% false alarm), wording rules read and applied.

## The funnel — calibration split, 1,432 fields (clean + ugly)

| Outcome | Share |
|---|---|
| ACCEPT | 88.13% |
| ACCEPT_WITH_FLAG | 6.91% |
| ESCALATE (would call a paid model) | 4.96% |
| **Accuracy** | **99.37%** |

## The retry rung's proof — the number Day 7 existed to produce

With the rung disabled, **7.33%** of fields end unresolved. With it on, only **4.96%** need a paid call. The local-compute rung resolved **32.4% of would-be escalations** — 2.37 percentage points of all fields — at **$0.0000049 per retried field**, roughly 10× cheaper than the cheapest multimodal call. Accuracy held (0.9930 → 0.9937). Ledger-derived cost is **$0.000438/page** across all local stages.

## Three bugs found, all cost bugs

The merged-name failure class **wasn't a layout problem at all** — PP-OCR was emitting a full-width comma (`，` U+FF0C), so `name_format` saw "0 commas". NFKC normalization at the OCR schema boundary fixed it at the *primary* rung, so those fields now never reach retry. Second, `name_format` was being applied to organisation names, failing correct values like "Miranda Medical Group" — split into `org_name_format`. Third, and most expensive: **the governor was escalating legitimately-blank optional boxes** — paying a model to inspect nothing. Optional fields now carry `optional: true`, return INAPPLICABLE when empty, and are accepted as blank. All four decisions logged in `assumptions.md`.

Also added: crop-level **red dropout** before retry OCR (the same trick real claim scanners use), which stopped Tesseract reading form labels as garbage.

Every field carries a human-readable decision trail (`page.decisions`), attempt budgets are enforced, retried candidates re-enter validation, and the governor provably cannot emit `ACCEPT_WITH_OVERRIDE`. Frozen test set untouched; no multimodal code added.

Next is **Day 8: Tier-2 escalation + model policy engine** — where that 4.96% finally meets a paid model, under crops-only enforcement.
#1134 • 7/28/2026, 10:22:06 AM
Prompt
hackathon 2026
/init
#1133 • 7/27/2026, 5:50:09 PM
