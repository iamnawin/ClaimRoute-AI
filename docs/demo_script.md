# ClaimRoute hackathon demo and judge runbook

## Before the session

1. From the repository root, run
   `.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py`.
2. Open `http://localhost:8501`.
3. Keep screenshot-safe mode enabled until the bundled synthetic document is confirmed.
4. Select `Balanced` and `cms1500_42_0000 / clean`.
5. Keep `cms1500_42_0000 / ugly`, the frozen summary, and the home screenshot ready as backups.
6. Do not configure or depend on a real external provider.

## Three-minute script

**0:00–0:20 — Problem**

“Healthcare claims contain many structured fields, but scan quality varies. Sending every page to
an expensive model is wasteful, increases the data boundary, and still does not guarantee a valid
claim.”

**0:20–0:40 — Product**

“ClaimRoute AI is a cost-governed claims extraction engine. It asks a different question for every
field: does this field deserve an AI call at all?” Point to the pipeline banner.

**0:40–1:05 — Run the clean sample**

Select Balanced and the bundled synthetic CMS-1500 clean sample, then run extraction. Say: “This is
synthetic with zero PHI. Balanced is the calibrated demo default. The UI calls the same pipeline as
the tests and benchmark.”

**1:05–1:30 — Route and results**

Show CMS-1500 routing and the Results tab. “The tagged demo processes 46 fields. All 46 resolve
locally: zero retries, zero escalations, zero human reviews. This visible clean run did not invoke
AI.”

**1:30–1:55 — Validation and governor**

Open Field evidence. Show the OCR candidate, typed normalization, healthcare validator verdicts,
provenance, and governor decision. “Confidence alone is not enough. NPI, code, date, arithmetic,
format, and cross-field rules influence the route.”

**1:55–2:15 — Retry and escalation evidence**

Use the committed ugly-sample receipt or a pretested second run. “Across degraded inputs, ClaimRoute
tries a local crop retry before selective escalation. This example records 3 retries, 1 offline-
oracle escalation, and 1 human-review outcome. The oracle is a deterministic test double, not a
real provider.”

**2:15–2:35 — JSON, cost, latency**

Show both download buttons and Cost & performance. “The final JSON carries structured output; the
audit JSON carries candidates, validators, decisions, provenance, and cost basis. The tagged clean
demo measured $0 external spend and 8.629 seconds.”

**2:35–2:55 — Benchmark**

Open Benchmark. “On 90 frozen synthetic pages, Balanced measured 99.716% field accuracy, 99.936%
critical accuracy, 93.303% primary local resolution, 1.905% offline-oracle routing, and a projected
automated cost of $0.0000949 per page. Separate official Tier C evidence measured 85.714% primary
normalized accuracy under a provisional denominator.”

**2:55–3:00 — Close**

“Every field takes the cheapest reliable path.”

## Seven-minute extended script

**0:00–0:35 — Problem and stakes**

Explain that claims combine fixed layouts, degraded scans, healthcare-specific types, and critical
fields. A plausible OCR string can still be an invalid NPI, date, code, or amount. Calling a model
for every page raises cost and unnecessary exposure without guaranteeing correctness.

**0:35–1:05 — Differentiation**

Introduce ClaimRoute and the question “Does this field deserve an AI call at all?” Walk through the
pipeline banner. Emphasize that the innovation is governed routing, not merely OCR or a model API.

**1:05–1:35 — Policy modes**

Open Operating modes. Explain Economy, Balanced, and Strict Accuracy as policy points on an
accuracy-cost frontier. State that frontier values are replay-calibration evidence and configured
assumptions; Balanced is the demo default.

**1:35–2:20 — Clean synthetic run**

Run `cms1500_42_0000 / clean`. Confirm synthetic/zero-PHI status and CMS-1500 routing. Show 46 fields,
46 local accepts, 0 retries, 0 escalations, 0 human reviews, and 46 API calls avoided. Explicitly
say: “No AI was invoked by this clean run.”

**2:20–3:10 — Field evidence and healthcare validation**

Open one field. Show primary OCR, normalization, validator verdicts, confidence, source engine, and
governor trail. Explain criticality and `ACCEPT_WITH_FLAG`. A candidate must pass the appropriate
healthcare rules; every retry or escalated answer is only another candidate and must re-enter
validation.

**3:10–3:55 — Local retry and multimodal boundary**

