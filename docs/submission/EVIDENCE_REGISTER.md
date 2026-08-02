# Evidence register

Controlled list of every metric permitted to appear in `01_Executive_Summary.pdf`,
`02_Architecture.pdf`, or `05_Benchmark.xlsx`.

**Rule: no number enters a deliverable unless it has a row here.** A number without a row
is treated as fabricated, regardless of how confident its author is.

## Relationship to the other registers

This file maps **metric to source file**. It does not restate approved sentences.

- [`claims_register.md`](claims_register.md) is **canonical for wording**: approved
  phrasing and prohibited phrasing per claim. Where a value here is used in prose, the
  sentence must match the approved wording there.
- [`evidence_index.md`](evidence_index.md) is **canonical for the evidence file map**.

If this register and `claims_register.md` disagree on how a value may be described,
`claims_register.md` wins.

## Labels

`MEASURED`, `PROJECTED`, `ASSUMED`, `SYNTHETIC`, `OFFICIAL`, `OFFLINE_ORACLE`,
`LIVE_PROVIDER`, `CROP_LEVEL`, `ONE_CALL_SMOKE_TEST`, plus the control value
`PENDING_EVIDENCE_REVIEW` for anything not yet traced to a file on disk.

## Frozen synthetic benchmark

Source: `eval/frozen/final_benchmark_summary.json`, `blended` object.
Frozen git commit recorded in that file: `8324d600fa61ad7c6a57f7c70e3126232bd4e602`.
Basis: 90 pages, 30 documents, 3168 evaluated fields, 3255 routed fields.

| Metric | Value | Label | Source | Frozen | Approved | Owner | Notes |
|---|---:|---|---|---|---|---|---|
| Field accuracy | 0.99715909 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | Synthetic only. Never present as real-claim accuracy. |
| Critical-field accuracy | 0.99935525 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Automated exact-match rate | 0.98042929 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Primary local resolution rate | 0.93302611 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | Not "needs no review". See claims register. |
| Escalation rate | 0.01904762 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | Routing measured; provider behaviour not. |
| Local retry rate | 0.06697389 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Local retry resolution rate | 0.71559633 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Human review rate | 0.01812596 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Accept-with-flag rate | 0.10353303 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Pages evaluated | 90 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | Denominator for the XLSX "Total Pages Processed". |
| Documents evaluated | 30 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Evaluated fields | 3168 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Routed fields | 3255 | `MEASURED` `SYNTHETIC` | `final_benchmark_summary.json` | Yes | Yes | TBD | Differs from evaluated; do not interchange. |
| **Precision** | **not computed** | `PENDING_EVIDENCE_REVIEW` | none | n/a | **No** | TBD | **Required by organiser. Absent from all frozen evidence.** See blocker below. |
| **Recall** | **not computed** | `PENDING_EVIDENCE_REVIEW` | none | n/a | **No** | TBD | **Required by organiser. Absent from all frozen evidence.** See blocker below. |

## Throughput and latency

Source: `eval/frozen/throughput_summary.json`. Development workstation, not production.

| Metric | Value | Label | Source | Frozen | Approved | Owner | Notes |
|---|---:|---|---|---|---|---|---|
| Throughput | 9.20039858 pages/min | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | File sets `not_production_claim: true`. |
| Throughput | 552.02391479 pages/hr | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | Same run, derived. Not per-worker production. |
| Average latency/page | 6521.45659556 ms | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | XLSX "Average Latency". |
| p50 latency | 5269.271 ms | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | |
| p95 latency | 10824.586 ms | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | |
| Total elapsed | 586931.094 ms | `MEASURED` `SYNTHETIC` | `throughput_summary.json` | Yes | Yes | TBD | XLSX "Processing Time". |
| Pages/second | derived | `MEASURED` `SYNTHETIC` | derive from above | Yes | Yes | TBD | 9.20039858 / 60. Show the derivation. |
| Memory usage | not measured | `PENDING_EVIDENCE_REVIEW` | none | n/a | No | TBD | File states no RSS probe was added. Do not estimate. |
| Provider latency | not available | `PENDING_EVIDENCE_REVIEW` | none | n/a | No | TBD | Offline oracle is not a provider benchmark. |

## Cost

Source: `eval/frozen/final_benchmark_summary.json`, `eval/frozen/cost_projection.csv`,
`docs/evaluation/final_cost_model.md`.

| Metric | Value USD/page | Label | Source | Frozen | Approved | Owner | Notes |
|---|---:|---|---|---|---|---|---|
| Measured local compute | 0.0000722 | `MEASURED` usage + configured price | `final_benchmark_summary.json` | Yes | Yes | TBD | Never call local stages "free". |
| Projected API | 0.0000227 | `PROJECTED` `OFFLINE_ORACLE` | `final_benchmark_summary.json` | Yes | Yes | TBD | Projected from token counts at configured GPT-5 nano prices. Not invoiced spend. |
| Projected total automated | 0.0000949 | `PROJECTED` | `final_benchmark_summary.json` | Yes | Yes | TBD | Headline cost-per-page figure. |
| Measured external API spend | 0.00 | `MEASURED` | `final_benchmark_summary.json` | Yes | Yes | TBD | Zero external calls made. |
| Measured external API calls | 0 | `MEASURED` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| Projected cost per resolved escalated field | 0.00068095 | `PROJECTED` `OFFLINE_ORACLE` | `final_benchmark_summary.json` | Yes | Yes | TBD | |
| OCR cost (isolated) | not separately metered | `PENDING_EVIDENCE_REVIEW` | `final_benchmark_ledger.jsonl` | Yes | No | TBD | Organiser asks for OCR/GPU/CPU split. Ledger may support decomposition; not yet done. |
| GPU cost | not separately metered | `PENDING_EVIDENCE_REVIEW` | none | n/a | No | TBD | Prototype ran CPU-only. State honestly; do not enter $0 without explanation. |
| CPU cost | see local compute | `MEASURED` usage + configured price | `final_benchmark_ledger.jsonl` | Yes | No | TBD | Local compute figure is CPU. Confirm decomposition before splitting the cell. |
| Volume projections (1K to 100M) | see file | `PROJECTED` | `cost_projection.csv` | Yes | Yes | TBD | Planning only. Not proof of scale. |

