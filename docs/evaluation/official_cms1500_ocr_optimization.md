# Official CMS-1500 OCR optimization

Development performance improved without coordinate or governor-threshold changes. Geometry remains
123/123 and holdout access remains zero.

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Primary OCR | 18/77 | 22/77 | +4 |
| Retry resolution | 23/60 | 37/60 | +14 |
| Normalized accuracy | 32/77 | 46/77 | +14 |
| Critical accuracy | 17/41 | 26/41 | +9 |
| Validator pass | 46/77 | 50/77 | +4 |
| Latency/page | 119,186.826 ms | 63,523.322 ms | -46.7% |
| Local cost/page | $0.001655373 | $0.000882268 | -46.7% |

Governor outcomes changed from 22 ACCEPT / 14 ACCEPT_WITH_FLAG / 41 ESCALATE to 29 ACCEPT /
13 ACCEPT_WITH_FLAG / 35 ESCALATE. External calls and spend remain zero.

## Implemented

- Normalized valid six-digit MMDDYY dates using the validator's existing deterministic year pivot.
- Reused one Paddle page pass across all retry fields, then ran bounded crop profiles only as needed.
- Added field-family attempt configuration, deterministic preprocessing, typed candidate generation,
  validator/confidence/agreement ranking, and validated early stop.
- Reused one registration per mapping pass and existing singleton OCR engines.

Checkboxes, incomplete code dictionaries, and label-heavy identifiers remain the largest clusters.
The system is improved but still below a prudent official freeze bar. **DO NOT FREEZE.**