Show the ugly sample or its committed receipt. Explain local crop retry, form-ink dropout, and the
attempt budget. Then explain selective escalation: approved field, approved provider, bounded crop,
strict JSON, grounding, typed normalization, validation, and governor re-entry. Full pages are
rejected. Raw responses are represented only by SHA-256 evidence. No real-provider smoke test was
completed.

**3:55–4:35 — Structured outputs**

Download final JSON and audit JSON. Explain the final-output example as document metadata plus
normalized fields. Explain the audit example as the funnel, per-field candidates and validation,
decision path, latency, token usage, and measured/projected cost bases.

**Final JSON shape**

```json
{
  "document": {"document_id": "cms1500_42_0000", "document_type": "cms1500"},
  "operating_mode": "Balanced",
  "fields": {"patient_name": {"value": "<synthetic value>", "state": "ACCEPT"}}
}
```

**Audit JSON shape**

```json
{
  "funnel": {"fields_detected": 46, "accepted_locally": 46, "locally_retried": 0,
             "escalated": 0, "human_review": 0, "api_calls_avoided": 46},
  "fields": [{"field_name": "patient_name", "processing_path": [],
              "validation": [], "governor_decisions": []}],
  "costs": {"measured_api": {"value_usd": 0.0, "basis": "MEASURED"}}
}
```

The UI downloads contain the full synthetic values and evidence. The abbreviated examples above
show structure without presenting a hard-coded demo as a live extraction.

**4:35–5:30 — Synthetic benchmark**

Open Benchmark. State every label: 99.716% exact field and 99.936% critical accuracy are measured on
the frozen synthetic test; 1.905% escalation uses an offline oracle; measured external spend is $0;
$0.0000227/page API and $0.0000949/page automated totals are projected. Show 9.20 pages/minute,
6.521-second mean, 5.269-second P50, and 10.825-second P95 as workstation prototype evidence.

**5:30–6:10 — Official evidence**

Keep it separate. Tier B selected 4/4 claim pages and rejected 15/15 attachments. Tier C measured
36/42 primary normalized fields, 36/63 extended fields, 16/18 critical fields, and 3/3
registrations with zero external calls. State the required label: “Provisional denominator policy
due to unavailable organiser clarification.” Do not blend this with synthetic accuracy.

**6:10–6:40 — Scale and security boundary**

Explain that page-oriented workers, resumable receipts, adapters, and ledgers are implemented. API
gateway, auth, queue, object storage, horizontally scaled workers, durable results, review service,
retention enforcement, and load testing are production design—not deployed infrastructure. Call the
current posture prototype controls and PHI-minimizing; make no HIPAA compliance claim.

**6:40–7:00 — Close**

“ClaimRoute treats AI as a budgeted resource, isolates external processing to the few fields that
earn it, and keeps a receipt for every decision. Every field takes the cheapest reliable path.”

Alternative closing line: “The operator sets the cost. ClaimRoute finds the accuracy.”

## Judge questions and spoken answers

1. **Why not use a multimodal LLM for every page?** Local OCR already resolves most fields. Full-page
   model calls add cost and data exposure without guaranteeing healthcare-valid output.
2. **What makes this an AI engineering solution?** It engineers uncertainty, policy, validation,
   routing, model boundaries, grounding, provenance, and cost—not just a prompt.
3. **Where is AI actually used?** Primary OCR is local ML. A multimodal model is available only for
   selected uncertain field crops after local retry; the benchmark used an offline oracle.
4. **Why is external API spend zero?** No real provider was called. The frozen run used a local
   deterministic test double, so external calls and measured spend were zero.
5. **How was projected API cost calculated?** Separate input/output token estimates were priced with
   configured provider rates only for routed crops, then divided by all pages.
6. **Why is synthetic accuracy higher than official accuracy?** Synthetic layouts match the
   engineered templates. Official legacy monochrome forms have different geometry and a provisional
   scoring denominator, so the results are separate.
7. **Did you use real PHI?** The benchmark and demo are synthetic. Official source material stayed
   local/read-only, and only PHI-safe aggregate receipts were committed.
8. **Did you test real providers?** No. Adapters and failure handling are implemented and tested, but
   no real-provider smoke test was completed.
9. **What happens when the model hallucinates?** Strict JSON parsing, crop grounding, typed
   normalization, healthcare validators, and governor re-entry reject unsupported candidates.
10. **What happens when OCR confidence is wrong?** Confidence is fused with layout, quality, pattern,
    validator results, and attempt history. Critical failures can retry, escalate, or reach review.
