# ClaimRoute AI - exact 10-minute spoken script

Use the words below as written at approximately 124 words per minute. Bracketed text is an action,
not narration. Keep screenshot-safe mode enabled except when showing the two bundled synthetic
samples.

## 0:00-0:40 - Opening

[Show `recording_title.png`.]

“Healthcare claims look structured, but extracting them reliably is difficult. Scans arrive with
noise, skew, weak form lines, and healthcare-specific fields where a plausible string can still be
wrong. Sending every page to an expensive multimodal model increases cost and expands the data
boundary, even when local OCR already has enough evidence. ClaimRoute AI solves this by treating
intelligence as a budgeted resource. Every field takes the cheapest reliable path.”

## 0:40-1:25 - Product and innovation

[Show `architecture_flow.png`.]

“ClaimRoute processes each field through preprocessing, document routing, local OCR, layout
mapping, typed normalization, healthcare validation, and a Cost Governor. The governor does not
trust confidence alone. It combines confidence with layout, page quality, validator results, field
criticality, and attempt history. A reliable field is accepted locally. A policy-eligible middle
band may be accepted with a visible flag. An uncertain field gets one bounded local retry. Only an
eligible unresolved crop may cross the multimodal boundary. If the attempt budget is exhausted,
automation stops and the field routes to human review.”

## 1:25-2:05 - Start the live demo

[Open Streamlit at `http://localhost:8501`. Keep screenshot-safe mode on. Select `Balanced` and
`cms1500_42_0000 / clean`.]

“This interface is a thin judging layer over the same extraction service used by tests and
evaluation. I am using the bundled synthetic CMS-1500 sample, so there is zero PHI. Balanced is the
calibrated demo default. No real provider is configured or required.”

[Run extraction.]

## 2:05-2:50 - Clean result

[Open Results.]

“The system correctly routes this page as CMS-1500 and processes 46 fields. In the tagged clean
demo, all 46 fields resolve locally. There are zero retries, zero escalations, and zero human-review
outcomes. That means 46 potential API calls were avoided. This visible clean run did not invoke a
multimodal model. The point is not that every page is easy. The point is that an easy field should
not pay for intelligence it does not need.”

## 2:50-3:45 - Field evidence and healthcare validation

[Open Field evidence and choose one synthetic field. Disable screenshot-safe mode only for this
bundled synthetic crop.]

“For each field, ClaimRoute preserves the crop geometry, OCR candidate, normalized value, source
engine, validator verdicts, confidence evidence, and governor decision. Healthcare validation is a
first-class stage. NPI checksums, code rules, dates, arithmetic, formats, and cross-field checks can
reject a text candidate that looks confident but is structurally wrong. Every retry or escalated
answer is only another candidate. It must be grounded to the crop, normalized, validated, and sent
through the governor again before it can enter final output.”

## 3:45-4:35 - Degraded sample and stopping behavior

[Select `cms1500_42_0000 / ugly`. Use the pretested result or the committed synthetic receipt.]

“This degraded version demonstrates the selective path. Its committed receipt records three local
retries, one offline-oracle escalation, and one human-review outcome. The offline oracle is a
deterministic test double. It makes no network call and is not evidence of OpenAI, Gemini,
OpenRouter, or any other provider’s accuracy. The important engineering behavior is the boundary:
try a cheaper crop-level OCR variant first, escalate only an approved bounded crop, and stop when
the evidence still does not justify automated acceptance.”

## 4:35-5:15 - Structured output and audit receipt

[Return to Results. Show the final JSON and audit JSON download controls.]

“The final JSON contains document metadata and normalized fields for downstream use. The audit JSON
adds candidates, validation results, route decisions, processing paths, provenance, latency, token
metadata, and measured or projected cost bases. This separation keeps the operational output small
while preserving the evidence required to explain what happened, why a field was accepted, and why
automation stopped.”

## 5:15-6:20 - Frozen synthetic benchmark

