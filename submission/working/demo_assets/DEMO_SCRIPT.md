# DEMO_SCRIPT.md - the 7 to 9 minute cut

Team DXtra AI - ClaimRoute AI
*Every field takes the cheapest reliable path.*

This is the **recording script**. It is the 10-minute narration in
[`../../demo_assets/10_minute_spoken_script.md`](../../demo_assets/10_minute_spoken_script.md)
tightened to a 8:30 target so the export stays comfortably inside the organiser's
10-minute cap. That file remains canonical for wording; where a sentence appears
in both, they say the same thing.

Deliver at roughly 120 words per minute. Bracketed lines are actions, not
narration. Pause for one beat after every headline number.

**Every metric below has a row in
[`docs/submission/EVIDENCE_REGISTER.md`](../../../docs/submission/EVIDENCE_REGISTER.md).
Do not improvise a number that is not on this page.**

---

## 0:00 - 0:35 Opening

[Show `recording_title.png`.]

"Healthcare claims look structured, but extracting them reliably is difficult.
Scans arrive with noise, skew, and weak form lines, and healthcare fields are the
kind where a plausible string can still be wrong. Sending every page to an
expensive multimodal model raises cost and widens the data boundary even when
local OCR already has enough evidence. ClaimRoute AI treats intelligence as a
budgeted resource. Every field takes the cheapest reliable path."

## 0:35 - 1:15 Product and innovation

[Show `architecture_flow.png`.]

"Each field moves through preprocessing, document routing, local OCR, layout
mapping, typed normalization, healthcare validation, and a Cost Governor. The
governor does not trust confidence alone. It combines confidence with layout,
page quality, validator verdicts, field criticality, and attempt history. A
reliable field is accepted locally. A policy-eligible middle band is accepted
with a visible flag. An uncertain field gets one bounded local retry. Only an
eligible unresolved crop may cross the multimodal boundary. When the attempt
budget is exhausted, automation stops and the field routes to human review."

## 1:15 - 1:50 Start the live demo

[Open Streamlit at `http://localhost:8501`. Screenshot-safe mode ON. Select
`Balanced` and `cms1500_42_0000 / clean`.]

"This interface is a thin judging layer over the same extraction service the
tests and the evaluation harness use. This is a bundled synthetic CMS-1500
sample, so there is zero PHI. Balanced is the calibrated demo default, and no
real provider is configured or required."

[Run extraction.]

## 1:50 - 2:30 Clean result

[Open Results.]

"The page routes correctly as CMS-1500 and 46 fields are processed. In the
tagged clean demo all 46 resolve locally: zero retries, zero escalations, zero
human review. Forty-six potential API calls were avoided, and this run invoked no
multimodal model at all. The point is not that every page is easy. The point is
that an easy field should not pay for intelligence it does not need."

## 2:30 - 3:15 Field evidence and healthcare validation

[Open Field evidence, choose one synthetic field. Disable screenshot-safe mode
**only** for this bundled synthetic crop, then turn it back on.]

"For every field ClaimRoute keeps the crop geometry, OCR candidate, normalized
value, source engine, validator verdicts, confidence evidence, and governor
decision. Healthcare validation is a first-class stage: NPI checksums, code
rules, dates, arithmetic, formats, and cross-field checks can reject a candidate
that looks confident but is structurally wrong. A retried or escalated answer is
only another candidate. It must be grounded to the crop, normalized, validated,
and passed through the governor again before it can enter final output."

## 3:15 - 4:00 Degraded sample and stopping behaviour

[Select `cms1500_42_0000 / ugly`. Use the pretested result or the committed
receipt. Do not improvise if it differs.]

"The degraded version shows the selective path. Its committed receipt records
three local retries, one offline-oracle escalation, and one human-review outcome.
The offline oracle is a deterministic test double. It makes no network call and
is not evidence of any provider's accuracy. The engineering behaviour that
matters is the boundary: try a cheaper crop-level OCR variant first, escalate
only an approved bounded crop, and stop when the evidence still does not justify
automated acceptance."

## 4:00 - 4:35 Structured output and audit receipt

[Return to Results. Show the final JSON and audit JSON download controls.]

"The final JSON carries document metadata and normalized fields for downstream
use. The audit JSON adds candidates, validation results, route decisions,
processing paths, provenance, latency, token metadata, and measured or projected
cost bases. The operational output stays small while the evidence needed to
explain every acceptance and every stop is preserved."

## 4:35 - 5:30 Frozen synthetic benchmark

[Open the Benchmark screen, or show `benchmark_summary.png`.]

