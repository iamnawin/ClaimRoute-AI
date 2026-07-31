# Official UB-04 provisional denominator policy

Status: **provisionally frozen; holdout not accessed**.

The organiser clarification requested before the deadline was unavailable. ClaimRoute therefore
uses a conservative, reproducible policy rather than inferring organiser intent. Every Tier C result
must carry this label: **“Provisional denominator policy due to unavailable organiser
clarification.”**

## Primary benchmark denominator

The primary score includes only fields supported by the current evaluator and schema that have an
unambiguous locator, are visibly printed and nonblank, and are deterministically comparable.
`primary_scored` fields enter when present in the organiser expected record. A
`conditional_scored` field enters only when it is also independently confirmed visibly populated
and unambiguous. The development reference set is 14 fields per page (28 comparisons across two
pages). Holdout counts are unknown until the authorized one-time run.

## Extended coverage denominator

The extended denominator contains every nonblank organiser-expected field, including fields outside
the primary policy. It is reported separately as coverage analysis and must never be presented as
the primary accuracy score. The development reference is 21 fields per page (42 comparisons).

## Exclusions

- `excluded_ambiguous`: FL 3b, FL 5, and the composite patient address.
- `excluded_not_printed`: repeated row 2–3 values present only in organiser records.
- `excluded_blank_valid`: blank HCPCS regions without an official blank-scoring rule.
- `excluded_unsupported`: attending qualifier, provider NPI, payer name, and service dates without
  a complete current schema/parser/expected-output path.
- `conditional_scored`: attending NPI only when visibly populated, unambiguous, and expected.

An excluded comparison is neither correct nor incorrect and cannot increase primary accuracy. The
report must show primary numerator/denominator, extended coverage numerator/denominator, exclusions
by category, and the provisional-policy label. Organiser clarification may create a new policy
version; it must not retroactively rewrite this frozen receipt.
