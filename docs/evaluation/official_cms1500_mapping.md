# Official CMS-1500 field-mapping specification

Status: **complete and machine-checked** (31 Jul 2026). No crop coordinate authored yet.

Machine-readable source of truth: [`eval/official/cms1500_field_map.yaml`](../../eval/official/cms1500_field_map.yaml).
Tests: [`tests/test_cms1500_field_map.py`](../../tests/test_cms1500_field_map.py) (31 tests).
This document is the human-readable rendering; the YAML is what the tests check.

## Why this exists before the crop coordinates

A layout template is a mapping from a field **name** to a rectangle. If the name is wrong,
nothing raises. `engine/governor.py:field_policy()` falls back to `defaults`, and the field is
extracted, validated, and governed under the wrong criticality, the wrong validators, and the
wrong blank-handling rule. The error surfaces only as a slightly worse accuracy number, weeks
later, indistinguishable from a bad crop.

Authoring the names first, and generating them from the code rather than typing them, removes
that failure mode. Every mechanical column below was produced by calling the same functions the
pipeline calls, and the test file re-derives all of them on every run.

## How each column was resolved

| Column | Resolved by |
|---|---|
| Official output field | keys produced by `eval/official/parsers.py:parse_nsf_bytes` |
| ClaimRoute canonical field | names emitted by `eval/official/evaluator.py:claimroute_expected` |
| Normalization family | `eval/official/normalization.py:classify_field(name)` |
| Validators, criticality, may-be-blank | `engine/governor.py:field_policy(name)` |
| Present in dev documents | field names + booleans from `eval/official/results/official_sample_rows.jsonl`, restricted to the three development source IDs |

CMS-1500 box numbers are the one column that is **not** machine-derived; they come from the
CMS-1500 (02-12) form layout and are the judgement part of this specification.

## Scope

- 44 field names reach `compare_fields` on the NSF-320 path.
- 28 reach it on the UB-192 path (documented here only for naming compatibility).
- 3 development documents used: `5858cb1e596e`, `a0ccd0f63f79`, `ac3175590d3e`.
- **8 holdout documents were not opened, rendered, OCR'd, inspected, or scored.** A test asserts
  no holdout ID appears anywhere in the mapping file.

## Two independent axes

The first draft of this specification collapsed two different questions into one column, and the
completeness test rejected it. They are kept separate:

- **`status`** answers *does this field reach `compare_fields`, and is a blank box legal?*
- **`box_ambiguous`** answers *is its printed location settled?*

A field can be fully scored and still sit in a contested box (`patient_account_no`). Marking such
a field `ambiguous_spec` would have quietly dropped it out of the completeness check.

### Status vocabulary

| Status | Meaning |
|---|---|
| `mapped_supported` | Official field → real schema name → real policy. Scored. |
| `blank_but_valid` | Scored, and `field_policy` says `optional: true`, so an absent value is ACCEPTed as empty and never escalated. |
| `not_printed` | In the record format but not a printed CMS-1500 box. No crop is possible. |
| `unsupported_schema` | Printed and/or parsed, but no scoreable path exists today. |
| `ambiguous_spec` | Has policy support but **no official expected value**: extractable yet unscoreable. |

`blank_but_valid` is derived from `field_policy`, **not** from clinical expectation. Box 14
(`admission_date`) is routinely blank on real claims, but the policy marks it `optional: false`,
so it is recorded as `mapped_supported`. The specification records what the system enforces.

## Mapping table — CMS-1500 (02-12), NSF-320 output

`crit` = criticality · `blank` = may be blank · `dev` = present in N of 3 development documents.

### Patient identity

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `patient_name` | `patient_name` | 2 | text | name_format | high | no | 3 | mapped_supported |
| `patient_dob` | `patient_dob` | 3 | date | date_valid, dob_before_service | high | no | 3 | mapped_supported |
| `patient_sex` | `patient_sex` | 3 | text | — | low | no | 3 | mapped_supported |
| `patient_address` | `patient_address` | 5 | text | — | low | no | 1 | mapped_supported |
| `patient_city` | `patient_city` | 5 | text | — | low | no | 1 | mapped_supported |
| `patient_state` | `patient_state` | 5 | text | — | low | no | 1 | mapped_supported |
| `patient_zip` | `patient_zip` | 5 | text | zip_format | med | no | 1 | mapped_supported |
| `patient_relationship` | `patient_relationship` | 6 | text | — | low | no | 3 | mapped_supported |
| `patient_control_no` | `patient_control_no` | 26 | text | — | med | no | 3 | mapped_supported ⚠ box |
| `patient_account_no` | `patient_account_no` | 26 | text | — | med | no | 3 | mapped_supported ⚠ box |

