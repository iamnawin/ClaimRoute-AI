# Architecture v1.2 (locked)

Cost-governed healthcare claims extraction: Tier 0 preprocess (page split, deskew, rotate,
denoise, DPI normalize, quality score) → free heuristic Document Router (CMS-1500 / UB-04 /
custom / unstructured / unknown) → Tier 1 single-engine OCR + template/anchor layout mapping →
confidence fusion (OCR + layout + quality + pattern; engine agreement only after the retry
rung) → healthcare validation (NPI checksum, CPT/ICD dictionaries, dates, arithmetic,
cross-field) → Cost Governor → selective rungs: cheap OCR retry/voting → Tier 2 field-crop
multimodal (approved model, zero-retention, crops only) → grounding check → human review queue.
Cross-cutting: cost ledger, model policy engine (PHI minimisation), audit log/provenance,
YAML config, eval dashboard tab.

## State model

```
ACCEPT · ACCEPT_WITH_FLAG · RETRY · ESCALATE · HUMAN_REVIEW · ACCEPT_WITH_OVERRIDE
```

`ACCEPT_WITH_OVERRIDE` is unreachable from automated paths — only an authenticated reviewer
produces it (enforced in `engine/schemas.py`), with an audit record: corrected value, failing
validator, reviewer identity, timestamp, override reason.

## Notes (normative)

- Governor input = fused confidence + validator verdicts + field policy + attempt history.
- Every automated candidate re-enters validation.
- Nothing enters final output without a validation stamp.
- Engine agreement is used only after the retry rung.
- Each field has a configurable attempt budget; exhausted attempts route to HUMAN_REVIEW.
- Human corrections are revalidated before finalization.
- Human overrides of validator failures are terminal and audit-logged.

Full rationale, rejected alternatives, and the day-by-day plan live in the execution plan
document (kept outside the repo); decisions here are normative for all code.
