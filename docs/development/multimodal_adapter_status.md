# Multimodal adapter — status

**Branch:** `Bhavya` · **Status:** built, tested, **NOT INTEGRATED** · **Default:** disabled

A provider-independent Tier-2 escalation adapter lives in `engine/escalation/`. It generates
**one candidate for one field crop** and returns a typed result. Nothing in the production
pipeline imports it, and it makes no call unless explicitly enabled.

## Why it exists

Official CMS-1500 development currently resolves 46 of 77 populated fields and routes 35 to
`ESCALATE`. Those escalations have nowhere to go: the only responder is
`engine/vision/offline_engine.py`, a deterministic test double whose accuracy is not evidence
about any real model. This adapter is the real path those crops will eventually take. Building
it separately keeps the official geometry and OCR optimisation work on `main` untouched.

## What was built

| Module | Responsibility |
|---|---|
| `engine/escalation/errors.py` | Ten typed categories; retryability decided once, centrally |
| `engine/escalation/contract.py` | Request/result types, strict parsing, grounding, usage, cost |
| `engine/escalation/providers/base.py` | Provider interface (transport only) + the strict prompt |
| `engine/escalation/providers/openai_provider.py` | The one real provider (OpenAI chat completions) |
| `engine/escalation/providers/fake.py` | Deterministic test doubles — never reachable from config |
| `engine/escalation/client.py` | Policy gate, bounded retries, raw-response hashing, safe audit |
| `configs/multimodal_providers.yaml` | Provider config; `enabled: false` |
| `.env.example` | Value-free environment template |

Providers are deliberately thin. Parsing, grounding, costing and retry logic live in the client,
so a second provider cannot introduce a second opinion about what a valid answer is — it never
sees that question. Adding a provider is a transport subclass, one row in
`providers/__init__.py::_KINDS`, and a price row in `configs/prices.yaml`.

### Reused, not rebuilt

`engine/cropper.py` (the structural PHI boundary and PNG encoding), `engine/grounding.py` field
shape patterns, `engine/vision/base.py::expectation_for` and `price_call`,
`engine/ocr/base.py::normalize_text`, and `engine/ledger.py`. The adapter adds no dependency:
transport is `urllib` from the standard library, matching the existing vision adapters.

## Response contract

```json
{"value": "visible field value or null", "visible": true, "confidence": 0.97}
```

Rejected, mechanically: invalid JSON; explanatory prose; missing required keys; any key beyond
those three (a second key means it read a neighbouring box); `confidence` outside 0–1;
`visible: false` with a non-null value; primitives of the wrong type (`visible` must be a real
boolean, and `bool` is explicitly excluded from `confidence` despite subclassing `int`); a value
longer than one form box can hold; and a value whose shape does not match the requested field
type.

A JSON object embedded in commentary is **rejected, not extracted**. Fishing it out with a regex
would reward a model that broke the contract, and its next answer would be no more parseable.

**The adapter performs no healthcare validation.** NPI checksums, ICD/CPT dictionaries and
cross-field arithmetic remain `engine/validators/`, applied by the caller on governor re-entry.
The answer is a candidate, never truth.

## Safety properties

- **Disabled by default.** `enabled: false` in tracked config. When disabled no provider object
  is constructed, so a missing key or a bad endpoint cannot cause a call either. Proven by
  asserting the fake provider's call count is zero.
- **Crops only.** A request whose region exceeds `max_page_fraction` is refused before the call.
  An image with **no recorded source-page size is also refused** — unverifiable provenance is not
  assumed benign. Page fraction is measured on the region taken *from the page*, not on the
  encoded image, because `crop_field` upscales small boxes.
- **Keys from the environment only.** Config names an env var; it never holds a value. The key is
  read at call time and stored on neither the provider nor the result.
- **Raw responses are hashed and dropped.** A response can contain a transcribed claim value, so
  persisting one would move PHI into logs. The SHA-256 preserves reproducibility without the
  payload.
- **Audit records report shape, not content**: `has_value`, `value_chars`, `visible`,
  `confidence`, crop SHA-256, sizes, latency, attempts, usage, cost. No crop bytes, no extracted
  values, no prompt, no key. Rejection reasons name the *type* that failed, never the value.
- **Provider error messages are never surfaced.** Only the machine-readable code/type is
  inspected, since a human-readable message can quote request content.
- **Synthetic-only.** A request not marked synthetic is refused while `synthetic_data_only` is
  set — official-dataset governance is still unresolved (`docs/security_and_phi.md`).

## Cost and token accounting

`measured_usd` is **provider-reported tokens priced from `configs/prices.yaml`**. It is a
list-price computation over reported usage, **not a billed invoice amount**; `basis` records
which it is so no report can quietly promote one to the other.

When a provider reports no usage, the fallback estimate covers **text tokens only** and is
flagged `estimate_excludes_image_tokens` / `estimate_is_lower_bound`. **Image tokens are never
invented** — no provider in scope reports them separately, so `image_tokens` stays `unknown`
rather than being back-computed from an unverifiable tile formula. Every absent count stays
`unknown`; none is defaulted to zero.

A rejected answer still reports the cost it incurred. The call was made and the money was spent;
hiding that would flatter the cost story.

## Measurement status

| Item | Status |
|---|---|
| Real API smoke test | **NOT RUN** — no `OPENAI_API_KEY` in this environment; skipped |
| Measured API spend | **$0** — zero real calls made in this task |
| Token accounting | Verified against **synthetic provider envelopes only** |
| Cost arithmetic | Verified against `configs/prices.yaml` list prices, synthetic token counts |
| Accuracy on escalated fields | **NOT MEASURED** — out of scope; requires integration first |

No number here is evidence about any real model's accuracy, latency, or cost.

## Running it

```bash
# unit tests — no network, no key, no spend
.\.venv\Scripts\python.exe -m pytest tests/test_multimodal_*.py -q

# opt-in real call: ONE billable request against a freshly rendered synthetic crop
$env:CLAIMROUTE_REAL_PROVIDER_SMOKE="1"; $env:OPENAI_API_KEY="..."
.\.venv\Scripts\python.exe -m pytest tests/integration/test_real_multimodal_provider.py -q
```

The smoke test renders its crop in-process from `data_factory` with a seed used nowhere else. It
asserts on **shape only** — one call is not evidence of accuracy, so asserting that the model
read a specific string would be an accuracy claim the test cannot support.

## Remaining integration risks

1. **Not wired to the governor.** `engine/escalate.py` still calls `engine/vision/`. Connecting
   this adapter means routing `ESCALATE` fields through it, re-entering `run_validators`, and
   re-deciding — none of which is done here.
2. **Two escalation paths now exist.** `engine/vision/` (schema: `value`/`visible_text`/
   `confidence`/`reason`) and `engine/escalation/` (schema: `value`/`visible`/`confidence`).
   Integration must pick one and retire or bridge the other; leaving both live invites a silent
   divergence in what "grounded" means.
3. **No response cache.** `engine/escalate.py` has one keyed on crop hash; this adapter has none,
   so re-running an evaluation would re-bill. `request_id` is already the right key.
4. **`gpt-5-nano` is unverified against real crops.** Whether it can read a 1-bit legacy CMS-1500
   field crop at all is unmeasured. The 35 escalated development fields are the natural first
   test, and that requires organiser-data governance to be resolved first.
5. **No provider-side zero-retention attestation.** `model_policy.require_zero_retention` is
   declared in `configs/pipeline.yaml` but nothing verifies the provider honours it.
6. **Rate limits are untested against a real endpoint.** Backoff is bounded and correct against
   scripted 429s; real concurrent behaviour under a live quota is unmeasured.
