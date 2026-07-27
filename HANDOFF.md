# Handoff — claims-engine (resume at Day 7: Cost Governor + retry rung)

## Mission & deadline
Solo build, **Datamatics AI Engineering Hackathon 2026**. Architecture v1.2 locked.
**Competition ends Sunday 2 Aug 2026** (official brief arrived 27 Jul — the original 12-day
plan is compressed to ~6). Days 1–6 COMPLETE, 36 tests green, HEAD `62c35c9`, tag
`v0.2-validated`.

## OFFICIAL BRIEF CHANGES (supersede the execution plan where they conflict)
- **Weights changed:** Accuracy 35%, **Cost per page 35%** (was 25%), Innovation 10% (was 20%),
  Scalability 10%, Simplicity 10%. → invest in ledger-backed cost evidence, not demo polish.
- **Four tiers, scored separately AND combined:**
  - Tier A = machine-printed CMS-1500, single page → **covered** (our clean/noisy/ugly CMS-1500)
  - Tier B = CMS-1500 **plus attachments; find the CMS-1500, discard other pages** → **GAP**:
    needs page-stream keep/discard (router already emits unstructured/unknown + evidence)
  - Tier C = UB-04 single page → **covered**
  - Tier D = **unstructured layout**, extract specified fields → **BIGGEST GAP** (was a stretch
    goal, now a scored tier; this is where Tier-2 multimodal escalation earns its keep)
- **Official sample dataset is mandatory for benchmarking** — it was NOT attached to the DL
  email. User has been asked to chase it (ClaimsExtraction.Hackathon@datamatics.com / Reshma
  Balachandran). **Until it lands, mirror the tier structure synthetically** (Tier B = multi-page
  bundles with cover/separator/EOB pages; Tier D = unstructured referral/EOB letters). Our
  synthetic factory remains a deliverable (reproducible, PHI-free, exact ground truth = their
  "novel benchmarking methods" bonus).
- Their bonus list ≈ our architecture: difficult-regions-only AI, dynamic model selection,
  auto confidence scoring, learning from corrections, model-agnostic orchestration, **on-prem
  inference (PP-OCR/ONNX — no cloud needed for Tier 1)**, open-source-first. Say this explicitly
  in the submission.
- Registration closed 28 Jul; user was given the email text to send.

## Current measured evidence (calibration split only; test split still frozen)
- **Day 3** (`eval/results/day3_report.json`): router 100% on 150 pages, 0 bbox-ink failures,
  clean pages untouched by Tier-0, ~1.1 s/page.
- **Day 4** (`eval/results/day4_bakeoff.json`): primary = **paddle** (PP-OCR via ONNX), retry =
  **tesseract** (rescues 4.1% of primary misses; raw-ugly failure rate 80% → 0% with Tier-0).
- **Day 5** (`eval/results/day5_report.json`): spine field accuracy **97.1 / 99.2 / 99.4%**
  (clean / noisy / ugly, preprocessing on). Raw-ugly = **0%**.
  **Phrase this carefully in the submission** (a judge will otherwise catch it): raw-ugly is 0%
  because *rotation breaks the router before extraction is ever attempted*, not because OCR
  fails. Correct line: *"Tier-0 preprocessing restores the degraded-page free path: automated
  field extraction rises from 0% to 99.4% because rotation correction makes routing and layout
  mapping viable, at ~$0.0001/page."* Call it **pipeline recovery**, never "OCR uplift".
- **Day 6** (`eval/results/day6_report.json`): validators flag **100%** of spine errors;
  false-alarm rate 4.4% (clean) / 1.9% (ugly); mean fused confidence **0.97 correct vs 0.68
  errors** — the separation the governor routes on.
- Known failure class (clean tier, ~97%): on *sharp* pages PP-OCR merges adjacent name boxes
  into one line span → `patient_name`/`insured_name` get concatenated text. `name_format`
  already FAILs these (comma count). **Day 7's crop-level Tesseract retry should resolve them
  nearly free — that's the retry rung's first proof.**

## What exists (don't rebuild)
`data_factory/` (CMS-1500 + UB-04, 3 tiers, exact bboxes, ink guardrail) · `engine/schemas.py`
(6-state, ACCEPT_WITH_OVERRIDE human-only) · `ledger.py` · `preprocess.py` (signal-gated,
transform history + bbox replay) · `router.py` (free, evidence + variant) · `ocr/` (base +
paddle + tesseract adapters, raw preserved) · `layout/` (templates generated from renderers per
line-count variant + overlap-based mapper) · `validators/` (15 validators, policy-driven,
dictionaries) · `fusion.py` (explainable; **verdicts deliberately NOT fused — they are separate
governor inputs**) · `extract.py` (the spine) · `eval/day{3,4,5,6}_*.py` (chunked, resumable).

## Day 7 scope (next)
1. `engine/governor.py`: 4-way decision (ACCEPT / ACCEPT_WITH_FLAG / RETRY / ESCALATE, terminal
   HUMAN_REVIEW) from **fused confidence + validator verdicts + field policy + attempt history**;
   attempt budget from `configs/pipeline.yaml` (primary 1 / retry 1 / multimodal 1 / grounding 0).
2. Retry rung: crop the field bbox, re-OCR with **tesseract** (word-level), engine agreement
   feeds fusion, **result re-enters validation**.
3. Measure the funnel: % resolved by primary / retry / accept-with-flag / still-uncertain.
4. Tag `v0.3-governor`.

## Environment gotchas (hard-won)
Bash calls are independent, background procs die, **hard 45 s cap** → chunk everything; eval
pattern = JSONL rows + per-row flush + `--limit`/resume (copy `eval/day6_eval.py`). Full pytest
run is ~55 s → split it (`--ignore=tests/test_day2.py`, then that file alone). pip needs
`--break-system-packages`. Installed: faker, pyyaml, pillow, numpy, pytest, pytesseract,
rapidocr-onnxruntime. Never seed with `hash(str)`. Windows paths for Read/Write/Edit;
`/sessions/...` for bash only. Mount deletion is enabled; stale `.git/*.lock` files have bitten
twice — `rm -f .git/HEAD.lock` if git complains.

## Suggested skills next session
`anthropic-skills:executing-plans`, `anthropic-skills:test-driven-development`,
`anthropic-skills:verification-before-completion`, `anthropic-skills:systematic-debugging`.
