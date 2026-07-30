# Handoff — claims-engine (Day 11 frozen evidence verified)

## Status

```
Day 7: COMPLETE
Day 8: COMPLETE
Day 9: COMPLETE
Day 10: COMPLETE
Day 11: COMPLETE
```

All supported by test evidence below. Architecture v1.2 remains locked.

| | |
|---|---|
| Current phase | Frozen synthetic evidence and submission audit (Day 11) |
| Frozen benchmark commit | `8324d600fa61ad7c6a57f7c70e3126232bd4e602` |
| Last verified UI commit | `7701e49` on `main`; feature, test, and presentation commits are separate |
| Working branch | `main` (preserve concurrent Day 7 result changes and `docs/MEMORY.md`) |
| Safety branch | `safety/day8-pre-audit` → `07b3857`, kept as a pre-audit restore point |
| Tests passed | **83 / 83** |
| Tests failed | **0** |
| Dependency status | requirements.txt synchronized, licence table complete, clean-venv install verified |
| Architecture status | v1.2 locked, unchanged by this audit |

## Session log - 30 Jul 2026 (Day 11 frozen evidence)

1. **Freeze:** committed the evaluation harness first, then froze the clean tree at `8324d60`.
   `eval/frozen/frozen_manifest.json` records the commit, environment, operating mode, dataset,
   commands, and evidence labels. Architecture v1.2 and all thresholds/policies remain unchanged.
2. **Dataset:** 30 held-out synthetic documents, each rendered clean/noisy/ugly = 90 pages and
   3,168 ground-truth fields. Calibration/test overlap = 0; duplicate rows/pages = 0; test SHA-256
   `4d70876b676cc06a4b2558e3d1a49450f826803c4b8d85f89041b91c80d2be5a`.
3. **Blended Balanced result:** 99.716% field accuracy, 99.936% critical-field accuracy,
   93.303% primary local resolution, 6.697% local retry, 71.560% retry resolution, 1.905%
   escalation, 4.839% escalation resolution, 10.353% accept-with-flag, and 1.813% human review.
4. **Tier accuracy / critical / human review:** clean 99.905% / 100% / 0%; noisy 99.811% /
   100% / 1.106%; ugly 99.432% / 99.807% / 4.332%.
5. **Cost:** measured external calls = 0 and measured API spend = $0. Measured local cost is
   $0.0000722/page. Projected selective-oracle API cost is $0.0000227/page and projected total
   automated cost is $0.0000949/page. Human review is a separate configured assumption.
6. **Throughput:** 90 pages in 586.931 seconds; 9.200 pages/minute, 552.024 pages/hour,
   6.521-second mean, 5.269-second p50, and 10.825-second p95 on the recorded development
   workstation. This is not a production throughput claim; memory/provider latency were unmeasured.
7. **Ablations:** primary-only 66.351%; preprocessing 99.527%; validators expose 6.881%
   unresolved; local retry reaches 99.842% with 1.957% unresolved; full governed pipeline reaches
   99.716% with 1.862% unresolved. A validators-disabled full pipeline is unsupported and was not
   invented after freeze.
8. **Config SHA-256:** `engines.yaml` `2ab91b47...d0dcb77`; `field_policy.yaml`
   `f08543f7...6244bd`; `operating_modes.yaml` `bb56ade8...372093`; `pipeline.yaml`
   `dfb8afae...a3c90d`; `prices.yaml` `96d1ab06...9a8c1`. Full hashes, critical runtime hashes,
   and environment metadata are in `eval/frozen/config_hashes.json`.
9. **Safety/licensing:** official-looking data remains excluded; no external provider or tracked
   secret/PHI/local dataset was found. Installed dependency license metadata is recorded in
   `docs/licensing.md`; provider and dataset terms remain separate approval tracks.
10. **Known limitations:** synthetic generalization is unverified; offline oracle is not provider
    accuracy/latency evidence; ugly escalations had zero governor-accepted resolution; production
    controls and throughput are untested; degraded overlays can be offset in processed coordinates.
11. **Unresolved organizer questions:** official image-to-output mapping, permitted purpose, PHI
    status, retention/deletion, and named-provider crop permissions.
12. **Next exact task:** build the final presentation and recorded synthetic demo using
    `docs/submission/claims_register.md`; fix or visibly disclose the degraded-overlay coordinate
    limitation before recording.

