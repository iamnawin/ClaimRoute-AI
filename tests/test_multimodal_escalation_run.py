"""Automatic multi-field escalation stays governed, bounded, and offline.

Every test here builds its own config and environment dict, so nothing reads the
repository's real provider configuration and no test can be made to pass by
turning the live path on. No test performs or permits a network call: the runner
is always given a stub that records its inputs.
"""
from __future__ import annotations

from PIL import Image

from app import multimodal_permission
from engine.escalation.client import request_from_page
from engine.escalation.live_policy import LiveCallGovernor


def _config(*, key=True, enabled=True, live_enabled=True,
            max_calls_per_document=3) -> tuple[dict, dict]:
    config = {
        "enabled": enabled,
        "request_policy": {
            "crop_only": True, "max_page_fraction": .25,
            "require_page_provenance": True, "synthetic_data_only": True,
        },
        "transport": {"max_attempts": 3, "retry_on_invalid_response": False},
        "providers": {"openrouter": {
            "kind": "openrouter_chat_completions",
            "model": "qwen/qwen3.7-flash", "api_key_env": "OPENROUTER_API_KEY",
        }},
        "live_provider": {
            "enabled": live_enabled, "provider": "openrouter",
            "live_test_env": "CLAIMROUTE_LIVE_PROVIDER_TEST",
            "model_allowlist": [{"id": "qwen/qwen3.7-flash", "vision": True}],
            "limits": {
                "max_calls_per_field": 1, "max_calls_per_page": 9,
                "max_calls_per_document": max_calls_per_document,
                "max_calls_per_batch": 9,
                "max_paid_attempts_per_field": 1,
                "max_session_spend_usd": .02,
                "max_document_spend_usd": .005,
                "allow_fallback_models": False,
                "allow_parallel_paid_calls": False,
                "allow_automatic_reruns": False,
            },
            "duplicate_policy": {"reuse_previous_result": True},
        },
        "operating_mode_models": {
            "models": {"fast": {"model_id": "qwen/qwen3.7-flash",
                                "supports_images": True}},
            "operating_modes": {
                "economy": {"primary": "fast"},
                "balanced": {"primary": "fast"},
                "accuracy": {"primary": "fast"},
            },
        },
    }
    env = {
        "CLAIMROUTE_MULTIMODAL_ENABLED": "true",
        "CLAIMROUTE_LIVE_PROVIDER_TEST": "true",
    }
    if key:
        env["OPENROUTER_API_KEY"] = "synthetic-test-key"
    return config, env


def _request(field_name="billing_provider_npi", *, synthetic=True):
    page = Image.new("RGB", (400, 300), "white")
    return request_from_page(
        page, (30, 30, 100, 55), field_name,
        doc_id="synthetic-doc", page_id="p1", synthetic=synthetic)


def _candidates(*names) -> list[dict]:
    return [{"page": 1, "field_name": name} for name in names]


class _Recorder:
    """Stands in for run_one_candidate. Records calls; never opens a socket."""

    def __init__(self, outcome="ACCEPTED", called=True):
        self.calls = []
        self.outcome = outcome
        self.called = called

    def __call__(self, request, **kwargs):
        self.calls.append((request, kwargs))
        field = request.field_name if request is not None else ""
        return {
            "fingerprint": f"fp-{field}-{len(self.calls)}",
            "field_name": field,
            "called_provider": self.called,
            "external_calls_made": int(self.called),
            "measured_cost_usd": 0.00001,
            "final_field_outcome": self.outcome,
        }, ("value" if self.outcome == "ACCEPTED" else None)


def _runner_kwargs(governor, config, *, candidates, receipts=None,
                   applied=None, synthetic=True):
    return {
        "enabled": True, "confirmed": True, "synthetic_attested": synthetic,
        "governor": governor, "config": config,
        "request_builder": lambda row: _request(row["field_name"]),
        "context_builder": lambda row: {},
        "apply_result": (lambda row, value, receipt:
                         applied.append((row["field_name"], value))
                         if applied is not None else None),
        "receipts": receipts if receipts is not None else {},
    }


