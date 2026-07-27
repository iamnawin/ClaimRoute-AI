# Handoff — Datamatics Hackathon: claims-engine build (resume at Day 3)

## Mission & state
Naveen (solo) is building the **cost-governed healthcare claims extraction engine** for the Datamatics AI Engineering Hackathon 2026. Architecture v1.2 is locked; **Days 1–2 of the 12-day plan are COMPLETE**. Next session = **Day 3: Tier 0 preprocessing + free heuristic document router**.

## Where everything lives
- **Repo (user's machine, connect folder `D:\AI-Workspace\hackathon 2026`):** `claims-engine/` — git history is the build log: `v0.0-factory` (Day 1, 5e8f845), `day2-dataset` (Day 2, b12b533). 18 pytest tests green.
- **Execution plan (day-by-day, benchmarks, submission story):** session outputs `hackathon-execution-plan.md` — the canonical plan; read before coding.
- **Architecture + normative notes:** `claims-engine/docs/architecture.md` (v1.2 state model incl. human-only ACCEPT_WITH_OVERRIDE, attempt budgets, revalidation rules).
- **Frozen test split:** `claims-engine/eval/splits/split_v1.json` — 20 calibration / 30 test claims, sha256 4d70876b…, claim-level, stratified. NEVER tune on test; factory refuses to overwrite a mismatched freeze.

## What exists (do not rebuild)
Dataset factory for CMS-1500 (44 fields) + UB-04 (~19 flat + revenue lines): synthetic, valid Luhn NPIs, arithmetic-consistent totals, exact per-field bboxes in ground truth. Degradation tiers clean/noisy/ugly with bbox transforms (only rotation moves geometry) + `check_bbox_ink` guardrail run on every generated page. 150-page dataset at `claims-engine/data/generated/` (gitignored, regenerable: `python -m data_factory.make_dataset --n-per-form 25 --seed 42 --out data/generated`, chunked via `--forms/--start/--end` if needed). `engine/schemas.py` (six-state model, override guard tested), `engine/ledger.py` (cost/page as a query), three configs (field_policy, pipeline w/ attempt budgets, prices verified 2026-07-27).

## Day 3 scope (from the plan)
1. `engine/preprocess.py`: page split, deskew, rotation detect (Hough/projection profile), denoise, DPI normalize, quality score (blur+contrast+skew residual). Output: clean page images + page metadata + quality score.
2. **Transform ground-truth bboxes alongside any deskew** (reuse the rotate_with_bboxes math in `data_factory/degrade.py`; the ink guardrail is the checker). This is the plan's #1 gotcha.
3. `engine/router.py`: geometry + anchor keywords ("HEALTH INSURANCE CLAIM FORM", "UB-04") → {cms1500, ub04, unstructured, unknown}. NO API calls. Exit: ≥98% on the generated dataset; measured preprocessing gain on ugly tier ("X points of accuracy at $0" needs OCR, so record quality-score deltas now, accuracy after Day 4).
4. Needs opencv: `pip install opencv-python-headless --break-system-packages`.

## Sandbox/environment gotchas (hard-won, believe them)
- Bash calls are independent; **background processes die between calls**; hard 45s timeout → chunk long jobs (generate to /tmp, then cp to the mount; mount writes are ~1s/page slow).
- Mount deletes were blocked; **file deletion is now enabled** for the folder (was granted via allow_cowork_file_delete). Stale `.git/*.lock` files caused failures once — cleared now.
- Never seed with `hash(str)` (PYTHONHASHSEED). Faker() construction is expensive — module-level instance exists in generators.
- Installed in sandbox: faker, pyyaml, pillow, numpy, pytest (pip needs `--break-system-packages`).
- bash path: `/sessions/<session>/mnt/hackathon 2026/claims-engine`; file tools use `D:\AI-Workspace\hackathon 2026\claims-engine`.

## Working style (locked)
$20–50 API budget (cache everything, Day 8+). Challenge weak assumptions; structured, concise; every day ends runnable + tagged; verification before "done" claims. Key metrics structure and all locked v1.2 decisions: see architecture.md + plan doc — do not reopen.

## Suggested skills for next session
- `anthropic-skills:executing-plans` — continue running the written plan with checkpoints.
- `anthropic-skills:test-driven-development` — preprocess/router logic and (Day 6) validators.
- `anthropic-skills:verification-before-completion` — before tagging any day complete.
- `anthropic-skills:systematic-debugging` — OCR/layout misbehavior from Day 4 on.
