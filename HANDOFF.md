# Handoff — claims-engine (Day 8 escalation harness verified)

## Status

```
Day 7: COMPLETE
Day 8: IN PROGRESS
```

Both supported by test evidence below. Architecture v1.2 remains locked.

| | |
|---|---|
| Current phase | Tier-2 escalation (Day 8) |
| Last verified commit | `ae0097c` on `main`; Day 8 harness work is currently uncommitted |
| Working branch | `main` (preserve concurrent Day 7 result changes and `docs/MEMORY.md`) |
| Safety branch | `safety/day8-pre-audit` → `07b3857`, kept as a pre-audit restore point |
| Tests passed | **57 / 57** (46 existing + 11 Day 8 harness tests) |
| Tests failed | **0** |
| Dependency status | requirements.txt synchronized, licence table complete, clean-venv install verified |
| Architecture status | v1.2 locked, unchanged by this audit |

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
