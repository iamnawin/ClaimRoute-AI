# Throughput and scalability evidence

## Measured prototype run

The frozen run processed 90 synthetic raster pages in 586.931 seconds on Windows, CPython 3.11.13,
an Intel64 development workstation, Tesseract 5.4.0, RapidOCR 1.4.4, and ONNX Runtime 1.28.0.
The first page was retained; no warm-up was excluded.

| Metric | Measured value |
|---|---:|
| Pages/minute | 9.200 |
| Pages/hour | 552.024 |
| Average latency/page | 6.521 s |
| p50 latency | 5.269 s |
| p95 latency | 10.825 s |
| Clean pages/minute | 13.456 |
| Noisy pages/minute | 11.209 |
| Ugly pages/minute | 6.152 |

Memory was not measured because no supported RSS probe was added to the frozen harness. Projected
provider latency is also unavailable: the offline oracle is deterministic local code and cannot
stand in for network/model latency.

## Scalability boundary

This is development-workstation prototype throughput, not a production SLA. The pipeline is
page-oriented and receipts are append-only, so a future deployment can distribute independent pages
across workers while keeping crop-only escalation and per-page ledgers. Production scale still
requires worker isolation, queues, durable audit storage, backpressure, provider rate-limit handling,
authentication, retention enforcement, monitoring, and load tests. No linear worker-count or
100-million-page throughput claim is approved until those components are tested.
