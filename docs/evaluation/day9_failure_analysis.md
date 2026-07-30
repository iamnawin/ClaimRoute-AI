# Day 9 failure analysis and replay calibration

## Evidence boundary

This analysis uses only the synthetic Day 8 calibration results. It reruns no OCR,
makes no external API calls, and does not use the official dataset. Offline-oracle
costs remain projected; measured API spend is $0. Pre-escalation local candidates
are reconstructed deterministically from recorded primary/retry attempts because Day 8
did not persist the selected local candidate or full page validation context.

Analyzed **171** unresolved-or-wrong fields: **170** human-review outcomes and **14** incorrect values. **157** correct values were still sent to human review.

## Top unresolved field types

| Field | Count |
|---|---:|
| `insured_id` | 10 |
| `insured_name` | 9 |
| `principal_dx` | 9 |
| `insurance_plan_name` | 8 |
| `patient_dob` | 8 |
| `provider_name` | 8 |
| `patient_control_no` | 7 |
| `billing_provider_name` | 5 |
| `line2_charges` | 5 |
| `line3_charges` | 5 |

## Root-cause clusters

| Likely cause | Count |
|---|---:|
| governor threshold | 157 |
| oracle limitation | 8 |
| normalization | 3 |
| field mapping | 1 |
| ocr segmentation | 1 |
| preprocessing | 1 |

| Resolution path | Count |
|---|---:|
| governor threshold calibration | 157 |
| multimodal escalation | 8 |
| deterministic normalization | 3 |
| better local crop strategy | 2 |
| field specific ocr mode | 1 |
| human review only | 0 |
| validator correction | 0 |

### Top recurring clusters

| Tier | Form | Field | Cause | Resolution | Count |
|---|---|---|---|---|---:|
| ugly | ub04 | `provider_name` | governor threshold | governor threshold calibration | 6 |
| ugly | cms1500 | `insured_id` | governor threshold | governor threshold calibration | 5 |
| ugly | ub04 | `insured_name` | governor threshold | governor threshold calibration | 5 |
| ugly | ub04 | `line3_charges` | governor threshold | governor threshold calibration | 5 |
| ugly | ub04 | `patient_dob` | governor threshold | governor threshold calibration | 5 |
| ugly | cms1500 | `insurance_plan_name` | governor threshold | governor threshold calibration | 4 |
| ugly | ub04 | `line1_rev_code` | governor threshold | governor threshold calibration | 4 |
| ugly | ub04 | `line2_charges` | governor threshold | governor threshold calibration | 4 |
| ugly | ub04 | `line2_service_date` | governor threshold | governor threshold calibration | 4 |
| ugly | ub04 | `medical_record_no` | governor threshold | governor threshold calibration | 4 |

The dominant cluster is a policy-resolution issue: validators passed and the retained
value was correct, but exhausted retry/escalation budgets plus the configured confidence
threshold still produced HUMAN_REVIEW. This is not OCR or provider accuracy evidence.

## Operating modes

| Mode | Accuracy | Critical accuracy | Escalation | Human review | Projected cost/page |
|---|---:|---:|---:|---:|---:|
| Economy | 96.55% | 98.97% | 3.96% | 3.31% | $0.000200 |
| Balanced | 98.51% | 99.72% | 7.50% | 0.98% | $0.000240 |
| Accuracy | 98.79% | 99.81% | 17.23% | 4.33% | $0.000351 |

## Recommended Balanced thresholds

- Local accept confidence: `0.8`
- Multimodal accept confidence: `0.9`
- Paid escalation: high and medium criticality only
- ACCEPT_WITH_FLAG enabled for low/medium: `True`
- Optional-field escalation: prohibited

## Accuracy-cost frontier

| Accuracy | Escalation | Human review | Projected cost/page | Point |
|---:|---:|---:|---:|---|
| 96.93% | 3.96% | 2.10% | $0.000200 | `local-0.80_model-0.88_paid-high_flags-on` |
| 98.51% | 7.50% | 0.98% | $0.000240 | `local-0.80_model-0.90_paid-high-med_flags-on` |
| 98.70% | 7.91% | 0.98% | $0.000245 | `local-0.80_model-0.90_paid-high-med-low_flags-on` |
| 98.74% | 13.18% | 1.86% | $0.000305 | `local-0.84_model-0.90_paid-high-med-low_flags-on` |
| 98.79% | 17.23% | 2.56% | $0.000351 | `local-0.88_model-0.90_paid-high-med-low_flags-on` |

## Limits and next evidence

The accuracy-cost frontier is bounded by the 406 fields actually escalated on Day 8.
Accuracy is retained-value exact match, including HUMAN_REVIEW values; automated correct
fields and human-review rate separately describe workflow resolution.
It must not be presented as real-provider performance or extrapolated to unobserved
calls. Official-dataset tuning remains blocked until its role and field mapping are
confirmed.