## Session log — 30 Jul 2026 (Day 10 UI)

1. **Framework:** retained the documented Streamlit direction. The pre-existing `app/` directory
   was empty; no alternate UI framework or application entry point existed.
2. **Thin adapter:** added `app/service.py` and `app/streamlit_app.py`. The application invokes
   `engine.extract.run_page` directly and reuses `PageResult`, `FieldResult`, the ledger, field
   policy, governor presets, and generated calibration summaries.
3. **Workflow:** bundled synthetic selection or local raster upload, Balanced default, document
   metadata, pipeline journey, actual resolution funnel, field table, overlay/crop evidence,
   validator and governor paths, cost/latency, scale projections, mode comparison, benchmark,
   and final/audit JSON downloads.
4. **Safety:** PNG/JPEG/single-page TIFF only, 10 MB and one-page limits, in-memory input,
   temporary-ledger cleanup, generic error messages, duplicate-run protection, screenshot-safe
   default, no value logging, and no real-provider control. Uploads always set
   `run_escalate=False`; only bundled synthetic examples can use `offline-oracle`.
5. **Cost labeling:** local compute and measured API spend are labeled MEASURED. Offline-oracle
   and scale costs are labeled PROJECTED. Mode thresholds are labeled CONFIGURED ASSUMPTION.
6. **Manual clean run:** `cms1500_42_0000 / clean`, Balanced, 46 fields, 46 local accepts,
   0 retries, 0 escalations, 0 human review, 46 API calls avoided, zero external calls.
7. **Manual degraded run:** `cms1500_42_0000 / ugly`, Balanced, 46 fields, 32 local accepts,
   11 flags, 3 retries, 1 offline-oracle escalation, 1 human review, 45 API calls avoided,
   measured API spend $0.
8. **Validation:** `python -m pytest tests/test_day10.py -q` = 11/11;
   `python -m pytest tests/ -q` = 75/75. Streamlit AppTest produced zero exceptions for startup,
   clean, and ugly workflows.
9. **Screenshot:** screenshot-safe start screen saved to `docs/screenshots/day10_home.png`.
10. **Known limits:** one raster page, no PDF, soft post-run timeout, processed-coordinate overlay
    can offset on degraded source pixels, uploads cannot complete paid escalation, and no human
    review queue. Day 9 replay modes remain evidence; locked runtime presets were not retuned.
11. **Deployment:** local or access-controlled synthetic demo only. No public official-data
    deployment until auth, retention, worker isolation, provider approval, and mapping are verified.
12. **Next exact task:** run the Day 11 frozen-test evaluation and submission readiness audit
    without tuning thresholds or using official data until its governance is confirmed.

## Session log — 30 Jul 2026 (Day 9 calibration)

1. **Failure analysis completed:** analyzed all 170 Day 8 HUMAN_REVIEW rows plus the
   one incorrect terminal row. Of the 170 human-review values, 157 were already exact-match
   correct; the dominant root cause is post-escalation governor threshold/budget behavior,
   not OCR or measured provider failure.
2. **Root-cause evidence:** 157 governor-threshold, 8 offline-oracle limitation,
   3 deterministic-normalization, 2 preprocessing/crop-strategy, and 1 OCR-segmentation
   case. Final validation stamps contain zero FAIL verdicts in this cohort.
3. **Outputs created:** `day9_failure_analysis.json/.csv` (171 field records),
   `docs/evaluation/day9_failure_analysis.md`, `configs/operating_modes.yaml`,
   `eval/day9_calibration.py`, 120 sweep rows, a deterministic JSON summary, and a
   five-point accuracy-cost frontier.
4. **Replay boundary:** the harness reuses the 406 recorded Day 8 escalation candidates and
   60 page receipts. It reruns no OCR, calls no provider, and uses no official data. Because
   Day 8 did not persist the selected pre-escalation candidate or full page validation context,
   local candidates are deterministic reconstructions from primary/retry attempts. Do not
   present this frontier as measured real-provider or production-governor performance.
