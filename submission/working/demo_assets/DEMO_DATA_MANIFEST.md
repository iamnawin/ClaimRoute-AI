# DEMO_DATA_MANIFEST.md - what may appear on screen

Team DXtra AI - ClaimRoute AI

The allowlist is short and closed. If something is not on it, it does not go in
the recording.

## Permitted on screen

| Item | Path | Why it is safe |
|---|---|---|
| Clean CMS-1500 sample | `data/generated/cms1500/clean/images/cms1500_42_0000.png` | Synthetic, generated, zero PHI by construction |
| Degraded CMS-1500 sample | `data/generated/cms1500/ugly/images/cms1500_42_0000.png` | Same page, synthetically degraded |
| Committed receipts for those two samples | workspace output | PHI-safe by construction; no raw values persisted |
| Aggregate frozen benchmark figures | `eval/frozen/final_benchmark_summary.json` | Aggregates only, no per-record rows |
| Aggregate official tier figures | `eval/official/results/official_sample_summary.json`, `eval/results/official_ub04_holdout_summary.json` | PHI-safe receipts; counts and rates only |
| Live smoke receipt | `eval/results/openrouter_qwen37_flash_smoke.json` | One synthetic crop; no raw response persisted |
| Generated deliverables | `submission/final/01_Executive_Summary.pdf`, `02_Architecture.pdf`, `05_Benchmark.xlsx` | Built from the registered evidence |
| Backup visuals | `submission/demo_assets/*.png` | Vetted per [`SCREENSHOT_CHECKLIST.md`](SCREENSHOT_CHECKLIST.md) |

Both bundled samples are **synthetic and contain no PHI**. They are the only
document images that may be shown.

## Prohibited on screen - no exceptions

- PHI of any kind, real or realistic
- Organiser source documents, their filenames, folders, or directory listings
- Organiser expected-output files or any expected value
- Protected Tier A holdouts, and the consumed Tier C holdout (which must not be rerun)
- Any crop, OCR text, or field value not from the two bundled synthetic samples
- Raw provider responses or diagnostic crops
- `.env` contents, API keys, tokens, credentials, environment-variable output
- Terminal scrollback or command history
- Browser developer tools
- Email, chat, calendar, notifications
- Local absolute paths identifying a person or machine (for example `D:\AI-Workspace\...`)

## Screenshot-safe mode

ON for the entire recording, with exactly one exception: the single Field
evidence crop at cue 10 in [`DEMO_CLICK_PATH.md`](DEMO_CLICK_PATH.md), which is a
bundled synthetic crop. It goes back ON at cue 11 before any other screen.

## Numbers

Every figure spoken or shown must have a row in
[`docs/submission/EVIDENCE_REGISTER.md`](../../../docs/submission/EVIDENCE_REGISTER.md).

| Quantity | Value | Label |
|---|---:|---|
| Field accuracy | 99.716% | `MEASURED` `SYNTHETIC` |
| Critical-field accuracy | 99.936% | `MEASURED` `SYNTHETIC` |
| Precision | 99.904% | `MEASURED` `SYNTHETIC` (derived) |
| Recall | 98.136% | `MEASURED` `SYNTHETIC` (derived) |
| Automated exact-match rate | 98.043% | `MEASURED` `SYNTHETIC` - **not** recall |
| Measured external spend | $0.00 | `MEASURED` |
| Projected automated cost/page | $0.0000949 | `PROJECTED` |

A number with no row is treated as fabricated. If the register says
`PENDING_EVIDENCE_REVIEW`, say it is not measured rather than estimating.

## Verification before packaging

Frame-sample the exported MP4 at 30-second intervals and confirm nothing from the
prohibited list appears. `finalize_submission.ps1` can check the container, the
streams, and the file list; it cannot see what is inside the frames. That check
is human and it is mandatory.