[Open the Benchmark screen, or show `benchmark_summary.png`.]

“Now I will state the evidence boundary precisely. On the frozen 90-page synthetic test, Balanced
measured 99.716 percent exact field accuracy and 99.936 percent critical-field accuracy across 3,168
evaluated fields. Of 3,255 routed fields, 93.303 percent resolved at the primary local rung. The
local retry rung resolved 71.560 percent of the fields routed to retry. Only 1.905 percent reached
the offline-oracle escalation simulation, and 1.813 percent ended in human review. These accuracy
and routing results are measured on synthetic data. They are not real-claim or live-provider
performance.”

## 6:20-7:10 - Official evidence

[Keep the official values on the aggregate benchmark visual. Do not display organiser source
records or images.]

“Official evidence is separate and is never blended with the synthetic benchmark. On
deterministically linked evaluable Tier B items, ClaimRoute selected four out of four claim pages
and rejected fifteen out of fifteen attachments. A separate one-time Tier C UB-04 holdout measured
thirty-six out of forty-two primary normalized fields, or 85.714 percent; sixteen out of eighteen
critical fields, or 88.889 percent; and three out of three structural registrations. The required
label is: provisional denominator policy due to unavailable organiser clarification. The Tier C
holdout is consumed and must not be rerun.”

## 7:10-8:00 - Cost, throughput, and latency

[Show `cost_and_latency.png`.]

“Local stage usage measured and prices to 0.0000722 dollars per page at the assumed rate of five
cents per vCPU-hour. External calls and measured external spend were zero. The selective
API-equivalent cost is projected at 0.0000227 dollars per page from offline-oracle token estimates.
The projected automated total is 0.0000949 dollars per page. OCR, retry, LLM, Vision AI, CPU, and
GPU were not all separately metered, so ClaimRoute does not invent a component split. The
development workstation processed 90 pages in 586.931 seconds: 9.20 pages per minute, with 6.521
seconds mean latency, 5.269 seconds P50, and 10.825 seconds P95. This is prototype evidence, not a
production SLA.”

## 8:00-8:45 - Security and provider portability

[Show page 6 of `02_Architecture.pdf`.]

“The provider-neutral foundations are implemented. OpenAI- and Gemini-compatible adapters exist
behind the same crop contract. Live OpenRouter execution has been verified once, as a single-call
synthetic crop smoke test costing 0.00001829 dollars with no model substitution. That is
integration evidence, not a performance benchmark. OpenRouter is one
possible route after the Cost Governor, Model Selection Policy, and Provider Adapter Registry; it is
not a permanent dependency. Direct commercial APIs, enterprise proprietary models, and local
multimodal models are adapter extension paths. Real-provider escalation is disabled by default,
full-page requests are rejected, and credentials come from environment variables. These are
PHI-minimizing prototype controls, not a HIPAA compliance claim.”

## 8:45-9:30 - Scale and production roadmap

[Show page 5, then page 7, of `02_Architecture.pdf`.]

“The implemented prototype includes the page-oriented extraction pipeline, shared schemas,
provider adapters, validation, Cost Governor, structured outputs, append-only receipts, tests, and
the Streamlit interface. Scaling beyond the prototype requires an authenticated API gateway,
encrypted object storage, a durable queue, stateless workers, a governed provider gateway, an
encrypted results and audit database, an authenticated review service, monitoring, retention
enforcement, and load testing. The 100-million-page figure is a linear cost projection, not a
capacity proof.”

## 9:30-10:00 - Close

[Return to `recording_title.png` or the clean Results screen.]

“ClaimRoute’s innovation is not another OCR wrapper and not a model call on every page. It is the
control system around uncertainty: healthcare validation, retry-first routing, bounded model
access, explicit stopping, provenance, and cost evidence for every decision. The operator sets the
cost. ClaimRoute finds the accuracy. Every field takes the cheapest reliable path.”
