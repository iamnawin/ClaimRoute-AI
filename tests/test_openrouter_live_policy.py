"""Spending guardrails for the paid OpenRouter path.

Every test here is deterministic and offline. The governor never performs a
call — it only authorises one — so nothing in this file can reach a network even
by mistake; `test_no_network_access_is_possible_from_the_governor` proves it by
severing the socket layer for the duration of a full authorise/record cycle.

No real API key is read, written, or asserted on. The placeholder below is
obviously not a credential.
"""
import socket

import pytest
from PIL import Image

from engine.escalation.contract import (CostBreakdown, CropImage, MultimodalRequest,
                                        MultimodalResult)
from engine.escalation.live_policy import (LIVE_TEST_ENV, MULTIMODAL_ENABLED_ENV,
                                           LiveCallGovernor, LiveDecision,
                                           SpendLimits, fingerprint)

MODEL = "openai/gpt-5-nano"
FAKE_KEY = "placeholder-not-a-real-key"

LIVE_ENV = {MULTIMODAL_ENABLED_ENV: "true", LIVE_TEST_ENV: "true",
            "OPENROUTER_API_KEY": FAKE_KEY}


# --------------------------------------------------------------------- helpers

def _crop(page=(1700, 2200), region=(90, 32), size=(90, 32)):
    return CropImage.from_pil(Image.new("RGB", size, "white"),
                              source_page_px=page, region_px=region)


def _request(field_name="provider_npi", *, synthetic=True, crop=None,
             doc_id="synthetic-doc", page_id="p1"):
    return MultimodalRequest(field_name, crop or _crop(),
                             expectation="a 10-digit NPI number",
                             doc_id=doc_id, page_id=page_id, synthetic=synthetic)


def _config(*, enabled=True, allowlist=None, limits=None, duplicate=None):
    return {
        "request_policy": {"crop_only": True, "max_page_fraction": 0.25,
                           "require_page_provenance": True},
        "providers": {"openrouter": {"kind": "openrouter_chat_completions",
                                     "model": MODEL,
                                     "api_key_env": "OPENROUTER_API_KEY"}},
        "live_provider": {
            "enabled": enabled,
            "provider": "openrouter",
            "live_test_env": LIVE_TEST_ENV,
            "model_allowlist": (allowlist if allowlist is not None
                                else [{"id": MODEL, "vision": True}]),
            "limits": limits or {},
            "duplicate_policy": duplicate or {"reuse_previous_result": True},
        },
    }


def _governor(env=None, **cfg):
    return LiveCallGovernor(_config(**cfg), env=dict(env if env is not None else LIVE_ENV))


def _result(billed=None, *, called=True, request_id="req-1", reported=True):
    """A completed call whose cost is known, unknown, or never incurred."""
    cost = CostBreakdown(basis="provider_reported" if reported else "unknown",
                         reported_usd=billed if reported else None,
                         measured_usd=None if reported else billed)
    r = MultimodalResult(request_id=request_id, cost=cost)
    r.called_provider = called
    return r


def _generous(**overrides):
    """Counts wide open so a money test cannot be blocked by a count first."""
    base = {"max_calls_per_field": 50, "max_calls_per_page": 50,
            "max_calls_per_document": 50, "max_calls_per_batch": 50,
            "max_paid_attempts_per_field": 50,
            "max_session_spend_usd": 1.0, "max_document_spend_usd": 1.0}
    base.update(overrides)
    return base


# ----------------------------------------------------- 1. disabled by default

def test_shipped_config_disables_the_live_path():
    """The tracked config must permit zero spending as committed."""
    from engine.escalation.client import load_config

    cfg = load_config()
    assert cfg["enabled"] is False
    assert cfg["live_provider"]["enabled"] is False
    gov = LiveCallGovernor(cfg, env=dict(LIVE_ENV))
    outcome = gov.authorize(_request(), model=MODEL)
    assert outcome.decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED
    assert not outcome.allowed


def test_governor_with_no_config_at_all_refuses():
    gov = LiveCallGovernor(None, env=dict(LIVE_ENV))
    assert gov.authorize(_request()).decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED


def test_adapter_enable_flag_alone_does_not_open_the_live_path():
    """Enabling the adapter for a fake provider must not enable a paid one."""
    env = {MULTIMODAL_ENABLED_ENV: "true", LIVE_TEST_ENV: "true",
           "OPENROUTER_API_KEY": FAKE_KEY}
    assert _governor(env=env, enabled=False).authorize(_request()).decision \
        is LiveDecision.BLOCKED_LIVE_PATH_DISABLED