11. **How are critical fields different?** Field policy assigns criticality and stricter routing;
    unresolved critical fields cannot be silently accepted.
12. **How does retry save money?** It spends a small amount of local compute on one crop before any
    provider route. The frozen retry rung resolved 71.560% of routed retries.
13. **How does it scale to millions of pages?** Independent page jobs can run on stateless workers,
    but queues, storage, auth, rate limits, observability, and load tests are roadmap work.
14. **What is implemented versus future architecture?** The extraction pipeline, adapters, ledger,
    receipts, tests, and UI are implemented. Production platform services are a design.
15. **Why Streamlit?** It is a thin, fast judging interface over the same extraction service; it does
    not duplicate OCR, validation, or governor logic.
16. **How is human review handled?** The engine routes exhausted exceptions to `HUMAN_REVIEW` and
    defines audited overrides. An authenticated review queue is not yet implemented.
17. **How are token costs measured?** Adapters retain input/output token metadata separately. In the
    offline run token usage drives a projection, not an invoice.
18. **What does final JSON contain?** Document metadata and normalized field outputs. Audit JSON adds
    candidates, validators, routing decisions, provenance, latency, tokens, and cost basis.
19. **What are the biggest limitations?** Synthetic generalization, no live-provider evidence,
    provisional official denominator, limited Tier D, one-page UI, and no production security layer.
20. **Why is this better than basic OCR?** It turns text candidates into typed, validated,
    explainably routed claim fields and records when automation should stop.

## Screenshot capture plan

Keep screenshot-safe mode on and use only bundled synthetic data.

1. Home: zero-PHI notice, Balanced selected, pipeline banner.
2. Clean Results: CMS-1500 route and 46/46 local funnel.
3. Field evidence: one synthetic field’s validators and governor trail.
4. Cost & performance: measured versus projected labels and latency.
5. Benchmark: frozen synthetic warning and blended results.
6. Operating modes: Economy, Balanced, Strict Accuracy and evidence-boundary caption.
7. Optional ugly Results: 3 retries, 1 offline-oracle escalation, 1 review.

Existing fallback image: `docs/screenshots/day10_home.png`.

## Backup demo checklist

- [ ] Local app command copied and tested.
- [ ] `cms1500_42_0000 / clean` selected in Balanced mode.
- [ ] Optional ugly sample pretested; do not improvise with another document.
- [ ] `docs/screenshots/day10_home.png` open locally.
- [ ] `docs/submission/final_submission_package.md` open at architecture and tables.
- [ ] `eval/frozen/final_benchmark_summary.json` open read-only.
- [ ] `docs/evaluation/official_ub04_holdout.md` open read-only.
- [ ] Final/audit JSON structural examples ready above.
- [ ] No provider key or internet dependency configured.

## Failure talk tracks

**If Streamlit fails:** “The live interface is a thin layer over the tested extraction service. I’ll
use the committed screenshot and immutable receipts; these are the same evidence sources loaded by
the UI.” Show the architecture, benchmark table, and JSON shapes.

**If OCR differs slightly:** “OCR timing and candidates can vary by local environment. I will not
substitute a better-looking result. The submission claim comes from the frozen commit, environment
manifest, and immutable 90-page receipt.” Switch to committed evidence.

**If there is no internet:** “The judged path is deliberately local and synthetic. No external API
is required; the multimodal boundary is demonstrated by the deterministic offline oracle and audit
evidence.” Continue locally.

## Final demo checklist

- [ ] Confirm branch `integrate/final-submission` and tag `hackathon-final-rc1`.
- [ ] Start from the repository root with the exact command below.
- [ ] Keep screenshot-safe mode on except for an explicitly confirmed bundled synthetic crop.
- [ ] Say that the clean run resolves 46/46 locally and does not invoke AI.
- [ ] Label the broader retry/escalation evidence `SYNTHETIC` and `OFFLINE_ORACLE`.
- [ ] Label local/API/scale costs `MEASURED`, `PROJECTED`, or `ASSUMED` correctly.
- [ ] Separate synthetic and official evidence.
- [ ] Call performance a workstation prototype measurement.
- [ ] Call scale a production design.
- [ ] Close with “Every field takes the cheapest reliable path.”

## Exact commands

```powershell
cd "D:\AI-Workspace\hackathon 2026\claims-engine"
git switch integrate/final-submission
git status --short --branch
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
```

The official Tier C holdout is consumed and must not be rerun.