5. **Calibrated modes (field / critical accuracy; escalation; human review; projected total):**
   Economy = **96.55% / 98.97%; 3.96%; 3.31%; $0.000200/page**. Balanced =
   **98.51% / 99.72%; 7.50%; 0.98%; $0.000240/page**. Accuracy =
   **98.79% / 99.81%; 17.23%; 4.33%; $0.000351/page**. Accuracy has zero flagged
   outcomes by design; its human-review rate is therefore higher than Balanced.
6. **Recommended headline mode:** Balanced at local accept `0.80`, multimodal accept
   `0.90`, paid escalation for high/medium criticality, flags for low/medium where policy
   permits, retry before escalation, and no optional-field escalation.
7. **Cost labeling:** measured API spend remains **$0**. All oracle API costs are projected.
   Runtime governor presets were not changed from replay evidence alone; architecture v1.2
   remains locked.
8. **Validation:** `python -m pytest tests/test_day9.py -q` = 7/7;
   `python -m pytest tests/ -q` = 64/64; repeated generation produced byte-identical files.
9. **Remaining blockers:** real-provider calibration still requires approved synthetic-only
   execution; official-dataset tuning remains blocked until role, mapping, retention, and PHI
   handling are confirmed.
10. **Next exact command:** `python -m eval.day9_calibration`.

Day 9 intentionally has no engine redesign and no UI changes. Any later UI work must be a
separate commit.

## Mission & deadline

Solo build, **Datamatics AI Engineering Hackathon 2026**. **Competition ends Sunday 2 Aug 2026**
(official brief arrived 27 Jul; the original 12-day plan is compressed to ~6).

## Session log — 30 Jul 2026 (Day 8 escalation harness)

1. **Task completed:** implemented `eval/day8_escalation.py` using the existing
   `run_page` → `escalate_field` → grounding/revalidation → governor spine.
2. **Files changed:** added the harness and `tests/test_day8.py`; generated resumable
   field rows, page receipts, cost ledger, and JSON/CSV summaries under `eval/results/`.
3. **Commands run:** `python -m pytest tests/test_day8.py -q`, full
   `python -m pytest tests/ -q`, small clean smoke run, resumable 10-page chunks for
   clean/noisy/ugly, then `python -m eval.day8_escalation --tiers clean noisy ugly --summarize`.
4. **Tests/results:** 57/57 tests pass. Completed 60 calibration pages / 2,148 fields;
   wrote 406 unique escalated-field rows with zero duplicate rows and zero provider errors.
5. **Cost labeling:** `offline-oracle` measured API spend is **$0**. Projected oracle
   spend is **$0.0128319 total / $0.000214 per page blended**. Projected total automated
   cost is **$0.000369/page blended**; measured local automated cost is **$0.000155/page**.
6. **Tier evidence:** field accuracy clean/noisy/ugly = **99.44% / 99.30% / 97.07%**;
   escalation rate = **3.21% / 8.66% / 44.83%**; human review =
   **0.70% / 1.96% / 21.09%**. Blended accuracy = **98.60%** and human review = **7.91%**.
7. **Known issues:** oracle results prove the controlled boundary, not any real model's
   accuracy. Ugly-tier escalation/human-review rates remain high. Clean has seven cache hits
   from the pre-existing smoke cache; cache savings are reported separately. Official PHI data
   was not used and remains prohibited from external providers.
8. **Next exact task:** review the 170 human-review escalation rows, classify grounding vs
   validator/confidence causes, then decide whether a real-provider synthetic calibration run
   is justified before tagging `v0.4-escalation`.

Resume/verify command:

```bash
python -m pytest tests/ -q
python -m eval.day8_escalation --tiers clean noisy ugly --summarize
```

## Session log — 30 Jul 2026 (baseline audit)

1. **CLAUDE.md updated** with current architecture, module map, conventions and hard rules
   (it had described a Day 3–5 snapshot and omitted governor/retry/escalation/vision).
2. **Baseline audit performed.** Day 8 work was already committed at `07b3857` and pushed, so
   no stash was needed; `safety/day8-pre-audit` was created before detaching HEAD.
3. **Test comparison performed** at `v0.3-governor` vs `07b3857` — see the table below.
4. **Defects identified and fixed** — two root causes behind all four failures.
5. **Dependency documentation updated** and verified by clean-venv install.
6. **Next task selected**: Day 8 escalation evaluation (below).

## Baseline comparison: `v0.3-governor` vs Day 8 tree