def test_multimodal_enabled_flag_is_required():
    env = dict(LIVE_ENV, **{MULTIMODAL_ENABLED_ENV: "false"})
    assert _governor(env=env).authorize(_request()).decision \
        is LiveDecision.BLOCKED_ADAPTER_DISABLED


# ------------------------------------------------------- 2. missing key blocks

def test_missing_api_key_prevents_the_call():
    env = dict(LIVE_ENV)
    env.pop("OPENROUTER_API_KEY")
    outcome = _governor(env=env).authorize(_request())
    assert outcome.decision is LiveDecision.BLOCKED_NO_API_KEY
    assert outcome.route_to_human_review


def test_blank_api_key_is_treated_as_missing():
    env = dict(LIVE_ENV, OPENROUTER_API_KEY="   ")
    assert _governor(env=env).authorize(_request()).decision \
        is LiveDecision.BLOCKED_NO_API_KEY


def test_openai_key_cannot_substitute_for_the_openrouter_key():
    """A key for another provider must not unlock this path."""
    env = {MULTIMODAL_ENABLED_ENV: "true", LIVE_TEST_ENV: "true",
           "OPENAI_API_KEY": FAKE_KEY}
    assert _governor(env=env).authorize(_request()).decision \
        is LiveDecision.BLOCKED_NO_API_KEY


# --------------------------------------------------- 3. live-test flag blocks

def test_missing_live_test_flag_prevents_the_call():
    env = dict(LIVE_ENV)
    env.pop(LIVE_TEST_ENV)
    assert _governor(env=env).authorize(_request()).decision \
        is LiveDecision.BLOCKED_LIVE_TEST_FLAG_UNSET


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "maybe"])
def test_only_explicit_truth_enables_the_live_test_flag(value):
    env = dict(LIVE_ENV, **{LIVE_TEST_ENV: value})
    assert _governor(env=env).authorize(_request()).decision \
        is LiveDecision.BLOCKED_LIVE_TEST_FLAG_UNSET


# ----------------------------------------------------- 4. non-synthetic input

def test_non_synthetic_input_prevents_the_call():
    outcome = _governor().authorize(_request(synthetic=False))
    assert outcome.decision is LiveDecision.BLOCKED_NOT_SYNTHETIC
    assert outcome.route_to_human_review


# ------------------------------------------------------ 5. full page rejected

def test_full_page_request_is_rejected():
    full = CropImage.from_pil(Image.new("RGB", (400, 500), "white"),
                              source_page_px=(400, 500), region_px=(400, 500))
    outcome = _governor().authorize(_request(crop=full))
    assert outcome.decision is LiveDecision.BLOCKED_NOT_A_CROP
    assert "full pages are never sent" in outcome.reason


def test_image_without_page_provenance_cannot_be_proven_a_crop():
    unprovable = CropImage.from_pil(Image.new("RGB", (90, 32), "white"))
    outcome = _governor().authorize(_request(crop=unprovable))
    assert outcome.decision is LiveDecision.BLOCKED_NOT_A_CROP


def test_a_crop_just_over_the_fraction_limit_is_rejected():
    over = CropImage.from_pil(Image.new("RGB", (60, 60), "white"),
                              source_page_px=(100, 100), region_px=(60, 60))
    assert _governor().authorize(_request(crop=over)).decision \
        is LiveDecision.BLOCKED_NOT_A_CROP


# ------------------------------------------------------ 6. text-only rejected

def test_text_only_model_is_rejected():
    """A model without a checked vision declaration never sees an image."""
    outcome = _governor(allowlist=[{"id": MODEL, "vision": False}]).authorize(_request())
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_NOT_VISION
    assert outcome.route_to_human_review


def test_missing_vision_declaration_is_not_treated_as_vision_capable():
    outcome = _governor(allowlist=[{"id": MODEL}]).authorize(_request())
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_NOT_VISION


@pytest.mark.parametrize("truthy", ["true", 1, "yes"])
def test_vision_must_be_a_real_boolean_true(truthy):
    """A truthy string is not a declaration; only `vision: true` counts."""
    outcome = _governor(allowlist=[{"id": MODEL, "vision": truthy}]).authorize(_request())
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_NOT_VISION


