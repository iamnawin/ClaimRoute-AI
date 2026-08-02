# RECORDING_CHECKLIST.md - pre-flight and export gate

Team DXtra AI - ClaimRoute AI

Work top to bottom. Derived from
[`../../demo_assets/recording_checklist.md`](../../demo_assets/recording_checklist.md).

## 1. Machine hygiene

- [ ] Close email, chat, calendar, password managers, and any terminal showing environment output
- [ ] Enable Do Not Disturb / Focus Assist so no notification can surface mid-take
- [ ] Fresh browser window: no personal bookmarks, no account avatar, no extra tabs
- [ ] Desktop wallpaper and taskbar carry nothing identifying
- [ ] Screen resolution 1920x1080, browser zoom 100%

## 2. Application state

- [ ] `.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py` is up on `http://localhost:8501`
- [ ] Screenshot-safe mode is **ON**
- [ ] Mode is **Balanced**
- [ ] Clean sample pre-run: 46 local accepts, 0 retries, 0 escalations, 0 review
- [ ] Degraded sample pre-run; if it differs from the committed receipt, plan to show the receipt
- [ ] `02_Architecture.pdf` already open at page 6, and the backup PNGs are open in order

## 3. Audio

- [ ] Dedicated microphone selected explicitly in the recorder, not the default
- [ ] 10 seconds of room tone recorded and listened to: no fan, traffic, hum, or keyboard noise
- [ ] Peaks between -12 and -6 dBFS, no clipping
- [ ] Automatic gain control disabled if it pumps or lifts the noise floor
- [ ] Headphones on, to stop speaker feedback
- [ ] Practised at 115-125 words per minute with a beat after each headline number

## 4. During the take

- [ ] Follow [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) and [`DEMO_CLICK_PATH.md`](DEMO_CLICK_PATH.md) exactly
- [ ] Say `SYNTHETIC` before any accuracy figure
- [ ] Say `OFFLINE_ORACLE` before the escalation figure
- [ ] Say the Tier C provisional-denominator label verbatim
- [ ] Screenshot-safe mode goes back ON immediately after the single evidence crop
- [ ] Nothing from [`DEMO_DATA_MANIFEST.md`](DEMO_DATA_MANIFEST.md)'s prohibited list appears

## 5. Export gate - all must pass

- [ ] Exact filename `03_Demo.mp4`, saved to **`submission/final/03_Demo.mp4`**
- [ ] Duration between 7:00 and 10:00; target 8:30
- [ ] `ffprobe` reports **both** a video stream and an audio stream
- [ ] File plays start to finish without corruption or desync
- [ ] Speech present on both channels
- [ ] Frame-sample the export at 30-second intervals: no PHI, organiser records, secrets, notifications, or personal paths
- [ ] Numbers spoken match [`docs/submission/EVIDENCE_REGISTER.md`](../../../docs/submission/EVIDENCE_REGISTER.md); recall is 98.136%, **not** 98.043%

## 6. Hand off to packaging

- [ ] `.\scripts\validate_submission_readiness.ps1` reports **ELIGIBLE**
- [ ] Delete `submission/final/README_RECORDING_REQUIRED.txt`
- [ ] `.\scripts\finalize_submission.ps1` builds `submission/DXtraAI_HealthcareAIHackathon.zip`
- [ ] The ZIP contains exactly four root-level files and no folders

> The path is `submission/final/03_Demo.mp4`. An earlier draft of the canonical
> checklist said `submission/03_Demo.mp4`; that is the packaging output
> directory, not the artifact directory. `finalize_submission.ps1` reads from
> `submission/final/`.
