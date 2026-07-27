# Handoff — Datamatics Hackathon: claims-engine (resume at Day 4: OCR adapters + bake-off)

## Mission & state
Solo build of the **cost-governed healthcare claims extraction engine** (Datamatics AI Engineering Hackathon 2026). Architecture v1.2 locked. **Days 1–3 COMPLETE, 25 tests green.** Git tags are the fallback ladder: `v0.0-factory` → `day2-dataset` → `v0.1-preprocess-router` (HEAD 50ac133, clean tree).

## Canonical references (read, don't re-derive)
- Repo: `claims-engine/` in connected folder `D:\AI-Workspace\hackathon 2026` (bash: `/sessions/<session>/mnt/hackathon 2026/claims-engine`)
- Plan: session outputs `hackathon-execution-plan.md` (day-by-day, benchmark methodology, submission story)
- `docs/architecture.md` (v1.2 normative), `docs/assumptions.md` (**6 engineering decisions — including #6: composite quality score is scan-condition, NOT processing-benefit; the preprocessing accuracy claim comes from the Day-4 OCR ablation**)
- Frozen split: `eval/splits/split_v1.json` (sha256 4d70876b…, 20 cal / 30 test claims; never tune on test)
- Day-3 evidence: `eval/results/day3_report.json` — router 100%/150 pages, 0 bbox-ink failures, clean pages untouched, ~1.1 s/page CPU

## What exists (do not rebuild)
Dataset factory (CMS-1500 + UB-04, clean/noisy/ugly, exact bboxes, ink guardrail), `engine/schemas.py` (6-state model; ACCEPT_WITH_OVERRIDE human-only, tested), `engine/ledger.py`, `engine/preprocess.py` (signal-gated deskew / illumination-flatten / denoise / stretch, transform history + `transform_bboxes` replay), `engine/router.py` (red-mask layout-profile correlation; evidence-returning), `eval/day3_eval.py` (chunked-eval template).

## Day 4 scope (from plan)
1. `engine/ocr/base.py`: `OcrEngine.extract(image) -> [(text, bbox, confidence)]` + adapters: **PaddleOCR** and **Tesseract** (pytesseract + apt tesseract-ocr). docTR = stretch.
2. Bake-off on the **calibration split only**: word accuracy, latency, amortized $/page (ledger!). Pick primary + retry engine (maximize error-profile diversity). Save table to `eval/results/` — it's submission evidence.
3. **The Day-4 headline: OCR ablation with preprocessing on/off on ugly tier** → "preprocessing recovered X points at $0" (decision #6 promise).
4. Wire ledger logging into preprocess + OCR stages (operation, $, ms per page).

## Hard-won environment facts (believe these)
- Bash: independent calls, background procs die, **hard 45 s cap** → chunk everything; eval harness pattern = JSONL rows + per-row flush + `--limit`/resume (see day3_eval.py). Mount writes ~1 s/page — generate to /tmp then `cp`.
- pip needs `--break-system-packages`. Installed: faker, pyyaml, pillow, numpy, pytest. PaddleOCR install is heavy (~minutes, may need chunked/`nohup` won't survive — install in one call, import-test in the next).
- File deletion on the mount is enabled (was granted). Never seed with `hash(str)`.
- Windows paths for Read/Write/Edit; /sessions path for bash only.

## Day-3 debugging lessons (encode in future work)
Point-sampling thin-line profiles aliases them away — always bin (BOX-resize). One layout reference per form under-matches variable-length tables — reference per line-count variant. Any-pixel extent crops break under speckle — use mass quantiles. Illumination gain amplifies corner noise — flatten is gated at 0.075 (measured separation: clean/noisy ≤0.063, shadow ≥0.094).

## Suggested skills for next session
- `anthropic-skills:executing-plans` (continue plan), `anthropic-skills:test-driven-development` (adapters + Day-6 validators), `anthropic-skills:verification-before-completion` (before tagging), `anthropic-skills:systematic-debugging` (OCR quirks).
