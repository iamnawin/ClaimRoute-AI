# Guarded OpenRouter live routing

**Status:** implemented, tested offline, **never executed against the live provider**.
No paid call has been made from this branch. `OPENROUTER_API_KEY` was absent from
the build environment throughout.

This document describes the only path in ClaimRoute AI that can spend money, and
the nine independent conditions that must all hold before it does.

---

## 1. Why this is a separate layer

`engine/escalation/` already answers *"is this response usable?"* — it parses,
grounds, prices and audits a multimodal answer. It does not answer the question
that comes first and costs money to get wrong: *"may we call a paid provider at
all, right now, for this crop?"*

That question is now `engine/escalation/live_policy.py`. It is a policy layer on
top of the existing adapter, **not a second multimodal framework**. OpenRouter
reuses the existing contract, client, error categories, grounding and cost
types; it adds one transport module and one policy module.

```
engine/escalation/
  contract.py     unchanged in shape; CostBreakdown gained reported_usd/billed_usd
  client.py       unchanged in flow; now prefers a provider-reported cost
  errors.py       unchanged
  providers/
    base.py       ProviderCall gained reported_cost_usd + actual_model
    openai_provider.py     transport extracted into _perform() for reuse
    openrouter_provider.py NEW — OpenAI-compatible transport, substitution locked off
  live_policy.py  NEW — the spending guardrails
```

---

## 2. Zero spending is the default

A paid call requires **all nine** of the following. They are ANDed; there is no
configuration in which one permissive setting unlocks a call on its own.

| # | Condition | Where it lives |
|---|---|---|
| 1 | `live_provider.enabled: true` | `configs/multimodal_providers.yaml` (ships `false`) |
| 2 | `CLAIMROUTE_MULTIMODAL_ENABLED=true` | environment |
| 3 | `CLAIMROUTE_LIVE_PROVIDER_TEST=true` | environment |
| 4 | `OPENROUTER_API_KEY` present and non-blank | environment |
| 5 | request marked `synthetic=True` | caller |
| 6 | image **proven** to be a field crop | `page_fraction` ≤ 0.25 with recorded provenance |
| 7 | model on the allowlist **and** declaring `vision: true` | tracked config |
| 8 | session **and** document budgets still positive | session counters |
| 9 | request is not a duplicate | session fingerprint cache |

Verified against the tracked config as committed:

```
tracked config only        -> BLOCKED_LIVE_PATH_DISABLED
+ all env flags + a key    -> BLOCKED_LIVE_PATH_DISABLED   (config still wins)
config forced on, no key   -> BLOCKED_NO_API_KEY
config forced on, no flag  -> BLOCKED_LIVE_TEST_FLAG_UNSET
```

Turning on the environment flags alone changes nothing. The tracked file must be
edited too, which makes enabling the paid path a reviewable act rather than an
accident of a shell profile.

---

## 3. Typed outcomes, never a bare boolean

Every authorisation returns a `LiveCallOutcome` carrying a `LiveDecision`. An
operator needs to know whether a field went unanswered because the money ran out
or because the model was wrong — those demand different fixes, and a single
"call failed" string loses exactly that.

```
ALLOW                          REUSED_CACHED_RESULT
BLOCKED_LIVE_PATH_DISABLED     BLOCKED_ADAPTER_DISABLED
BLOCKED_LIVE_TEST_FLAG_UNSET   BLOCKED_NO_API_KEY
BLOCKED_NOT_SYNTHETIC          BLOCKED_NOT_A_CROP
BLOCKED_MODEL_NOT_ALLOWLISTED  BLOCKED_MODEL_NOT_VISION
BLOCKED_MODEL_REFUSED          BLOCKED_FIELD_CALL_LIMIT
BLOCKED_PAGE_CALL_LIMIT        BLOCKED_DOCUMENT_CALL_LIMIT
BLOCKED_BATCH_CALL_LIMIT       BLOCKED_FIELD_PAID_ATTEMPTS
BLOCKED_SESSION_BUDGET         BLOCKED_DOCUMENT_BUDGET
BLOCKED_DUPLICATE_REQUEST      BLOCKED_PARALLEL_CALL
```

**Every refusal routes the field to human review.** Silently dropping a field
would make a budget cap look like an accuracy result. Only `ALLOW` and
`REUSED_CACHED_RESULT` do not.

---

