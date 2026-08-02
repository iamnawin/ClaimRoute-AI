# FAILURE_TALK_TRACKS.md - what to say when something breaks

Team DXtra AI - ClaimRoute AI

Say the line, move on, keep recording. A recovered take is better than a
re-record, and an honest recovery is on-message: routing uncertainty instead of
hiding it is the product. Canonical wording lives in
[`../../demo_assets/recording_checklist.md`](../../demo_assets/recording_checklist.md).

## Streamlit will not start or crashes mid-demo

> "The interface is a thin layer over the tested extraction service. I will use
> the committed synthetic-safe visuals and the immutable aggregate receipts the
> application loads."

Then: switch to `day10_home.png`, `benchmark_summary.png`, `cost_and_latency.png`
and continue from the current cue in [`DEMO_CLICK_PATH.md`](DEMO_CLICK_PATH.md).

## OCR output differs from the pre-run

> "OCR timing and candidates can vary by workstation. I will not substitute a
> better-looking result. The submission claim comes from the frozen commit and
> its receipts."

Then: show the committed receipt. Do not re-run hoping for a nicer number.

## No internet during the recording

> "The judged path is local and synthetic. No external API is required. The
> multimodal boundary is demonstrated by the deterministic offline oracle and the
> audit evidence."

Nothing in the demo needs the network. This is not a degraded take.

## The degraded sample behaves differently

> "This live variance is exactly why ClaimRoute keeps receipts and routes
> uncertainty instead of hiding it. I will show the committed pretested synthetic
> receipt."

## A judge asks for a number that is not in the register

> "That figure is not in our evidence register, so I will not quote it. What we
> measured is ..." - then give the nearest registered metric and its label.

Never estimate on camera. `PENDING_EVIDENCE_REVIEW` in the register means the
number does not exist yet, and saying so is a stronger answer than guessing.

## A judge asks about precision and recall

> "Precision is 99.904 percent and recall is 98.136 percent, derived per field
> from the frozen benchmark rows - 3,106 true positives, 3 false positives, 59
> false negatives. That is a derivation from the existing frozen evidence, not a
> new benchmark run."

If pressed on 98.043 percent: that is the automated exact-match rate, TP over all
3,168 evaluated fields. Recall divides by the 3,165 fields that had a populated
ground truth to find. Different denominators, different metrics.

## A judge asks about Tier A official accuracy

> "Measured zero on official Tier A. It is in our evidence register and in the
> workbook, and we do not present it as overall accuracy or claim all-tier
> support."

Do not soften this. It is real, measured, and deliberately not hidden.

## A judge asks whether a real provider was used

> "One verified live call: a single synthetic crop through OpenRouter, 0.00001829
> dollars, no model substitution. That is integration evidence, not a performance
> benchmark. The frozen benchmark used a deterministic offline oracle with zero
> external calls and zero measured spend."

## Something confidential nearly appears on screen

Stop the take. Do not narrate around it. Cut, clear the screen, restart from the
last checkpoint in the click path. This is the one failure that is never worth
recovering live.
