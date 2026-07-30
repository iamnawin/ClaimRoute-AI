# Day 11 final cost model

## Frozen blended result

| Cost component | USD/page | Evidence class |
|---|---:|---|
| Local preprocessing, OCR, validation, routing, and retry | $0.00007220 | MEASURED ledger usage priced with configured compute rate |
| External API invoice | $0.00000000 | MEASURED; zero calls |
| Selective offline-oracle provider equivalent | $0.00002270 | PROJECTED |
| Total automated processing | $0.00009490 | PROJECTED local + provider equivalent |
| Human review | $0.01966667 | CONFIGURED ASSUMPTION, reported separately |

Local OCR is local compute, not free. The local ledger prices elapsed stage time at the configured
`$0.05/vCPU-hour`. Human review uses `$0.03` per reviewed field and is not included in automated cost.
No exchange rate or infrastructure-overhead multiplier is used.

Input and output tokens remain separate in every oracle ledger row. The projected selective cost uses
GPT-5 nano prices of `$0.05/M` input tokens and `$0.40/M` output tokens. These were checked on
2026-07-30 against the [official OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5-nano).
Other configured comparison rates were checked against [Google AI pricing](https://ai.google.dev/gemini-api/docs/pricing),
the [Gemini 3.1 Flash-Lite model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite),
and [Anthropic's Claude Haiku 4.5 documentation](https://www-cdn.anthropic.com/files/4zrzovbb/website/3684c2faafb97418665782cea0001f439f74b1d2.pdf).
Provider commercial terms, data-use terms, taxes, caching, batch discounts, and negotiated pricing
are separate from this technical projection.

The run projected `$0.00068095` per correctly governor-resolved escalated field. This is high because
only three of 62 routed escalation attempts reached automated acceptance under the locked policy.
There is no finite ugly-tier value because zero ugly escalations were governor-resolved.

## Scale projection

| Pages | Local compute | Selective API | Total automated | Human review assumption |
|---:|---:|---:|---:|---:|
| 1,000 | $0.0722 | $0.0227 | $0.0949 | $19.67 |
| 1 million | $72.20 | $22.70 | $94.90 | $19,666.67 |
| 10 million | $722 | $227 | $949 | $196,666.67 |
| 100 million | $7,220 | $2,270 | $9,490 | $1,966,666.68 |

These are linear extrapolations from the frozen per-page denominator, not invoices or production
capacity estimates. They exclude storage, orchestration, redundancy, observability, networking,
support, and provider latency.