Same dataset both runs (`data/` is gitignored, so it does not move with the checkout —
any difference would be attributable to code alone).

| Test | Day 7 baseline | Day 8 tree (pre-fix) | Regression? | Classification |
|---|---|---|---|---|
| `test_day2::test_all_tiers_pass_ink_guardrail` | FAIL | FAIL | No | Guardrail defect |
| `test_day2::test_build_small_dataset_end_to_end` | FAIL | FAIL | No | Guardrail defect |
| `test_day3::test_bboxes_survive_preprocessing_on_ugly` | FAIL | FAIL | No | Guardrail defect |
| `test_day5::test_spine_end_to_end_clean_page` | FAIL | FAIL | No | Pre-existing Day 7 defect |
| 3 × Tesseract-not-found (`day5`, `day6`, `day7`) | FAIL (env) | PASS | No — Day 8 **fixed** it | Environment |

**Zero regressions introduced by Day 8.** All four failures pre-date it and reproduce
identically at the tag. The three Tesseract failures are an environment artefact: the binary is
installed but not on PATH, and the Day 8 commit incidentally fixed it by adding binary
auto-discovery to the adapter. Counting pass/fail alone would have credited Day 8 with
"fixing 3 tests"; reading the diff is what attributes it correctly.

## Defects found and fixed

### 1. bbox-ink guardrail measured legibility, not geometry (3 of the 4 failures)

`check_bbox_ink` required `pixel < 128` — an **absolute** darkness cutoff — to prove a bbox
still covered its ink. But photometric tiers and Tier-0 `illumination_flatten` legitimately
lighten the page. After preprocessing an ugly UB-04 the darkest pixel *anywhere on the image*
is ~114, so all 34 correctly-placed bboxes failed simultaneously.

The tell: the `noisy` tier failed too, and `noisy` provably never moves a coordinate
(`degrade()` returns `dict(bboxes)` unchanged). Geometry could not have drifted.

Fixed by measuring each crop against **its own 90th-percentile background**. Verified to keep
detection power rather than trade it away: 0 false alarms on correct bboxes across all three
tiers, while injected drift of 25–60px still fails 18–24 of 34 fields.
Logged as decision 11 in `docs/assumptions.md`. **Do not "fix" this by lowering the absolute
threshold** — it would pass today's images and silently lose drift detection on darker paper.

### 2. Retry rung could not read single-character fields (the 4th failure)

`test_day5` was 37/44. All 7 misses were single-character boxes: `patient_sex` ('F'), three
`line*_units`, three `line*_diagnosis_pointer`. Tesseract's default PSM 3 assumes a page of
prose and discards a lone glyph in a small box, returning nothing; PSM 6/7/10 read all three
correctly. So the retry rung could not rescue exactly the fields it exists for — all seven went
primary → RETRY → ESCALATE unresolved and would have been billed to a paid model for want of a
one-line config.

Fixed with an optional `psm` argument on the Tesseract adapter (**default unchanged**, so the
Day 4 full-page bake-off path is untouched) and the retry rung requesting PSM 6 for crops.
Result: `cms1500_42_0000` clean-page accuracy **37/44 → 44/44**, all seven resolved at the
local-compute rung, none escalated. Logged as decision 12.

Neither fix weakened a test, lowered a threshold, or disabled a check.

## Current measured evidence (calibration split only; test split still frozen)

- **Day 3** (`day3_report.json`): router 100% on 150 pages, 0 bbox-ink failures, clean pages
  untouched by Tier-0, ~1.1 s/page.
- **Day 4** (`day4_bakeoff.json`): primary = **paddle** (PP-OCR via ONNX), retry = **tesseract**
  (rescues 4.1% of primary misses; raw-ugly failure 80% → 0% with Tier-0).
- **Day 5** (`day5_report.json`): spine field accuracy 97.1 / 99.2 / 99.4% (clean/noisy/ugly).
- **Day 6** (`day6_report.json`): validators flag 100% of spine errors; false-alarm 4.4% clean /
  1.9% ugly; mean fused confidence 0.97 correct vs 0.68 errors.