def test_all_eligible_fields_are_processed_in_one_run():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    runner, applied = _Recorder(), []
    candidates = _candidates("billing_provider_npi", "patient_sex", "total_charge")

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates, applied=applied))

    assert summary["attempted"] == 3
    assert summary["accepted"] == 3
    assert summary["external_calls"] == 3
    assert [name for name, _ in applied] == [
        "billing_provider_npi", "patient_sex", "total_charge"]


def test_document_call_limit_stops_the_run_early():
    """A bound that every later field would also hit ends the loop.

    The governor is the authority: the runner does not carry its own counter, so
    this proves the limit is enforced by policy and not re-implemented in the UI.
    """
    config, env = _config(max_calls_per_document=2)
    governor = LiveCallGovernor(config, env=env)
    runner = _Recorder()
    candidates = _candidates("billing_provider_npi", "patient_sex", "total_charge")

    # Consume the document allowance through the governor's own accounting.
    for name in ("billing_provider_npi", "patient_sex"):
        outcome = governor.authorize(_request(name), model=governor.model)
        assert outcome.allowed
        governor.release()
        governor._counters.per_document["synthetic-doc"] = (
            governor._counters.per_document.get("synthetic-doc", 0) + 1)

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates))

    assert runner.calls == []
    assert summary["attempted"] == 0
    assert "max_calls_per_document" in summary["stopped_reason"]


def test_duplicate_fingerprints_are_not_charged_twice():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    runner = _Recorder()
    candidates = _candidates("billing_provider_npi")
    # A receipt already held for this exact request means the session paid once.
    preview = governor.preview_authorization(
        _request("billing_provider_npi"), model=governor.model)
    receipts = {preview.fingerprint: {"external_calls_made": 1}}

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates,
                         receipts=receipts))

    assert runner.calls == []
    assert summary["attempted"] == 0
    assert summary["blocked"] == 1


def test_validation_failure_leaves_the_field_unresolved_but_still_counts_cost():
    """A rejected answer is not a free call. The spend is real and reported."""
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    runner = _Recorder(outcome="HUMAN_REVIEW_REQUIRED")
    candidates = _candidates("billing_provider_npi")

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates))

    assert summary["attempted"] == 1
    assert summary["accepted"] == 0
    assert summary["rejected"] == 1
    assert summary["external_calls"] == 1
    assert summary["measured_cost_usd"] > 0


def test_non_synthetic_input_makes_no_call():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)
    runner = _Recorder()
    candidates = _candidates("billing_provider_npi")

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates, synthetic=False))

    assert runner.calls == []
    assert summary["attempted"] == 0
    assert summary["external_calls"] == 0


def test_disabled_live_config_blocks_every_field():
    config, env = _config(live_enabled=False)
    governor = LiveCallGovernor(config, env=env)
    runner = _Recorder()
    candidates = _candidates("billing_provider_npi", "patient_sex")

    summary = multimodal_permission.run_eligible_fields(
        candidates, runner=runner,
        **_runner_kwargs(governor, config, candidates=candidates))

    assert runner.calls == []
    assert summary["external_calls"] == 0


def test_blockers_name_each_unmet_requirement_separately():
    config, env = _config(key=False, enabled=False, live_enabled=False)
    governor = LiveCallGovernor(config, env={})

    rows = multimodal_permission.enablement_blockers(
        governor=governor, config=config, synthetic_attested=False,
        request=None, candidates=0)
    unmet = {row.key for row in multimodal_permission.unmet(rows)}

    assert {"provider_configuration", "environment_flag", "credential",
            "synthetic_input", "crop_available", "eligible_fields"} <= unmet


def test_blockers_clear_when_every_requirement_is_met():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)

    rows = multimodal_permission.enablement_blockers(
        governor=governor, config=config, synthetic_attested=True,
        request=_request(), candidates=2)

    assert multimodal_permission.unmet(rows) == []


def test_credential_blocker_never_exposes_the_key_value():
    config, env = _config()
    governor = LiveCallGovernor(config, env=env)

    rows = multimodal_permission.enablement_blockers(
        governor=governor, config=config, synthetic_attested=True,
        request=_request(), candidates=1)
    credential = next(row for row in rows if row.key == "credential")

    assert credential.satisfied
    assert "synthetic-test-key" not in credential.detail
    assert "OPENROUTER_API_KEY" in credential.detail
