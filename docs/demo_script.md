# ClaimRoute hackathon demo script

## Before the session

1. Start the app with `.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py`.
2. Open `http://localhost:8501`.
3. Keep screenshot-safe mode enabled until the audience confirms the bundled synthetic document.
4. Confirm `Balanced` and `cms1500_42_0000 / clean` are selected.

## Five-minute walkthrough

### Run the clean claim

Select the bundled clean CMS-1500 and run extraction.

Say: "This is synthetic data with zero PHI. The UI calls the same extraction spine used by our
tests and evaluation harnesses. No results are hard-coded."

Open Results and point to:

- 46 fields detected
- 46 locally accepted
- 46 API calls avoided
- measured local compute cost
- measured API cost of $0

### Inspect one field

Open Field evidence and choose a field. Disable screenshot-safe mode only because this is a
bundled synthetic document.

Show the crop, OCR candidate, validator verdicts, engine provenance, and governor decision path.

### Show degradation behavior

Select `cms1500_42_0000 / ugly` and run Balanced again.

Point out the actual receipt: 3 local retries, 1 selective offline-oracle escalation, 1 human-review
outcome, and 45 API calls avoided. Explain that the offline-oracle cost is projected and external
API spend remains measured at $0.

### Explain operating modes

Open Operating modes. The table is loaded from the Day 9 calibration output.

- Economy minimizes projected cost and escalation.
- Balanced is the recommended hackathon default.
- Strict Accuracy prioritizes verified correctness and permits fewer flagged acceptances, which
  can increase human review.

### Show benchmark evidence

Open Benchmark and state the label exactly: "Synthetic benchmark with offline-oracle projection."

Show clean, noisy, ugly, blended, critical-field accuracy, escalation, human review, projected
cost per page, and the accuracy-cost frontier. Do not call it the final official benchmark.

### Export the receipt

Return to Results and download final JSON and audit JSON. Explain that the audit export preserves
field routing, candidates, validation, cost basis, and provenance.

## Judge questions

**Does this send PHI to an AI provider?**

Not in this demo. Uploaded documents are structurally local-only. Bundled synthetic examples can
use the deterministic offline oracle, which makes no external call.

**Are the cost figures measured?**

Local compute is measured. External API spend is measured at $0. Offline-oracle API cost and scale
projections are explicitly labeled PROJECTED. Mode thresholds are labeled CONFIGURED ASSUMPTION.

**Is the benchmark official?**

No. It is a synthetic calibration benchmark. Official dataset use remains blocked until role,
mapping, retention, and PHI handling are confirmed.

## Fallback

If the live pipeline is unavailable, show `docs/screenshots/day10_home.png` and the committed Day 8
and Day 9 evidence. Do not show official claims or substitute hard-coded extraction results.
