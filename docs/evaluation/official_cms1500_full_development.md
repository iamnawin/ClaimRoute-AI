# Official CMS-1500 full development expansion

The CMS-1500 (02-12) official template now covers all 41 scored, schema-supported,
geometrically unambiguous names in the NSF-320 denominator. This is a development result,
not a holdout score and not a frozen-system claim.

## Mechanical selection

The authoritative map contains 44 evaluated names. All 44 are scored and schema-supported;
41 are geometrically unambiguous and eligible. Three evaluated names are excluded because
their printed box is contested: two box-26 aliases and one plan-name mapping. Outside the
44-name denominator, one unsupported schema concept and four names without an official
expected alias remain un-authored. Lines 4-6 are excluded by the evaluator's three-line cap.

## Development evidence

Only the three IDs declared under `development` in the frozen split manifest were used.
All 123 field/document crop instances aligned to the intended printed box. Blank boxes were
recorded as blank, not as OCR failures. Of 77 populated evaluable instances, primary OCR
resolved 18, local retry was attempted on 60 and resolved 23, and final normalization resolved
32. Critical-field accuracy was 17/41. Governor outcomes were 22 ACCEPT, 14 ACCEPT_WITH_FLAG,
and 41 ESCALATE. External calls and external cost remained zero.

Measured latency was 795,223.988 ms total (265,074.663 ms/page). Measured local cost was
$0.011044778 total ($0.003681593/page). The failure cluster is downstream of registration:
39 OCR character-confusion failures and 6 segmentation failures; registration and coordinate
geometry failures were zero.

## Earlier escalation analysis

The retry path was supplying raw OCR confidence to the governor even though `Attempt.confidence`
is defined as fused candidate confidence. Propagating fused retry evidence changes one prior NPI
case from ESCALATE to ACCEPT. The other NPI case remains at 0.8093 and the units case remains at
0.8272, both below Balanced's 0.88 accept threshold. Those two are expected conservative policy
outcomes; thresholds were not changed.

## Safety

Expected values were consulted only after coordinates were fixed. The local evaluator retained
and parsed only record blocks 1, 5, and 11. No holdout TIFF was opened, rendered, registered,
cropped, or OCRed. Local crops, contact sheets, OCR text, and detailed rows remain Git-ignored.
The committed report contains no organiser value, OCR text, source filename, TIFF, crop, overlay,
or PHI.

The complete aggregate receipt is
`eval/results/official_cms1500_full_development_summary.json`.
