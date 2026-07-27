# Assumptions & Engineering Decisions Log

## Submission assumptions (stated, not silent)
1. **Field scope:** ~25–30 adjudication-relevant fields per form (CMS-1500 44 incl. service
   lines; UB-04 ~19 + revenue lines), not every form locator.
2. **Accuracy metric:** field-level exact match after normalization (dates → ISO, currency →
   cents, ID formatting stripped); reported plain, criticality-weighted, and per degradation tier.
3. **Cost metric:** API list prices + amortized compute, per page; human review costed at
   $0.03/field-touch and reported as a separate line, never hidden.
4. **Dataset:** fully synthetic stand-in for the unissued official set — zero PHI by
   construction, perfectly known ground truth, reproducible from one seed.

## Engineering decisions log
1. **Never use Python `hash()` for reproducible dataset seeds.** It is randomized per process
   (PYTHONHASHSEED). Use stable indices or crc32. (Found Day 2; fixed in make_dataset.)
2. **Legitimately-empty fields are representable in the schema but excluded from ground truth
   and from extraction-accuracy denominators when absent.** Example: revenue code 0250 (room &
   board) carries no HCPCS. An extractor must not be penalized for not finding what isn't there —
   and must be penalized for hallucinating it. (Found Day 2.)
3. **Only full-dataset generation may create or validate the frozen split.** Chunked/partial
   runs are barred from touching the split manifest; a mismatched regeneration refuses to
   overwrite. (Found Day 2 when the freeze guard correctly fired on a chunk.)
4. **Preprocessing estimates, it does not know.** True degradation angles exist only in the
   factory's metadata. Tier-0 corrections replay their *actual applied* transforms onto
   ground-truth bboxes; the bbox-ink guardrail is the proof the estimate sufficed. (Day 3.)
5. **Signal-gated preprocessing.** Every Tier-0 op fires only when its measured signal crosses
   a threshold; clean pages pass through untouched and the empty transform history proves it.
   (Day 3.)
6. **The composite quality score measures scan condition, not processing benefit.** Resampling
   from deskew legitimately lowers its blur term even as geometry is repaired, so before/after
   composite deltas are NOT the claim. Tier-0 improvement claims rest on direct measurables
   (skew residual, white-point restoration) and, definitively, on the OCR-accuracy ablation
   with preprocessing on/off (Day 4+). (Day 3.)