## 4. Initial limits

Smoke-test values, **not production calibration**. Declared as data in
`configs/multimodal_providers.yaml` under `live_provider.limits`.

| Limit | Value |
|---|---|
| max calls per field | 1 |
| max calls per page | 2 |
| max calls per document | 3 |
| max calls per batch | 5 |
| max paid attempts per field | 1 |
| max session spend | $0.02 |
| max document spend | $0.005 |
| fallback models | disabled |
| parallel paid calls | disabled |
| automatic reruns | disabled |

A truncated or partly-written `limits:` block falls back to these values rather
than to an absent limit.

### Two decisions worth knowing about

**An unknown cost is charged as the full remaining document allowance, not as
zero.** A provider that reports no cost must not be able to make unlimited calls
simply because none of them appeared to cost anything. The pessimistic reading
is the safe one.

**Budgets are checked against money actually billed** (`CostBreakdown.billed_usd`,
which prefers the provider's own figure) and never against `estimated_usd`. That
estimate excludes image tokens and is an explicit lower bound; spending a
session against lower bounds would overrun the cap by construction.

**"Paid attempts" are keyed by field, not by fingerprint.** Re-cropping the same
field produces a new fingerprint and so escapes duplicate protection; without a
field-level cap it could be paid for repeatedly.

---

## 5. Duplicate-call protection

The fingerprint is a SHA-256 over **safe metadata only**:

```
crop_sha256 | field_name | field_type | model_id | prompt_version | schema_version
```

No raw crop bytes and no extracted values — this string reaches audit records
and logs, and neither belongs there.

`prompt_version` and `schema_version` are **derived** from the prompt template
and the required response keys, not hand-maintained. Editing the prompt changes
them automatically, so a cached answer cannot survive a contract change it never
actually satisfied just because nobody bumped a constant.

### Cost is reported in three columns

A cache hit is a saving, and it is reported as a saving:

| Column | Meaning |
|---|---|
| `measured_incremental_usd` | what this run actually added |
| `projected_uncached_usd` | what the same work would have cost with no cache |
| `cache_savings_usd` | the difference |

**Projected cost is never shown as zero because a cache hit occurred.** This is a
deliberate correction of defect D1 recorded in the manual-testing runbook, where
a warm on-disk vision cache made a repeat run display "Escalated: 33" beside
"Projected API: $0.000000" and understated projected cost by 5.5×.

---

## 6. Model selection

Exactly one approved model for the first smoke test:

```yaml
model_allowlist:
  - id: openai/gpt-5-nano
    vision: true
    price_row: gpt-5-nano
```

`vision: true` is a **checked declaration, not decoration** — and it must be a
real boolean. A model whose entry omits it, sets it false, or sets it to the
string `"true"` is refused with `BLOCKED_MODEL_NOT_VISION`. A text-only model
handed an image burns a call to return nothing useful.

Two model classes are refused **at construction**, before a key is ever read, and
config cannot opt back into them:

- **Auto Router** (`openrouter/auto`) — the served model is unknown until after
  you are billed.
- **`:free` variants** — different rate limits, different retention terms, and a
  zero-cost receipt that would prove nothing about the paid path.

`provider: {allow_fallbacks: false}` is sent on **every** request and is not
configurable. A `models:` array is never sent. An aggregator silently
substituting a pricier model is an unbounded spend, and the point of this path is
a bounded one. If the provider reports a different model than was requested,
`model_substituted` is set and recorded — never silently accepted as equivalent.

> **Verify before spending.** `openai/gpt-5-nano` was chosen because
> `configs/prices.yaml` already carries a price row for it verified 2026-07-30,
> and because it is vision-capable and cheap. Model ids on an aggregator change.
> Confirm the id is still listed and still image-capable on OpenRouter before the
> live call; the allowlist is one line to edit.

---

## 7. Cost precedence

OpenRouter reports what it actually charged (`usage.cost`, requested via
`usage: {include: true}`). That figure outranks any local price-table
computation, because it is the only number that is a real charge rather than
list price times reported tokens.

| `basis` | Meaning |
|---|---|
| `provider_reported` | the provider's own charge; `reported_usd` set |
| `measured_usage` | list price over reported tokens; a computation, not an invoice |
| `estimated_usage` | text tokens only, image tokens excluded — an explicit **lower bound** |
| `unknown` | no price row; reported as unknown rather than guessed |

When a provider-reported cost exists, the local figure is computed **alongside**
it rather than overwritten, so the two can be compared — a large gap means the
price row has drifted.

**Token categories that a provider does not report stay `unknown` and are never
invented.** In particular image tokens are not back-computed from a tile formula
we cannot verify against a bill.

---

## 8. Security posture

- The key is read from `OPENROUTER_API_KEY` at call time, never stored on the
  instance beyond the call, never logged, never placed in an error detail, never
  written to config.
- `api_key_env` is **fixed by the adapter** for OpenRouter. A config entry cannot
  redirect it at another variable and quietly borrow a different provider's key.
- Raw provider responses are **hashed and discarded**. `raw_sha256` is kept;
  the body is not, because it can contain transcribed claim values.
- Provider error *messages* are never read into an error detail — only the
  machine-readable code — because a message can echo request content.
- Crop bytes never appear in a repr, a log, an audit record, or a fingerprint.
- `.env.example` carries empty values only. `.env` is gitignored.

---

## 9. Running the one paid call

```bash
# 1. edit configs/multimodal_providers.yaml:  live_provider.enabled: true
# 2. export the three environment values (never commit them)
export OPENROUTER_API_KEY=...            # your key; never written to any file here
export CLAIMROUTE_MULTIMODAL_ENABLED=true
export CLAIMROUTE_LIVE_PROVIDER_TEST=true

# 3. one call, one synthetic crop
python scripts/openrouter_live_smoke.py --receipt eval/results/openrouter_smoke.json
```

The script renders a **fresh synthetic CMS-1500** from the data factory using a
seed reserved for it (90211), shared with no dataset, split, or committed
artifact. It never reads `data/generated/`, the organiser sample, or any
development or holdout split.

Before calling it prints metadata only — model id, crop dimensions, field type,
maximum call counts, maximum spend. It never prints the key, the crop contents,
the expected value, or any patient information.

**It makes exactly one call.** There is no retry loop, the adapter's transport
retries are forced to `max_attempts: 1` for the run, and a failure is not
retried — a failed paid call is a result to read, not a reason to buy another
one. Balance retrieval is a second network call and is therefore opt-in
(`--balance`), so a receipt claiming one external call can say so truthfully.

The receipt records provider, requested vs actual model, outcome, structured
validity, visibility, confidence, grounding result, healthcare validator
verdicts, governor outcome, every token category the provider reported,
provider-reported cost, locally calculated cost, latency, session spend before
and after, and the response hash. It records **that** a value came back and
whether it validated — never what it said.

---

## 10. Test coverage

`tests/test_openrouter_live_policy.py` (57) and `tests/test_openrouter_provider.py` (41).
Both sever the socket layer and drive a full cycle to prove no network access.

| # | Proof | Test |
|---|---|---|
| 1 | provider disabled by default | `test_shipped_config_disables_the_live_path` |
| 2 | missing key prevents calls | `test_missing_api_key_prevents_the_call` |
| 3 | missing live-test flag prevents calls | `test_missing_live_test_flag_prevents_the_call` |
| 4 | non-synthetic input prevents calls | `test_non_synthetic_input_prevents_the_call` |
| 5 | full-page request rejected | `test_full_page_request_is_rejected` |
| 6 | text-only model rejected | `test_text_only_model_is_rejected` |
| 7 | model allowlist enforced | `test_model_allowlist_is_enforced` |
| 8 | session budget enforced | `test_session_budget_is_enforced` |
| 9 | document budget enforced | `test_document_budget_is_enforced` |
| 10 | maximum attempts enforced | `test_paid_attempts_per_field_is_enforced_across_different_crops` |
| 11 | duplicates create no second paid call | `test_duplicate_request_does_not_create_another_paid_call` |
| 12 | structured-response validation works | `test_structured_response_validation_accepts_a_well_formed_answer` |
| 13 | invalid JSON rejected | `test_invalid_json_is_rejected` |
| 14 | provider errors typed | `test_http_errors_are_categorised` |
| 15 | usage/cost metadata normalised | `test_detailed_token_categories_are_normalised_when_reported` |
| 16 | measured and projected stay separate | `test_cache_hit_never_reports_projected_cost_as_zero` |
| 17 | no network calls in unit tests | `test_no_socket_is_opened_anywhere_in_this_module` |