# ------------------------------------------------------- 7. allowlist enforced

def test_model_allowlist_is_enforced():
    outcome = _governor().authorize(_request(), model="anthropic/claude-opus-4")
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_NOT_ALLOWLISTED


def test_empty_allowlist_blocks_every_model():
    assert _governor(allowlist=[]).authorize(_request(), model=MODEL).decision \
        is LiveDecision.BLOCKED_MODEL_NOT_ALLOWLISTED


def test_auto_router_is_refused_even_if_allowlisted():
    """Config cannot opt back into a model that is unknown until after billing."""
    gov = _governor(allowlist=[{"id": "openrouter/auto", "vision": True}])
    outcome = gov.authorize(_request(), model="openrouter/auto")
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_REFUSED
    assert "Auto Router" in outcome.reason


def test_free_model_variants_are_refused_even_if_allowlisted():
    gov = _governor(allowlist=[{"id": "some/model:free", "vision": True}])
    outcome = gov.authorize(_request(), model="some/model:free")
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_REFUSED


def test_the_approved_model_passes_every_gate():
    outcome = _governor().authorize(_request())
    assert outcome.decision is LiveDecision.ALLOW
    assert outcome.allowed and not outcome.route_to_human_review
    assert outcome.model == MODEL


# --------------------------------------------------------- 8. session budget

def test_session_budget_is_enforced():
    gov = _governor(limits=_generous(max_session_spend_usd=0.01))
    first = gov.authorize(_request("provider_npi"))
    assert first.allowed
    gov.record_call(first, _result(0.01))

    after = gov.authorize(_request("attending_npi"))
    assert after.decision is LiveDecision.BLOCKED_SESSION_BUDGET
    assert after.route_to_human_review
    assert gov.session_remaining_usd == pytest.approx(0.0)


def test_session_budget_survives_spend_spread_over_documents():
    gov = _governor(limits=_generous(max_session_spend_usd=0.01,
                                     max_document_spend_usd=1.0))
    for i, doc in enumerate(("d1", "d2")):
        o = gov.authorize(_request(f"npi_{i}", doc_id=doc))
        assert o.allowed
        gov.record_call(o, _result(0.005, request_id=f"r{i}"))
    blocked = gov.authorize(_request("npi_3", doc_id="d3"))
    assert blocked.decision is LiveDecision.BLOCKED_SESSION_BUDGET


def test_default_session_cap_is_two_cents():
    assert SpendLimits().max_session_spend_usd == 0.02


# -------------------------------------------------------- 9. document budget

def test_document_budget_is_enforced():
    gov = _governor(limits=_generous(max_session_spend_usd=1.0,
                                     max_document_spend_usd=0.005))
    first = gov.authorize(_request("provider_npi", doc_id="doc-a"))
    gov.record_call(first, _result(0.005))

    same_doc = gov.authorize(_request("attending_npi", doc_id="doc-a"))
    assert same_doc.decision is LiveDecision.BLOCKED_DOCUMENT_BUDGET

    # A different document still has its own allowance.
    other_doc = gov.authorize(_request("attending_npi", doc_id="doc-b"))
    assert other_doc.allowed


def test_unknown_cost_is_charged_as_the_full_document_allowance():
    """A provider that reports nothing must not get unlimited calls."""
    gov = _governor(limits=_generous(max_session_spend_usd=1.0,
                                     max_document_spend_usd=0.005))
    first = gov.authorize(_request("provider_npi", doc_id="doc-a"))
    gov.record_call(first, _result(None, reported=False))     # cost unknown

    assert gov.document_remaining_usd("doc-a") == pytest.approx(0.0)
    assert gov.authorize(_request("attending_npi", doc_id="doc-a")).decision \
        is LiveDecision.BLOCKED_DOCUMENT_BUDGET


# -------------------------------------------------------- 10. maximum attempts

def test_calls_per_field_limit_is_enforced():
    gov = _governor(limits=_generous(max_calls_per_field=1))
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0001))
    # A different crop for the same field: a new fingerprint, so this is not
    # caught by duplicate protection.
    again = gov.authorize(_request("provider_npi", crop=_crop(size=(91, 32))))
    assert again.decision in (LiveDecision.BLOCKED_FIELD_PAID_ATTEMPTS,
                              LiveDecision.BLOCKED_FIELD_CALL_LIMIT)


