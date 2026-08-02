# DEMO_CLICK_PATH.md - exact interaction order

Team DXtra AI - ClaimRoute AI

Follow this literally. Every click is timed against
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). Derived from
[`../../demo_assets/demo_sequence.md`](../../demo_assets/demo_sequence.md),
which stays canonical for the screen order.

## Before the recorder starts

```
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
```

| Setting | Value |
|---|---|
| URL | `http://localhost:8501` |
| Mode | `Balanced` |
| Screenshot-safe mode | **ON** |
| Browser zoom | 100% |
| Clean sample | `data/generated/cms1500/clean/images/cms1500_42_0000.png` |
| Degraded sample | `data/generated/cms1500/ugly/images/cms1500_42_0000.png` |

Pre-run both samples before recording. Confirm the clean run gives **46 local
accepts, 0 retries, 0 escalations, 0 review**. If the degraded run differs from
its committed receipt, use the receipt and say so - do not re-roll for a better
take.

## Click path

| # | Cue | Action | Screen |
|---|---|---|---|
| 1 | 0:00 | Show `recording_title.png` full screen | Title card |
| 2 | 0:35 | Show `architecture_flow.png` | Flow diagram |
| 3 | 1:15 | Switch to browser, Streamlit **Home** | Home, safe mode on |
| 4 | 1:20 | Select mode `Balanced` | Home |
| 5 | 1:30 | Select `cms1500_42_0000 / clean` | Home |
| 6 | 1:45 | Click **Run extraction** | Progress |
| 7 | 1:50 | Open **Results** tab | Results funnel |
| 8 | 2:10 | Point at the CMS-1500 route badge and the 46/46 local resolution | Results |
| 9 | 2:30 | Open **Field evidence**, pick one synthetic field | Evidence |
| 10 | 2:35 | Toggle screenshot-safe mode **OFF** for this bundled synthetic crop only | Evidence |
| 11 | 3:05 | Toggle screenshot-safe mode back **ON** | Evidence |
| 12 | 3:15 | Select `cms1500_42_0000 / ugly`, show the committed receipt | Results |
| 13 | 4:00 | Return to **Results**, show final JSON and audit JSON download controls | Results |
| 14 | 4:35 | Open **Benchmark**, or show `benchmark_summary.png` | Benchmark |
| 15 | 5:30 | Stay on aggregate visuals for the official Tier B and Tier C figures | Benchmark |
| 16 | 6:15 | Show `cost_and_latency.png` | Cost |
| 17 | 7:00 | Open `02_Architecture.pdf` at **page 6** | PDF |
| 18 | 7:40 | Go to **page 5**, then **page 7** | PDF |
| 19 | 8:10 | Return to `recording_title.png` or the clean Results screen | Close |

## Toggle discipline

Screenshot-safe mode is ON for the whole recording except step 10, and it goes
back ON at step 11 before anything else is shown. That single window is the only
place a crop appears, and it is a bundled synthetic crop with no PHI.

## Never on screen

- Organiser source documents, filenames, folders, or expected-output files
- Any crop, value, or record that is not from the two bundled synthetic samples
- `.env`, environment variables, API keys, terminal history
- Browser developer tools, email, chat, calendar, or password managers
- Desktop or application notifications
- Local absolute paths that identify a person or machine

## If you lose the thread

Stop talking, return to the last stable screen in the table above, and resume at
that cue. A two-second silence costs nothing. Narrating a screen you did not
intend to show costs a re-record.