## Official organiser data

Source: `eval/official/results/official_sample_summary.json`,
`eval/results/official_ub04_holdout_summary.json`. PHI-safe receipts only.

Never combine these with synthetic figures.

| Metric | Value | Label | Source | Frozen | Approved | Owner | Notes |
|---|---:|---|---|---|---|---|---|
| Tier B claim-page identification | 4/4 (1.0) | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | On deterministically linked evaluable items only. |
| Tier B attachment rejection | 15/15 (1.0) | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | |
| Tier C primary normalized fields | 36/42 (0.857) | `MEASURED` `OFFICIAL` | `official_ub04_holdout_summary.json` | Yes | Yes | TBD | Provisional-denominator label is mandatory. |
| Tier C critical fields | 16/18 (0.889) | `MEASURED` `OFFICIAL` | `official_ub04_holdout_summary.json` | Yes | Yes | TBD | |
| Containers processed | 30 | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | |
| Pages processed | 67 | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | |
| Local cost per input page | 0.0000291 | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | Official run; distinct from the synthetic figure. |
| External provider calls | 0 | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Yes | TBD | |
| Combined official result | withheld | `PENDING_EVIDENCE_REVIEW` | `official_sample_summary.json` | Yes | **No** | TBD | Harness set `combined_result: null` because a linkage abstained. **Do not compute a combined number by hand.** |
| Tier A field accuracy | 0.0 | `MEASURED` `OFFICIAL` | `official_sample_summary.json` | Yes | Handle with care | TBD | Real measured zero on official Tier A. Must not be hidden, and must not be presented as overall accuracy. See claims register. |

## Live provider integration smoke test

Source: `eval/results/openrouter_qwen37_flash_smoke.json`. Synthetic crop only; separate
from the frozen benchmark and official organiser evidence.

| Metric | Value | Label | Source | Frozen | Approved | Owner | Notes |
|---|---:|---|---|---|---|---|---|
| External provider calls | 1 | `MEASURED` `LIVE_PROVIDER` `SYNTHETIC` `CROP_LEVEL` `ONE_CALL_SMOKE_TEST` | `openrouter_qwen37_flash_smoke.json` | No | Yes | Naveen | Integration evidence only; not a performance benchmark. |
| Input tokens | 276 | `MEASURED` `LIVE_PROVIDER` | `openrouter_qwen37_flash_smoke.json` | No | Yes | Naveen | Provider receipt. |
| Output tokens | 77 | `MEASURED` `LIVE_PROVIDER` | `openrouter_qwen37_flash_smoke.json` | No | Yes | Naveen | Provider receipt; reasoning tokens are reported separately in the receipt. |
| Provider-reported cost | 0.00001829 USD | `MEASURED` `LIVE_PROVIDER` | `openrouter_qwen37_flash_smoke.json` | No | Yes | Naveen | One request using `qwen/qwen3.7-flash`; no model substitution. |
| End-to-end latency | 3856.93 ms | `MEASURED` `LIVE_PROVIDER` | `openrouter_qwen37_flash_smoke.json` | No | Yes | Naveen | One-call latency; not a reliability or SLA claim. |

## Prohibited

| Claim | Why |
|---|---|
| Any provider accuracy figure | Offline oracle is a test double. No real provider was benchmarked. |
| Combined official accuracy | Harness deliberately withheld it. |
| Synthetic and official merged | Different denominators and datasets. |
| Production throughput per worker | Only a development workstation was measured. |
| "Proven at 100M pages" | Projection, not demonstration. |
| "$0" or "free" for local stages | CPU is priced in `configs/prices.yaml` and ledgered. |
| "$0.0000949 is our API cost" | Projected, not invoiced. |

## Open blockers

1. **Precision and recall are required and do not exist.** The organiser's Benchmark
   Report explicitly lists both. No frozen artifact contains them; the summary carries
   `field_accuracy` and `critical_field_accuracy` only. Two honest options, and the
   decision has not been made:
   - Derive them. `eval/frozen/final_benchmark_rows.jsonl` holds per-field truth,
     candidate, and decision, which is likely sufficient. This requires a new eval
     harness, a definition of what counts as a positive, and a re-freeze. Out of scope
     for this documentation task.
   - Declare them honestly in the XLSX as not separately computed, and state which metric
     was used instead.

   Do not enter `field_accuracy` into a cell labelled Precision or Recall. They are
   different quantities.

2. **Component cost split (OCR / LLM / Vision / GPU / CPU) is partially unavailable.**
   The organiser asks for component-wise cost per page. Local compute is measured as one
   figure. Decomposition may be derivable from `final_benchmark_ledger.jsonl`, unverified.
   GPU was never used.

3. **Tier A official accuracy is 0.0.** Real, measured, and must not be quietly omitted.
   `claims_register.md` already prohibits any "all tiers supported" claim. The executive
   summary needs a deliberate, honest framing decision.
