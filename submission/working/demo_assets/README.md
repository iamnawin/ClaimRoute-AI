# Recording package

Team DXtra AI - ClaimRoute AI

Everything needed to record `submission/final/03_Demo.mp4`. The recording is the
**only** remaining manual step in the submission; the two PDFs and the workbook
are generated and validated.

## Read in this order

| # | Document | Purpose |
|---|---|---|
| 1 | [`DEMO_DATA_MANIFEST.md`](DEMO_DATA_MANIFEST.md) | What may and may not appear on screen. Read first. |
| 2 | [`RECORDING_CHECKLIST.md`](RECORDING_CHECKLIST.md) | Machine, app, and audio pre-flight, plus the export gate. |
| 3 | [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) | The 7-9 minute narration, 8:30 target. |
| 4 | [`DEMO_CLICK_PATH.md`](DEMO_CLICK_PATH.md) | Exact click order, timed to the script. |
| 5 | [`FAILURE_TALK_TRACKS.md`](FAILURE_TALK_TRACKS.md) | What to say when something breaks. |
| 6 | [`SCREENSHOT_CHECKLIST.md`](SCREENSHOT_CHECKLIST.md) | Backup visuals and their inspection. |

## Relationship to `submission/demo_assets/`

[`../../demo_assets/`](../../demo_assets/) holds the canonical narration
(`10_minute_spoken_script.md`), the canonical screen order
(`demo_sequence.md`), the original checklist, and the PNG visuals. Those files
are the source of truth for wording and sequence.

This folder is the **working cut**: the same material tightened to 8:30 and split
into the six task-shaped documents a person actually needs while recording. Where
the two disagree on a number, `docs/submission/EVIDENCE_REGISTER.md` decides.

The PNGs are referenced in place. They are gitignored and are not duplicated here.

## After recording

```powershell
# 1. place the file
#    submission/final/03_Demo.mp4

# 2. confirm readiness
.\scripts\validate_submission_readiness.ps1

# 3. remove the blocker marker
Remove-Item submission\final\README_RECORDING_REQUIRED.txt

# 4. build the email ZIP
.\scripts\finalize_submission.ps1
```

The ZIP must contain exactly four root-level files and no folders.