`patient_address` is the only field with `external_model_allowed: false`. It never leaves the
trust boundary regardless of confidence.

`patient_sex` and `patient_relationship` are **checkbox** fields: the official record carries a
code, the form carries a mark. The crop must resolve *which* box is ticked, not read text.

⚠ **Box 26 contention**: `patient_control_no` (CA0 record) and `patient_account_no` (EA0 record)
both target the single printed "Patient's Account No." region. At most one can win it. Both are
excluded from the proof set because we cannot yet tell which.

### Insured identity

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `insured_id` | `insured_id` | 1a | text | id_format | high | no | 3 | mapped_supported |
| `insured_name` | `insured_name` | 4 | text | name_format | med | no | 3 | mapped_supported |
| `insurance_plan_name` | `insurance_plan_name` | 11c | text | — | med | no | 0 | mapped_supported ⚠ box |

⚠ Box 11c and box 9d both carry plan names; the record supplies one value. Present in **zero**
development documents, so it cannot be validated here.

### Dates

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `admission_date` | `admission_date` | 14 | date | date_valid | med | no | 0 | mapped_supported |

Present in zero development documents. Its policy entry lives in `ub04_fields` but resolves for
both forms, because `governor.py` merges `fields` and `ub04_fields` into one lookup.

### Diagnosis codes — box 21

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `diagnosis_1` | `diagnosis_code_a` | 21A | text | icd10_format, icd10_dictionary | high | no | 3 | mapped_supported |
| `diagnosis_2` | `diagnosis_code_b` | 21B | text | icd10_format, icd10_dictionary | high | **yes** | 3 | blank_but_valid |
| `diagnosis_3` | `diagnosis_code_c` | 21C | text | icd10_format, icd10_dictionary | high | **yes** | 1 | blank_but_valid |
| `diagnosis_4` | `diagnosis_code_d` | 21D | text | icd10_format, icd10_dictionary | high | **yes** | 1 | blank_but_valid |

Box 21 prints twelve pointers (A–L) on the 02-12 revision; the NSF-320 record supplies four.
E–L have no expected value and cannot be scored.

### Service lines — box 24, repeated (`line{n}_`, n ∈ 1..3)

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `service_from` | `line{n}_date_from` | 24A | date | date_valid, dob_before_service | high | no | 3 | mapped_supported |
| `service_to` | `line{n}_date_to` | 24A | date | date_valid | med | no | 3 | mapped_supported |
| `place_of_service` | `line{n}_place_of_service` | 24B | text | — | low | no | 3 | mapped_supported |
| `procedure_code` | `line{n}_cpt_code` | 24D | text | cpt_format, cpt_dictionary | high | no | 3 | mapped_supported |
| `modifiers` | *(none)* | 24D | — | — | — | — | 0 | **unsupported_schema** |
| `diagnosis_pointer` | `line{n}_diagnosis_pointer` | 24E | text | — | med | no | 3 | mapped_supported |
| `charge` | `line{n}_charges` | 24F | money | currency_format, claim_arithmetic | high | no | 3 | mapped_supported |
| `units` | `line{n}_units` | 24G | quantity | numeric_format | med | no | 3 | mapped_supported |
| *(none)* | `line{n}_rendering_npi` | 24J | text | npi_checksum | high | yes | 0 | **ambiguous_spec** |

Policy for these resolves through `service_line_template.<suffix>` via the `line\d+_(\w+)` regex
in `governor.py`. A test asserts every line index is governed identically.

`line{n}_date_from` / `_date_to`, `line{n}_units`, and `line{n}_charges` are the three families
that carried the normalization defects fixed in `9c47fe2`.

### Provider identity and totals

| Official field | ClaimRoute field | Box | Norm | Validators | Crit | Blank | Dev | Status |
|---|---|---|---|---|---|---|---|---|
| `referring_npi` | `referring_provider_npi` | 17b | text | npi_checksum | high | **yes** | 0 | blank_but_valid |
| `federal_tax_id` | `federal_tax_id` | 25 | code | tax_id_format | high | no | 3 | mapped_supported |
| `provider_npi` | `billing_provider_npi` | 33a | text | npi_checksum | high | no | 3 | mapped_supported |
| `provider_name` | `billing_provider_name` | 33 | text | org_name_format | med | no | 3 | mapped_supported |
| `total_charge` | `total_charge` | 28 | money | currency_format, claim_arithmetic | high | no | 3 | mapped_supported |
| *(none)* | `amount_paid` | 29 | text | currency_format | med | yes | 0 | **ambiguous_spec** |

`federal_tax_id` is the only NSF-320 field reaching the `code` branch.

