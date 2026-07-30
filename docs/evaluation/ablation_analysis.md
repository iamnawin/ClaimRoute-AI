# Day 11 ablation analysis

All supported arms use the same 90-page frozen synthetic test split and frozen commit. Accuracy is
measured; the full-pipeline oracle component is projected.

| Arm | Accuracy | Critical accuracy | Unresolved | Local cost/page | Projected automated cost/page | Avg latency | Pages/min |
|---|---:|---:|---:|---:|---:|---:|---:|
| Primary OCR only | 66.351% | 66.667% | 33.586% | $0.00003778 | $0.00003778 | 2.720 s | 22.06 |
| Primary + preprocessing | 99.527% | 99.936% | 0.379% | $0.00006635 | $0.00006635 | 4.778 s | 12.56 |
| Primary + preprocessing + validators | 99.527% | 99.936% | 6.881% | $0.00006636 | $0.00006636 | 4.778 s | 12.56 |
| Validators + local retry | 99.842% | 99.936% | 1.957% | $0.00007220 | $0.00007220 | 5.198 s | 11.54 |
| Full cost-governed pipeline | 99.716% | 99.936% | 1.862% | $0.00007220 | $0.00009490 | 6.521 s | 9.20 |

Preprocessing is the dominant recovery step on the deliberately degraded synthetic pages. Validators
do not change the candidate text; they expose untrusted values that a raw exact-match-only arm would
otherwise treat as resolved. Local retry reduces that unresolved population from 6.881% to 1.957%.

The full pipeline routes 1.905% of fields to the offline oracle, but the locked governor accepts only
4.839% of those escalations. This slightly lowers final field accuracy versus the local-retry arm
because terminal human-review fields are evaluated using the post-escalation candidate. The result is
reported as observed; no post-test tuning was performed. The ugly tier's escalated fields had 0%
governor-accepted resolution and remain a clear limitation.

The requested validators-disabled full-pipeline arm is not technically supported by the frozen
engine. Adding a bypass after the freeze would invalidate the evidence, so no number is invented.
Likewise, there is no full-page LLM accuracy claim; only selective crop pricing is projected.
