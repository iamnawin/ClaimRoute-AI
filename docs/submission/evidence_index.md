# Day 11 evidence index

| Evidence | Purpose |
|---|---|
| `eval/frozen/frozen_manifest.json` | Frozen commit, split, policy, commands, and evidence labels |
| `eval/frozen/config_hashes.json` | SHA-256 hashes for configuration and critical runtime files |
| `eval/frozen/environment_manifest.json` | Python, OCR, platform, package versions, and license metadata |
| `eval/frozen/final_benchmark_rows.jsonl` | Field-level candidates, routing, truth, decisions, and cost basis |
| `eval/frozen/final_benchmark_pages.jsonl` | Page receipts, counts, costs, and latency |
| `eval/frozen/final_benchmark_ledger.jsonl` | Operation-level measured/projected ledger |
| `eval/frozen/final_benchmark_summary.json/.csv` | Clean, noisy, ugly, and blended metrics |
| `eval/frozen/ablation_summary.json/.csv` | Five supported frozen ablation arms and unsupported-arm disclosure |
| `eval/frozen/throughput_summary.json` | Repeatable local prototype throughput |
| `eval/frozen/cost_projection.csv` | 1K through 100M page projections |
| `docs/evaluation/frozen_test_methodology.md` | Dataset, denominators, labels, exclusions, reproduction |
| `docs/evaluation/ablation_analysis.md` | Interpretation and limitations |
| `docs/evaluation/final_cost_model.md` | Cost audit and provider price sources |
| `docs/evaluation/throughput_and_scalability.md` | Measured throughput and production boundary |
| `docs/submission/claims_register.md` | Approved and prohibited wording |
| `docs/licensing.md` | Installed dependency/license audit |
| `docs/security_and_phi.md` | Data, PHI, secret, and provider boundary audit |
| `docs/screenshots/day10_home.png` | Screenshot-safe UI proof |
| `eval/official/results/official_sample_summary.json` | PHI-safe official Tier B page-selection receipt |
| `eval/results/official_ub04_holdout_summary.json` | PHI-safe one-time official Tier C receipt |
| `eval/results/openrouter_qwen37_flash_smoke.json` | PHI-safe one-call synthetic crop-level OpenRouter integration receipt |
| `docs/evaluation/official_ub04_holdout.md` | Tier C denominator, results, failures, and evidence boundary |
| `docs/submission/final_submission_package.md` | Final evidence-backed narrative, tables, roadmap, and readiness |
| `docs/demo_script.md` | Three- and seven-minute scripts, judge Q&A, and backup plan |
