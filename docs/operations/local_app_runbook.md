# ClaimRoute local application runbook

## Purpose

Run the ClaimRoute Streamlit application against bundled synthetic claims or a local raster image.
The UI calls `engine.extract.run_page`; it contains no OCR, validation, or governor implementation.

## Install and start

From the repository root:

```powershell
uv venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
```

Local URL: `http://localhost:8501`

## Supported input

- PNG
- JPEG
- Single-page TIFF
- Maximum file size: 10 MB
- Maximum page count: 1

The default demo files are generated under `data/generated/` and contain zero PHI by
construction. Recommended examples:

- `cms1500_42_0000 / clean`
- `cms1500_42_0000 / ugly`

## Safety behavior

- Bundled synthetic examples may use the local deterministic `offline-oracle` test double.
- Uploads always call the pipeline with `run_escalate=False`.
- Real-provider mode is not exposed by the application.
- Official data is not bundled and must not be uploaded to a public deployment.
- Uploaded bytes and the temporary ledger are held only for the active run and cleaned locally.
- Extracted values are not written to application logs.
- Screenshot-safe mode is enabled by default and hides document pixels, crops, and values.
- Repeating the same document and mode reuses the session receipt instead of running twice.

## Screenshot-safe workflow

1. Keep `Screenshot-safe mode` enabled.
2. Use a bundled synthetic example.
3. Confirm the green zero-PHI notice is visible.
4. Capture only the start screen, funnel, cost tab, operating modes, or benchmark tab.
5. Do not capture an uploaded document unless its data classification is explicitly known.

Reference screenshot: `docs/screenshots/day10_home.png`.

## Verification

```powershell
python -m pytest tests/test_day10.py -q
python -m pytest tests/ -q
```

Day 10 manual workflow verification completed on 30 Jul 2026:

| Document | Mode | Fields | Local accepts | Retries | Escalations | Human review | API calls avoided |
|---|---|---:|---:|---:|---:|---:|---:|
| `cms1500_42_0000 / clean` | Balanced | 46 | 46 | 0 | 0 | 0 | 46 |
| `cms1500_42_0000 / ugly` | Balanced | 46 | 32 | 3 | 1 | 1 | 45 |

Both runs used zero external API calls. Offline-oracle cost is projected; measured API spend is $0.
The Benchmark tab now reads the frozen Day 11 synthetic summary from
`eval/frozen/final_benchmark_summary.json`; the accuracy-cost frontier remains Day 9 replay
calibration evidence and is labelled accordingly.

## Known limitations

- The app accepts one raster page per run; PDF and multi-page support are not implemented.
- The 120-second timeout is a post-run safety budget, not hard process cancellation.
- Bounding boxes are returned in processed-page coordinates. An overlay on a heavily degraded
  source image can be visually offset.
- Uploaded images remain local-only, so fields requiring Tier 2 finish at escalation or human review.
- Day 9 frontier metrics are replay calibration evidence. Current extraction still uses the locked v1.2
  runtime presets in `configs/pipeline.yaml`; UI work did not retune them.
- Human override workflow and authenticated review queues are not part of the hackathon UI.

## Deployment recommendation

Use this application locally or on an access-controlled demo machine with synthetic data. Do not
deploy it publicly for official claims until authentication, retention controls, hard worker
timeouts, audit storage, approved-provider controls, and official image-to-record mapping are
verified.

## Fallback demo plan

If local OCR startup fails, show `docs/screenshots/day10_home.png`, then present the committed
Day 9 mode comparison and Day 8 synthetic benchmark outputs. Do not substitute hard-coded field
results or claim that the offline oracle is a real provider.
