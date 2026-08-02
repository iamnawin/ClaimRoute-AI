# SCREENSHOT_CHECKLIST.md - backup visuals

Team DXtra AI - ClaimRoute AI

These PNGs let the demo continue when the live application will not cooperate.
They live in [`../../demo_assets/`](../../demo_assets/) and are **gitignored**
(`submission/demo_assets/*.png`), so they are produced locally and are not on
GitHub. Confirm each is present and clean before recording.

## Required visuals

| File | Used at | Must contain | Must never contain |
|---|---|---|---|
| `recording_title.png` | 0:00, 8:10 | Product name, team name, tagline | Employee IDs, emails, personal handles |
| `architecture_flow.png` | 0:35 | End-to-end pipeline and governor states | Provider credentials, internal hostnames |
| `day10_home.png` | Streamlit fallback | Home screen, screenshot-safe mode ON | Any real filename or crop |
| `benchmark_summary.png` | 4:35 fallback | Aggregate synthetic metrics with labels | Per-record rows, expected values, official images |
| `cost_and_latency.png` | 6:15 | Aggregate cost and performance | Raw ledger rows, API keys |

## Per-file inspection

For each PNG, open it at 100% and confirm:

- [ ] No PHI of any kind
- [ ] No organiser document, filename, folder, or expected-output value
- [ ] No API key, token, `.env` fragment, or credential
- [ ] No terminal history or environment-variable output
- [ ] No desktop or application notification captured in the frame
- [ ] No local absolute path that identifies a person or machine
- [ ] No browser developer tools panel
- [ ] Text is legible at 1920x1080 without zooming

## Label discipline

Any visual showing accuracy must carry or be narrated with `SYNTHETIC`. Any
visual showing escalation must carry or be narrated with `OFFLINE_ORACLE`. Any
visual showing cost must distinguish `MEASURED` from `PROJECTED`. If a PNG is
missing its label, narrate the label rather than showing the image bare.

## Freshness

- [ ] `benchmark_summary.png` figures match `docs/submission/EVIDENCE_REGISTER.md`
- [ ] If precision or recall appears in a PNG, it reads **99.904%** and **98.136%**
- [ ] No visual shows 98.043% in a cell or caption labelled Recall

Regenerate any stale visual before recording. A screenshot that disagrees with
the workbook is worse than no screenshot, because the judges will see both.

## Missing visuals

If a PNG cannot be produced, do not fabricate a replacement and do not
screenshot a different run to stand in for it. Narrate the section from
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) over the last stable screen and continue.