`amount_paid` would classify as **text**, not money: it matches neither `MONEY_FIELDS` nor the
`_charge` / `_charges` suffixes. If it ever becomes scoreable, fix the routing first.

## Naming compatibility (CMS-1500 ↔ UB-04)

Requirement: preserve both. Each of these will break the other form if "tidied up".

**Format-conditional renames** — applied only when `format_name == "NSF320"`:

| Official field | NSF-320 (CMS-1500) name | UB-192 (UB-04) name |
|---|---|---|
| `provider_npi` | `billing_provider_npi` | `provider_npi` |
| `provider_name` | `billing_provider_name` | `provider_name` |

Use `billing_provider_npi` for every CMS-1500 crop. `provider_npi` would resolve to the UB-04
policy entry.

**Intentional singular/plural split** — `total_charge` (CMS-1500 box 28) vs `total_charges`
(UB-04 box 47). Separate policy entries, both normalizing to money. Unifying them would break one
form's policy lookup and the frozen UB-04 templates.

**Unconditional renames**: `referring_npi` → `referring_provider_npi`;
`diagnosis_1..4` → `diagnosis_code_a..d`.

**Shared across both forms**: `patient_name`, `patient_dob`, `patient_sex`, `patient_address`,
`patient_control_no`, `admission_date`.

## Known limits

| Limit | Effect |
|---|---|
| Service-line cap of 3 | `claimroute_expected` iterates `service_lines[:3]`; the form prints 6 rows. Lines 4–6 are dropped from both expected and scored output. Authoring crops for them adds cost with no accuracy benefit. |
| `modifiers` dropped | Parsed from FA0 positions 65–70 but has no alias and no policy entry, so it never reaches scoring. |
| `rendering_npi` unscoreable | Box 24J has policy support but no official expected value. Extractable, not scoreable. |
| `amount_paid` unscoreable | Box 29 likewise, and would misroute as text if it became scoreable. |
| Box 26 contention | Two official fields, one printed region. |

## Initial proof set — the first five crops

Eligibility was mechanical: present in **all three** development documents, `mapped_supported`,
and `box_ambiguous: false`. **18 of the 44** names qualified.

Selection criterion among those 18: **one field per normalization family**, not the five most
convenient. Five `text` singletons would prove only that one code path works. One per family
means the first proof run exercises every branch of `classify_field`, so a residual routing
defect surfaces on five crops rather than hiding until all 46 are authored. Two of these families
(date, quantity) carried live defects fixed in `9c47fe2`, so they are the ones most worth
re-proving against real pages.

| # | ClaimRoute field | Box | Family | Crit | Why this one |
|---|---|---|---|---|---|
| 1 | `patient_dob` | 3 | **date** | high | Highest-value component-order risk: printed MM\|DD\|YYYY across three sub-cells against a CCYYMMDD record. |
| 2 | `line1_charges` | 24F | **money** | high | Decimal alignment, only latently correct before `9c47fe2`. First service-line crop, so it proves `line{n}_` policy resolution end to end. |
| 3 | `line1_units` | 24G | **quantity** | med | Carried a live defect (parser `1.0` vs printed `1`). A single isolated glyph, so it also proves the PSM_BLOCK crop requirement (assumptions #12). |
| 4 | `federal_tax_id` | 25 | **code** | high | The only NSF-320 field reaching the code branch, so the sole way to exercise it on this form. |
| 5 | `billing_provider_npi` | 33a | **text** | high | Proves the format-conditional rename resolves to the CMS-1500 entry, not the UB-04 one — the most likely naming mistake in the remaining 41 boxes. Backed by `npi_checksum`, so a mis-read is caught deterministically. |

Deliberately excluded: `patient_account_no` and `patient_control_no` (contested box);
`diagnosis_code_b` (`blank_but_valid`, so an absent value ACCEPTs and proves nothing about crop
accuracy); `patient_name` (eligible and high criticality, but the text branch is already covered
by `billing_provider_npi`, which additionally proves the rename path).

## Open questions for the organiser

1. Is box 24J (Rendering Provider ID) part of the official output?
2. Is box 29 (Amount Paid) part of the official output?
3. Which official field, `patient_control_no` or `patient_account_no`, corresponds to printed box 26?
4. Are service lines beyond the third in scope for scoring?
5. Are box 24D modifiers required?
6. Does `insurance_plan_name` correspond to box 11c or box 9d?

## PHI posture

Field names, box numbers, counts, and booleans only. No organiser value, OCR text, crop, page
pixel, or holdout identifier appears in the mapping file, this document, or the tests. Presence
counts derive from the existing aggregate PHI-safe rows, which contain field names and booleans
and no values.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cms1500_field_map.py -q
```
