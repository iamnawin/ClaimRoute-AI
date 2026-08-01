# Exact Streamlit and evidence sequence

## Exact synthetic samples

- Clean: `data/generated/cms1500/clean/images/cms1500_42_0000.png`
- Ugly: `data/generated/cms1500/ugly/images/cms1500_42_0000.png`
- Mode: `Balanced`
- App: `http://localhost:8501`
- Start command: `\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py`

## Screen order

1. `recording_title.png` for the opening.
2. `architecture_flow.png` for the product explanation.
3. Streamlit Home with screenshot-safe mode enabled.
4. Select `Balanced` and `cms1500_42_0000 / clean`.
5. Run extraction; show the CMS-1500 route and Results funnel.
6. Open Field evidence for one bundled synthetic field.
7. Show final JSON and audit JSON download controls.
8. Select `cms1500_42_0000 / ugly`; use only the pretested result or committed receipt.
9. Show Benchmark, or use `benchmark_summary.png`.
10. Show `cost_and_latency.png`.
11. Show architecture PDF pages 5, 6, and 7.
12. Return to the title or clean Results screen for the close.

## Benchmark screen sequence

1. State `SYNTHETIC` before giving 99.716% and 99.936%.
2. State `OFFLINE_ORACLE` before discussing 1.905% escalation.
3. State `MEASURED external spend: $0`.
4. State `PROJECTED automated cost: $0.0000949/page`.
5. Move to official evidence and say it is separate.
6. State the Tier C provisional-denominator label verbatim.

## Architecture screen sequence

1. End-to-end page pipeline.
2. Local-first OCR and healthcare validation.
3. Cost Governor states and retry-first path.
4. Crop-only model boundary and failure handling.
5. Production-scale design, explicitly not deployed.
6. Provider portability chain and OpenRouter boundary.
7. Implemented prototype versus production roadmap.

## Backup visuals

- `day10_home.png`: committed synthetic-safe Streamlit home.
- `architecture_flow.png`: generated architecture flow.
- `benchmark_summary.png`: aggregate results only.
- `cost_and_latency.png`: aggregate cost and performance only.
- `recording_title.png`: opening/closing card.

No official images, crops, raw benchmark records, expected values, credentials, or PHI belong in
this folder or the recording.
