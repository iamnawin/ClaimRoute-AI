# Submission claims register

| Proposed claim | Evidence | Status | Approved wording | Avoid |
|---|---|---|---|---|
| Frozen accuracy | Final benchmark summary | Verified synthetic | Balanced achieved 99.716% exact field accuracy and 99.936% critical-field accuracy on 90 frozen synthetic pages. | ClaimRoute achieves 99.716% on real healthcare claims. |
| Local resolution | Final benchmark summary | Verified synthetic | 93.303% of routed fields resolved at the primary local rung on the frozen synthetic run. | 93.303% of all production claims need no review. |
| Selective escalation | Final benchmark summary | Verified routing; projected provider | 1.905% of routed fields reached selective offline-oracle escalation. | Only 1.905% will call a real provider in production. |
| API spend | Ledger and summary | Verified | The benchmark made zero external calls; measured API spend was $0. | The API cost was $0. |
| Automated cost | Final cost model | Projected | Projected automated cost was $0.0000949/page under documented selective-oracle pricing assumptions. | Our invoiced or production API cost is $0.0000949/page. |
| Local cost | Ledger | Measured usage + configured price | Local stage usage was measured and prices to $0.0000722/page at the configured compute rate. | Local OCR is free. |
| Throughput | Throughput summary | Verified prototype | The development-workstation prototype measured 9.2 pages/minute on the frozen synthetic run. | Production throughput is 552 pages/hour per worker. |
| Provider accuracy | None | Prohibited | No provider-accuracy claim is approved. | GPT-5/Gemini/Claude achieves the oracle result. |
| Live provider integration | OpenRouter synthetic smoke receipt | Verified one-call integration | ClaimRoute executed one policy-guarded, crop-level multimodal extraction using Qwen 3.7 Flash through OpenRouter. The call used 276 input tokens and 77 output tokens, cost $0.00001829, completed in 3.86 seconds, and returned a grounded NPI candidate that passed checksum validation. | Multimodal benchmark accuracy, production reliability, all-field resolution, or official-claim testing is proven. |
| Official Tier B | PHI-safe organiser receipt | Verified official page routing | On deterministically linked evaluable items, Tier B selected 4/4 claim pages and rejected 15/15 attachments. | All Tier B containers were authoritatively mapped. |
| Official Tier C | Frozen one-time holdout receipt | Verified official, provisional denominator | Tier C measured 36/42 primary normalized fields (85.714%) and 16/18 critical fields (88.889%) under the required provisional-denominator label. | ClaimRoute achieves 85.714% on all UB-04 claims. |
| Tier A / Tier D | Development or limited evidence only | Holdout/full-support claim prohibited | Tier A is not officially holdout-proven; Tier D routing exists but extraction support is limited. | All official tiers or document types are fully supported. |
| Enterprise scale | Cost projection | Projected | Linear cost projections are shown for planning only. | ClaimRoute is proven at 100 million pages. |
| Licence compatibility | Installed metadata and `docs/licensing.md` | Verified for listed OSS; provider terms separate | Listed runtime dependencies declare permissive licenses; provider and dataset terms require separate approval. | All commercial/data use is legally approved. |