"Now the evidence boundary, stated precisely. On the frozen 90-page synthetic
test, Balanced measured 99.716 percent exact field accuracy and 99.936 percent
critical-field accuracy across 3,168 evaluated fields. Precision is 99.904
percent and recall is 98.136 percent, derived per field from the frozen rows:
3,106 true positives, 3 false positives, 59 false negatives. Of 3,255 routed
fields, 93.303 percent resolved at the primary local rung, and the retry rung
resolved 71.560 percent of what reached it. Only 1.905 percent reached the
offline-oracle escalation simulation and 1.813 percent ended in human review.
These are measured on synthetic data. They are not real-claim or live-provider
performance."

> Say `SYNTHETIC` before the accuracy figures and `OFFLINE_ORACLE` before the
> escalation figure. Precision and recall are **derived**, not re-benchmarked;
> if asked, the derivation is TP/(TP+FP) and TP/(TP+FN) over the frozen rows.
> 98.043 percent is the automated exact-match rate, a **different** number from
> recall. Never present one as the other.

## 5:30 - 6:15 Official evidence

[Keep official values on the aggregate visual. Never display organiser source
records, filenames, or images.]

"Official evidence is separate and is never blended with the synthetic benchmark.
On deterministically linked evaluable Tier B items, ClaimRoute selected four out
of four claim pages and rejected fifteen out of fifteen attachments. A separate
one-time Tier C UB-04 holdout measured thirty-six of forty-two primary normalized
fields, sixteen of eighteen critical fields, and three of three structural
registrations. The required label is: provisional denominator policy due to
unavailable organiser clarification. That holdout is consumed and must not be
rerun."

## 6:15 - 7:00 Cost, throughput, and latency

[Show `cost_and_latency.png`.]

"Local stage usage measured and priced to 0.0000722 dollars per page at an
assumed five cents per vCPU-hour. Measured external spend was zero. The selective
API-equivalent cost is projected at 0.0000227 dollars per page from
offline-oracle token estimates, for a projected automated total of 0.0000949
dollars per page. OCR, retry, LLM, Vision, CPU and GPU were not all separately
metered, so ClaimRoute does not invent a component split. The development
workstation processed 90 pages in 586.931 seconds: 9.20 pages per minute, 6.521
seconds mean latency, 5.269 P50, 10.825 P95. Prototype evidence, not a
production SLA."

## 7:00 - 7:40 Security and provider portability

[Show page 6 of `02_Architecture.pdf`.]

"The provider-neutral foundations are implemented: OpenAI- and Gemini-compatible
adapters sit behind the same crop contract. Live OpenRouter execution has been
verified once, as a single-call synthetic crop smoke test costing 0.00001829
dollars with no model substitution. That is integration evidence, not a
performance benchmark. OpenRouter is one route after the Cost Governor, Model
Selection Policy, and Provider Adapter Registry, not a permanent dependency.
Real-provider escalation is off by default, full-page requests are rejected, and
credentials come from environment variables. These are PHI-minimizing prototype
controls, not a HIPAA compliance claim."

## 7:40 - 8:10 Scale and production roadmap

[Show page 5, then page 7, of `02_Architecture.pdf`.]

"The implemented prototype covers the page-oriented pipeline, shared schemas,
provider adapters, validation, Cost Governor, structured outputs, append-only
receipts, tests, and the Streamlit interface. Going beyond it needs an
authenticated gateway, encrypted object storage, a durable queue, stateless
workers, a governed provider gateway, an encrypted audit database, an
authenticated review service, monitoring, retention enforcement, and load
testing. The hundred-million-page figure is a linear cost projection, not a
capacity proof."

## 8:10 - 8:30 Close

[Return to `recording_title.png` or the clean Results screen.]

"ClaimRoute's innovation is not another OCR wrapper, and not a model call on
every page. It is the control system around uncertainty: healthcare validation,
retry-first routing, bounded model access, explicit stopping, provenance, and
cost evidence for every decision. The operator sets the cost. ClaimRoute finds
the accuracy. Every field takes the cheapest reliable path."

---

## Timing guard

| Checkpoint | Target | Hard ceiling |
|---|---|---|
| End of clean result | 2:30 | 3:00 |
| End of frozen benchmark | 5:30 | 6:15 |
| End of cost section | 7:00 | 7:45 |
| Export length | 8:30 | **10:00** |

If you are past a hard ceiling, cut from the roadmap section first, then the
architecture page turns. Never cut the evidence-boundary sentences: the
`SYNTHETIC` label, the offline-oracle disclaimer, or the Tier C provisional
denominator wording.