def test_paid_attempts_per_field_is_enforced_across_different_crops():
    gov = _governor(limits=_generous(max_paid_attempts_per_field=1))
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0001))
    again = gov.authorize(_request("provider_npi", crop=_crop(size=(91, 32))))
    assert again.decision is LiveDecision.BLOCKED_FIELD_PAID_ATTEMPTS


def test_an_unbilled_call_does_not_consume_a_paid_attempt():
    gov = _governor(limits=_generous(max_paid_attempts_per_field=1))
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0))          # provider refused before billing
    again = gov.authorize(_request("provider_npi", crop=_crop(size=(91, 32))))
    assert again.allowed


def test_page_document_and_batch_limits_are_enforced_in_that_order():
    gov = _governor(limits=_generous(max_calls_per_page=2))
    for i in range(2):
        o = gov.authorize(_request(f"npi_{i}", page_id="p1"))
        assert o.allowed
        gov.record_call(o, _result(0.0001, request_id=f"r{i}"))
    assert gov.authorize(_request("npi_x", page_id="p1")).decision \
        is LiveDecision.BLOCKED_PAGE_CALL_LIMIT


def test_document_call_limit_is_enforced():
    gov = _governor(limits=_generous(max_calls_per_document=3))
    for i in range(3):
        o = gov.authorize(_request(f"npi_{i}", page_id=f"p{i}"))
        gov.record_call(o, _result(0.0001, request_id=f"r{i}"))
    assert gov.authorize(_request("npi_x", page_id="p9")).decision \
        is LiveDecision.BLOCKED_DOCUMENT_CALL_LIMIT


def test_batch_call_limit_is_enforced():
    gov = _governor(limits=_generous(max_calls_per_batch=5))
    for i in range(5):
        o = gov.authorize(_request(f"npi_{i}", doc_id=f"d{i}"))
        gov.record_call(o, _result(0.0001, request_id=f"r{i}"))
    assert gov.authorize(_request("npi_x", doc_id="d9")).decision \
        is LiveDecision.BLOCKED_BATCH_CALL_LIMIT


def test_smoke_test_limits_are_the_documented_defaults():
    limits = SpendLimits()
    assert (limits.max_calls_per_field, limits.max_calls_per_page,
            limits.max_calls_per_document, limits.max_calls_per_batch) == (1, 2, 3, 5)
    assert limits.max_paid_attempts_per_field == 1
    assert limits.max_document_spend_usd == 0.005
    assert not limits.allow_fallback_models
    assert not limits.allow_parallel_paid_calls
    assert not limits.allow_automatic_reruns


def test_a_truncated_limits_block_falls_back_to_the_tight_defaults():
    limits = SpendLimits.from_config({"max_calls_per_field": 2, "nonsense": 99})
    assert limits.max_calls_per_field == 2
    assert limits.max_session_spend_usd == 0.02


def test_parallel_paid_calls_are_blocked_while_one_is_in_flight():
    gov = _governor(limits=_generous())
    first = gov.authorize(_request("provider_npi"))
    assert first.allowed
    second = gov.authorize(_request("attending_npi"))     # first not recorded yet
    assert second.decision is LiveDecision.BLOCKED_PARALLEL_CALL


def test_release_clears_an_in_flight_call_that_never_happened():
    gov = _governor(limits=_generous())
    gov.authorize(_request("provider_npi"))
    gov.release()
    assert gov.authorize(_request("attending_npi")).allowed


# ------------------------------------------------------------ 11. duplicates

def test_duplicate_request_does_not_create_another_paid_call():
    gov = _governor(limits=_generous())
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0004, request_id="req-original"))

    repeat = gov.authorize(_request("provider_npi"))
    assert repeat.decision is LiveDecision.REUSED_CACHED_RESULT
    assert not repeat.allowed                     # crucially: no second call
    assert repeat.reused_from == "req-original"
    assert repeat.avoided_cost_usd == pytest.approx(0.0004)
    assert gov.calls_made == 1
    assert gov.paid_calls_avoided == 1


def test_a_reused_answer_does_not_go_to_human_review():
    gov = _governor(limits=_generous())
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0004))
    assert not gov.authorize(_request("provider_npi")).route_to_human_review


