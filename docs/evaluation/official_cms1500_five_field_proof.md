# Official CMS-1500 five-field development proof

This proof uses only the three development items frozen in `tier_a_official_v1`. The eight
holdout items and one excluded item were not opened, rendered, OCRed, cropped, or measured.

## Registration

Official CMS-1500 (02-12) scans use their own structural registration. It does not reuse the
synthetic red-grid extent. Otsu binarization and long horizontal ruled components establish the
form top, bottom, and row bands. Vertical rules are detected inside those bands to establish the
left and right bounds. Components touching the page edge are rejected as scanner artifacts.
Registration abstains when structural evidence is insufficient.

The three development pages registered at confidence 0.993–0.994. Their stable anchors were the
outer horizontal rule group, band-local left border, and band-local right border. Every page
reported a rejected page-edge dark artifact.

## Fixed regions and local retry

Only Boxes 3, 24F line 1, 24G line 1, 25, and 33a were authored. Coordinates were fixed from
printed rules and box semantics before expected values were compared. Each field declares its own
padding. Primary whole-page Tesseract output re-enters normalization, validation, and the frozen
governor. Governor-routed retries use local RapidOCR crops with deterministic field modes: date
component ordering, decimal-preserving money parsing, isolated-glyph handling, digit-only tax ID,
and digit-preserving NPI validation/check-digit repair. No provider call was made.

## Result

| Measure | Result |
|---|---:|
| Geometrically correct crops | 15/15 |
| Values visibly present | 15/15 |
| Primary normalized matches | 4/15 |
| Retry attempts | 12/15 |
| Retry normalized matches | 12/12 |
| Final normalized matches | 15/15 |
| Validator passes | 15/15 |
| Governor ACCEPT | 12/15 |
| Governor ESCALATE | 3/15 |
| Measured latency | 55,691.535 ms |
| Measured local cost | $0.000773493 |
| External calls | 0 |

The three escalations are correct normalized candidates that remain below the frozen governor's
acceptance confidence. Thresholds were not weakened. The repository-safe JSON summary contains
per-instance booleans, states, timings, and costs, but no OCR or organiser values.

## Safety receipt

- Development source IDs: `5858cb1e596e`, `ac3175590d3e`, `a0ccd0f63f79`.
- Holdout access: zero.
- Expected values were used only after geometry was fixed, for comparison in memory.
- Local diagnostic images and scripts remain under the Git-ignored diagnostics directory.
- No TIFF, crop, overlay, OCR text, expected value, organiser filename, or PHI is committed.
