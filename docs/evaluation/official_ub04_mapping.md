# Official UB-04 field mapping

Status: **development contract; holdout untouched**.

The authoritative machine-readable crosswalk is `eval/official/ub04_field_map.yaml`. It maps the
UB-192 parser contract to ClaimRoute names, CMS-1450 form locators, normalization, validators,
policy, scoreability, support, and geometric ambiguity. These axes remain separate: a field can be
scored and supported while still being geometrically ambiguous (`patient_address`), or supported by
policy while absent from the current expected-output path (`provider_npi`, `line{n}_service_date`).

## Coverage

- 28 possible evaluated ClaimRoute names: 16 claim-level names plus four service-line families
  expanded across the evaluator's three-line cap.
- 19 mapped source families are scored and supported.
- One potentially scored but unsupported control field: `attending_qualifier`. The evaluator emits
  it when populated even though ClaimRoute has no matching policy; this is documented, not hidden.
- Two specification/policy fields are absent from current parser output: `provider_npi` and service
  date.
- One policy-only field has no current UB-192 source mapping: `payer_name`.
- No organiser value, OCR text, crop, filename, or local path is stored in the map.

## Frozen development split

Tier C contains six items: five deterministic links and one ambiguous link. Safe linkage metadata
selected the two joint-highest-margin items for development before template authoring. The other
three deterministic items are untouched holdout; the ambiguous item is excluded from every
denominator. The immutable manifest is `eval/official/splits/tier_c_split_v1.json`.

## Five proof fields

`patient_control_no`, `admission_date`, `line1_units`, `total_charges`, and `principal_dx` are
scored, supported, unambiguous, and populated in both development records. Together they cover
text, date, quantity, money, and code normalization across the top, service grid, total row, and
lower diagnosis section. Coordinates must be fixed from form structure before expected values are
used for evaluation.

## Expanded development template

The template now holds 25 concrete regions, including the evaluator's three-row service cap.
Fourteen regions are score-eligible on both development documents. Optional HCPCS rows are
`blank_but_valid`; six repeated row-2/3 values are `not_printed`; FL 3b and FL 5 are
`excluded_from_denominator_pending_organiser_confirmation`. Patient address remains ambiguous,
and attending/provider/service-date/payer concepts remain outside the template or denominator for
the reasons recorded in the machine-readable map.
