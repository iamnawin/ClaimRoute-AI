# Day 11 frozen-test methodology

## Evaluation boundary

The authoritative Day 11 result is anchored to Git commit
`8324d600fa61ad7c6a57f7c70e3126232bd4e602` and architecture v1.2. The harness froze
configuration and environment metadata before reading the test results. No threshold, validator,
governor, preprocessing, retry, or provider-policy setting was changed afterward.

The dataset is deterministic synthetic CMS-1500 and UB-04 data generated with seed 42. The frozen
test split contains 30 claim documents rendered once in each of three tiers: 90 pages and 3,168
ground-truth fields. The 20 calibration documents and 30 test documents have zero overlap. The test
split SHA-256 is `4d70876b676cc06a4b2558e3d1a49450f826803c4b8d85f89041b91c80d2be5a`.

Official-looking files under the workspace `Images & Output` directory were excluded. Their
image-to-output mapping, allowed purpose, retention requirements, PHI status, and external-provider
permissions remain unconfirmed; they are therefore test-data candidates, not authoritative scoring
evidence.

## Reproduction

From the repository root and the frozen environment:

```powershell
.venv\Scripts\python.exe -m eval.day11_frozen freeze
.venv\Scripts\python.exe -m eval.day11_frozen run
.venv\Scripts\python.exe -m eval.day11_frozen summarize
```

The run is append-safe and resumable. Summary generation refuses an incomplete run, duplicate page
or field keys, nonzero measured API spend, or a dataset-integrity mismatch. Exact configuration and
environment evidence is in `eval/frozen/config_hashes.json`, `environment_manifest.json`, and
`frozen_manifest.json`.

## Metric rules

- Field accuracy is normalized exact match over the 3,168 expected ground-truth fields.
- A truly absent optional field is excluded from routing denominators unless the engine hallucinates
  a value. This rule is identical for clean, noisy, ugly, and blended summaries.
- Critical-field accuracy uses the frozen field-policy criticality labels.
- Routing rates use routed fields as their denominator (3,255, including routed optional boxes).
- `automated_exact_match_rate` counts exact fields that end in an automated terminal state; an exact
  value sent to human review is not credited as automated resolution.
- Latency and local cost are aggregated from the same 90 page receipts. The first page is retained;
  no warm-up sample was removed.

## Evidence labels

| Label | Meaning |
|---|---|
| MEASURED | Synthetic accuracy/routing, local elapsed time, local compute ledger, counts, and actual external spend of `$0` |
| PROJECTED | Offline-oracle token cost, selective-provider cost, and volume extrapolations |
| CONFIGURED ASSUMPTION | `$0.05/vCPU-hour`, `$0.03/human-reviewed field`, and the provider prices in `configs/prices.yaml` |
| UNVERIFIED | Real-provider accuracy/latency, real-claim generalization, production throughput, official-dataset mapping/governance |

The offline oracle is a deterministic test double. It makes no network request and is not evidence
of any provider's accuracy. Its token estimate is priced as GPT-5 nano only to model a selective
field-crop cost boundary.