def test_duplicate_can_be_blocked_outright_instead_of_reused():
    gov = _governor(limits=_generous(),
                    duplicate={"reuse_previous_result": False})
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0004))
    repeat = gov.authorize(_request("provider_npi"))
    assert repeat.decision is LiveDecision.BLOCKED_DUPLICATE_REQUEST
    assert repeat.route_to_human_review


def test_fingerprint_is_deterministic_across_identical_requests():
    a, b = _request("provider_npi"), _request("provider_npi")
    assert fingerprint(a, MODEL) == fingerprint(b, MODEL)


def test_fingerprint_changes_with_crop_field_and_model():
    base = _request("provider_npi")
    assert fingerprint(base, MODEL) != fingerprint(_request("attending_npi"), MODEL)
    assert fingerprint(base, MODEL) != fingerprint(base, "other/model")
    assert fingerprint(base, MODEL) != fingerprint(
        _request("provider_npi", crop=_crop(size=(91, 32))), MODEL)


def test_fingerprint_changes_when_the_prompt_contract_changes(monkeypatch):
    """A cached answer must not survive a change to the question."""
    base = _request("provider_npi")
    before = fingerprint(base, MODEL)
    monkeypatch.setattr("engine.escalation.live_policy.PROMPT_VERSION", "deadbeef")
    assert fingerprint(base, MODEL) != before


def test_fingerprint_carries_no_crop_bytes_or_values():
    req = _request("provider_npi")
    fp = fingerprint(req, MODEL)
    assert len(fp) == 32 and all(c in "0123456789abcdef" for c in fp)
    assert req.crop.png_bytes.hex() not in fp


# ------------------------------- 16. measured and projected costs stay separate

def test_cache_hit_never_reports_projected_cost_as_zero():
    """The saving is reported as a saving, not as the work having been free."""
    gov = _governor(limits=_generous())
    first = gov.authorize(_request("provider_npi"))
    gov.record_call(first, _result(0.0004))
    gov.authorize(_request("provider_npi"))       # duplicate, served from cache

    report = gov.session_report()
    assert report["measured_incremental_usd"] == pytest.approx(0.0004)
    assert report["projected_uncached_usd"] == pytest.approx(0.0008)
    assert report["cache_savings_usd"] == pytest.approx(0.0004)
    assert report["projected_uncached_usd"] > 0


def test_measured_and_projected_are_equal_when_nothing_was_cached():
    gov = _governor(limits=_generous())
    o = gov.authorize(_request("provider_npi"))
    gov.record_call(o, _result(0.0004))
    report = gov.session_report()
    assert report["measured_incremental_usd"] == report["projected_uncached_usd"]
    assert report["cache_savings_usd"] == 0.0


def test_session_report_states_the_limits_it_enforced():
    report = _governor().session_report()
    assert report["limits"]["max_session_spend_usd"] == 0.02
    assert report["calls_made"] == 0
    assert report["measured_incremental_usd"] == 0.0


def test_blocked_outcomes_are_never_booked_as_spend():
    gov = _governor(enabled=False)
    blocked = gov.authorize(_request())
    gov.record_call(blocked, _result(9.99))       # must be ignored entirely
    assert gov.session_spend_usd == 0.0
    assert gov.calls_made == 0


def test_every_blocked_decision_routes_to_human_review():
    """No refusal may leave a field silently unanswered."""
    for decision in LiveDecision:
        outcome_needs_review = decision not in (LiveDecision.ALLOW,
                                                LiveDecision.REUSED_CACHED_RESULT)
        from engine.escalation.live_policy import LiveCallOutcome
        assert LiveCallOutcome(decision).route_to_human_review is outcome_needs_review


def test_outcome_dict_is_audit_safe():
    outcome = _governor().authorize(_request())
    d = outcome.to_dict()
    assert set(d) >= {"decision", "reason", "fingerprint", "allowed",
                      "route_to_human_review"}
    blob = repr(d)
    assert FAKE_KEY not in blob
    assert "png" not in blob.lower()


# ------------------------------------------------------------ 17. no network

def test_no_network_access_is_possible_from_the_governor(monkeypatch):
    """Sever the socket layer, then run a full authorise/record cycle."""
    def refuse(*args, **kwargs):
        raise AssertionError("unit tests must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    gov = _governor(limits=_generous())
    outcome = gov.authorize(_request("provider_npi"))
    assert outcome.allowed
    gov.record_call(outcome, _result(0.0004))
    assert gov.session_report()["calls_made"] == 1