- **Day 7** (`day7_report.json`, regenerated 30 Jul after the fixes, clean tier, 20 docs /
  716 fields):
  - field accuracy **99.16%**
  - funnel **81.01% ACCEPT · 15.78% ACCEPT_WITH_FLAG · 3.21% ESCALATE · 0% HUMAN_REVIEW**
  - retry rung: 436 fields retried (60.89%), **413 resolved**, 2 still wrong
  - retry cost **$0.0000020 per retried field**
  - ledger total **$0.000115 per page** over 20 pages (`ocr_paddle` $0.00123,
    `retry_tesseract` $0.00087, `preprocess` $0.00015, `route` $0.00005) — all local compute
  - **noisy/ugly tiers not yet run** through the funnel; do this before quoting a blended number

## Day 7 acceptance criteria — all met

1. Governor 4-way decision from all four inputs — `engine/governor.py`, tested in `test_day7.py`.
2. Retry rung crops, re-OCRs with tesseract, revalidates, feeds engine agreement — verified.
3. Funnel measured — above.
4. Tag `v0.3-governor` exists.

## SUBMISSION WORDING RULES (a judge will test these)

1. Tier-0 result is **pipeline recovery**, never "OCR uplift": 0% → 99.4% on ugly because
   rotation correction makes routing and layout mapping viable, not because OCR improved.
2. The retry rung is **"local compute only" / "near-zero incremental cost"** — never "$0" or
   "free". It burns CPU, that CPU is priced in `configs/prices.yaml`, and every retry is logged
   to the ledger. Same for preprocessing, routing, validation.
3. `offline-oracle` is a **deterministic test double**. Its accuracy is not evidence about any
   real model; its cost is *projected* from token counts, never measured spend.
4. Cache hits and grounding rejections are reported separately so neither flatters the cost story.

## What exists (don't rebuild)

`data_factory/` (CMS-1500 + UB-04, 3 tiers, exact bboxes, ink guardrail) · `engine/schemas.py`
(6-state, ACCEPT_WITH_OVERRIDE human-only) · `ledger.py` · `preprocess.py` · `router.py` ·
`ocr/` (paddle + tesseract, PSM-aware) · `layout/` · `validators/` (15) · `fusion.py` ·
`governor.py` · `retry_rung.py` · `cropper.py` (PHI boundary, structural) · `grounding.py` ·
`escalate.py` · `vision/` (base + offline-oracle + openai + gemini) · `extract.py` (the spine) ·
`eval/day{3,4,5,6,7}_*.py`.

## Day 8 scope (next, in order)

1. **Do not add new escalation functionality** until its evidence exists — the code is written
   (`escalate.py`, `grounding.py`, `cropper.py`, `vision/`) but has only a smoke test.
2. Write `eval/day8_escalation.py` following the established harness contract
   (`--tiers/--limit/--summarize`, JSONL rows, per-row flush, resume on restart).
3. Measure with `offline-oracle`: escalation rate, grounding rejection rate, cache-hit rate,
   projected cost/page, and accuracy delta on the 3.21% that reach ESCALATE.
4. Run the funnel on **noisy and ugly** tiers so the Day 7 number is not clean-only.
5. Tag `v0.4-escalation`.

## Environment gotchas (hard-won)

Shell calls are independent and long runs get killed → **chunk everything** (`--limit` +
resumable JSONL rows). Full pytest ~50 s (non-day2) + ~15 s (day2). Tesseract 5.4.0 is
installed at `C:\Program Files\Tesseract-OCR\` but **not on PATH** — `tesseract_engine.py`
auto-discovers it (PATH → standard locations → `TESSERACT_CMD`), so no PATH edit is needed.
Never seed with `hash(str)`. Windows paths for Read/Write/Edit. `docs/*.docx` can be file-locked
by Word and block `git switch`; use `git switch --force` (the blob is committed and identical).
Stale `.git/*.lock` files have bitten twice.

## Resume commands

```bash
cd "D:/AI-Workspace/hackathon 2026/claims-engine"
git log --oneline -1          # expect 8fed3b1 (or later) on main

python -m pytest tests/ --ignore=tests/test_day2.py   # expect 35 passed
python -m pytest tests/test_day2.py                   # expect 11 passed

# Day 7 funnel on the tiers not yet covered
python -m eval.day7_funnel --tiers noisy --limit 12
python -m eval.day7_funnel --summarize
```

**Next exact task:** write `eval/day8_escalation.py` (harness only, no new engine code), then
run it chunked against `offline-oracle` on the calibration split.
