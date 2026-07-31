# Official UB-04 candidate denominator policy

Status: **candidate only; organiser confirmation required; holdout not authorized**.

The machine-readable contract is `eval/official/ub04_denominator_policy.yaml`. Every mapped Tier C
field has exactly one policy. The current development denominator includes 14 concrete fields per
page (28 comparisons): required claim fields plus visibly printed/nonblank first revenue-row values.

Excluded categories are deliberate:

- FL 3b is printed but absent from the development expected record.
- FL 5 has a ten-character UB-192 slice but a nine-digit printed EIN.
- Rows 2–3 revenue, units, and charges exist in the expected record but are not printed.
- Blank HCPCS boxes are valid but excluded because the evaluator omits empty expected values.
- Patient address spans several printed subfields and remains ambiguous.
- Provider NPI, service date, and payer name have no current authoritative expected-output path.
- Attending NPI remains conditional on organiser confirmation of qualifier semantics; the qualifier
  itself is unsupported as a scored ClaimRoute field.

These exclusions must remain unchanged until the organiser answers the exact questions recorded in
the YAML. No absence or record-only value may be silently converted into a scored comparison.
