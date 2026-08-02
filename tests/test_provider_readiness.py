"""One shared readiness verdict, and the states it must keep apart.

The defect these cover: `_provider_policy_snapshot` reported one boolean and one
free-text reason, so six different causes arrived on screen as the same
"disabled by policy". An operator who had exported CLAIMROUTE_MULTIMODAL_ENABLED
but not CLAIMROUTE_LIVE_PROVIDER_TEST saw the identical message as an operator
who had configured nothing at all, and an invalid boolean silently read as
false. "Ready, but this input is ineligible" had no representation whatsoever.

Two rules hold across every test here:

- The readiness verdict is DISPLAY STATE. It never authorises anything, so
  `state is READY` must still leave `LiveCallGovernor` refusing a call on the
  shipped config. That is asserted, not assumed.
- No test may make, or be able to make, a network call.
"""
from pathlib import Path

import pytest
import yaml
from PIL import Image

from app import workspace
from engine.escalation.client import load_config
from engine.escalation.contract import CropImage, MultimodalRequest
from engine.escalation.live_policy import LiveCallGovernor, LiveDecision
from engine.escalation.readiness import (ConfigurationFlagError,
                                         ProviderReadiness, ReadinessState,
                                         evaluate_readiness, parse_flag)

REPO_CONFIG = load_config()
KEY = "OPENROUTER_API_KEY"
ENABLE = "CLAIMROUTE_MULTIMODAL_ENABLED"
LIVE_TEST = "CLAIMROUTE_LIVE_PROVIDER_TEST"

# Never a realistic key shape. A fixture that looks like a credential invites
# someone to paste a real one in beside it.
FAKE_KEY = "test-key-not-a-credential"

FULLY_ENABLED_ENV = {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true"}


def _readiness(env, *, mode="balanced", config=None, **kwargs) -> ProviderReadiness:
    return evaluate_readiness(config=config if config is not None else REPO_CONFIG,
                              env=env, mode=mode, **kwargs)


# --------------------------------------------------------------- gate states


def test_no_key_configured_reports_missing_key():
    readiness = _readiness({ENABLE: "true", LIVE_TEST: "true"})

    assert readiness.state is ReadinessState.MISSING_KEY
    assert readiness.ready is False
    assert KEY in readiness.reason
    assert readiness.required_action


def test_key_present_but_enable_flag_false_reports_disabled():
    """Credentials exist and the operator did nothing wrong; the application
    configuration is simply off. That is a different instruction from a missing
    key, so it must not share a message with one."""
    readiness = _readiness({KEY: FAKE_KEY, LIVE_TEST: "true"})

    assert readiness.state is ReadinessState.DISABLED
    assert readiness.ready is False
    assert ENABLE in readiness.required_action


def test_enable_flag_true_but_live_test_flag_false_reports_test_permission():
    """The exact reported symptom. Exporting CLAIMROUTE_MULTIMODAL_ENABLED and
    restarting used to change nothing on screen, because this state collapsed
    into the same 'disabled by policy' string as a bare clone."""
    readiness = _readiness({KEY: FAKE_KEY, ENABLE: "true"})

    assert readiness.state is ReadinessState.TEST_PERMISSION_REQUIRED
    assert readiness.ready is False
    assert LIVE_TEST in readiness.required_action


def test_the_three_blocked_states_do_not_share_a_message():
    """The regression itself: three causes, one indistinguishable message."""
    missing = _readiness({ENABLE: "true", LIVE_TEST: "true"})
    disabled = _readiness({KEY: FAKE_KEY, LIVE_TEST: "true"})
    permission = _readiness({KEY: FAKE_KEY, ENABLE: "true"})

    reasons = {missing.reason, disabled.reason, permission.reason}
    assert len(reasons) == 3
    states = {missing.state, disabled.state, permission.state}
    assert len(states) == 3


def test_all_gates_true_reports_ready():
    readiness = _readiness(FULLY_ENABLED_ENV)

    assert readiness.state is ReadinessState.READY
    assert readiness.ready is True
    assert readiness.model
    assert readiness.model_allowlisted is True
    assert readiness.model_image_capable is True


def test_ready_is_display_state_and_still_cannot_authorise_a_call():
    """READY means "nothing in the operator's setup is missing", never "billing
    is permitted". The shipped config keeps live_provider.enabled false, so the
    governor must still refuse — checked here so a future edit that widens
    readiness cannot quietly widen spending with it."""
    readiness = _readiness(FULLY_ENABLED_ENV)
    assert readiness.state is ReadinessState.READY

    governor = LiveCallGovernor(REPO_CONFIG, env=dict(FULLY_ENABLED_ENV))
    outcome = governor.preview_authorization(_synthetic_crop_request())

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED


# ------------------------------------------------------------------- model


def test_model_not_allowlisted_reports_model_not_allowed():
    config = _config_with_allowlist([])
    readiness = _readiness(FULLY_ENABLED_ENV, config=config)

    assert readiness.state is ReadinessState.MODEL_NOT_ALLOWED
    assert readiness.ready is False
    assert readiness.model_allowlisted is False


def test_model_without_declared_vision_reports_model_not_allowed():
    resolved = _readiness(FULLY_ENABLED_ENV).model
    config = _config_with_allowlist([{"id": resolved, "vision": False}])
    readiness = _readiness(FULLY_ENABLED_ENV, config=config)

    assert readiness.state is ReadinessState.MODEL_NOT_ALLOWED
    assert readiness.model_image_capable is False


# ------------------------------------------------------------------- input


def test_ready_provider_with_ineligible_input_is_not_reported_as_disabled():
    """A full page is refused because it is a page, not because the provider is
    off. Showing "external provider disabled" here sends the operator to fix a
    setting that is already correct."""
    readiness = _readiness(FULLY_ENABLED_ENV, request=_full_page_request())

    assert readiness.state is ReadinessState.INPUT_INELIGIBLE
    assert readiness.ready is False
    assert readiness.input_eligible is False
    assert "disabled" not in readiness.reason.lower()


def test_ready_provider_with_approved_synthetic_crop_stays_ready():
    readiness = _readiness(FULLY_ENABLED_ENV, request=_synthetic_crop_request())

    assert readiness.state is ReadinessState.READY
    assert readiness.input_eligible is True


def test_non_synthetic_input_is_ineligible_not_disabled():
    readiness = _readiness(FULLY_ENABLED_ENV,
                           request=_synthetic_crop_request(synthetic=False))

    assert readiness.state is ReadinessState.INPUT_INELIGIBLE
    assert readiness.ready is False


def test_input_eligibility_is_unknown_when_no_input_is_supplied():
    """Absence of a selected document is not a refusal. The panel needs to say
    "ready" before anything is picked."""
    readiness = _readiness(FULLY_ENABLED_ENV)

    assert readiness.input_eligible is None
    assert readiness.state is ReadinessState.READY


# -------------------------------------------------------- boolean parsing


@pytest.mark.parametrize("raw", ["true", "TRUE", "  True  ", "1", "yes", "YES",
                                 "on", "ON", "\ton\n"])
def test_documented_truthy_values_are_accepted_case_and_whitespace_insensitively(raw):
    assert parse_flag(ENABLE, raw) is True


@pytest.mark.parametrize("raw", ["false", "FALSE", " 0 ", "no", "off", "", None])
def test_documented_falsy_values_are_accepted(raw):
    assert parse_flag(ENABLE, raw) is False


@pytest.mark.parametrize("raw", ["yeah-sure", "enabled", "2", "y", "t"])
def test_invalid_boolean_raises_rather_than_silently_reading_as_false(raw):
    """Silently reading an unrecognised value as false is how "I set the flag"
    and "the flag is off" become true at the same time."""
    with pytest.raises(ConfigurationFlagError) as excinfo:
        parse_flag(ENABLE, raw)

    assert ENABLE in str(excinfo.value)
    assert raw not in str(excinfo.value) or "true" in str(excinfo.value)


def test_invalid_boolean_env_value_surfaces_as_configuration_error():
    readiness = _readiness({KEY: FAKE_KEY, ENABLE: "yeah-sure", LIVE_TEST: "true"})

    assert readiness.state is ReadinessState.CONFIGURATION_ERROR
    assert readiness.ready is False
    assert ENABLE in readiness.reason
    assert readiness.required_action


# ------------------------------------------------------------ safety/errors


def test_initialization_failure_is_reported_not_raised():
    """A structurally broken model table must render as a state. A traceback on
    the results page loses the local work already done, which is a worse outcome
    than an unavailable provider."""
    broken = yaml.safe_load(yaml.safe_dump(REPO_CONFIG))
    broken["operating_mode_models"] = {
        "operating_modes": {"balanced": {"primary": "no-such-alias"}},
        "models": {},
    }

    readiness = _readiness(FULLY_ENABLED_ENV, config=broken)

    assert readiness.ready is False
    assert readiness.state is ReadinessState.INITIALIZATION_ERROR
    assert readiness.required_action


def test_diagnostics_never_expose_the_key_in_any_form():
    """Not the value, not a prefix, not a length, not a hash."""
    import hashlib

    readiness = _readiness(FULLY_ENABLED_ENV)
    rendered = repr(readiness) + repr(readiness.diagnostics())

    assert FAKE_KEY not in rendered
    assert FAKE_KEY[:6] not in rendered
    assert str(len(FAKE_KEY)) not in rendered.replace("gpt-5", "").replace("3.5", "")
    assert hashlib.sha256(FAKE_KEY.encode()).hexdigest()[:8] not in rendered


def test_diagnostics_report_every_gate_the_operator_must_check():
    readiness = _readiness({KEY: FAKE_KEY, ENABLE: "true"})
    diagnostics = readiness.diagnostics()

    for expected in ("OPENROUTER_API_KEY_PRESENT", "CLAIMROUTE_MULTIMODAL_ENABLED",
                     "CLAIMROUTE_LIVE_PROVIDER_TEST", "CONFIG_PROVIDER_ENABLED",
                     "SELECTED_MODE", "SELECTED_MODEL", "MODEL_ALLOWLISTED",
                     "MODEL_IMAGE_CAPABLE", "INPUT_ELIGIBLE", "PROVIDER_READY",
                     "BLOCKING_REASON"):
        assert expected in diagnostics

    assert diagnostics["OPENROUTER_API_KEY_PRESENT"] is True
    assert diagnostics["CLAIMROUTE_LIVE_PROVIDER_TEST"] is False
    assert diagnostics["PROVIDER_READY"] is False
    assert diagnostics["BLOCKING_REASON"] == ReadinessState.TEST_PERMISSION_REQUIRED.value


def test_environment_change_is_visible_without_a_process_restart():
    """Readiness is recomputed per call, so a refresh reflects the current
    environment. A cached verdict would make "restart and try again" the only
    way to see a corrected setting."""
    before = _readiness({KEY: FAKE_KEY, ENABLE: "true"})
    after = _readiness(FULLY_ENABLED_ENV)

    assert before.state is ReadinessState.TEST_PERMISSION_REQUIRED
    assert after.state is ReadinessState.READY


# ------------------------------------------------- shared with the snapshot


def test_the_workspace_snapshot_reports_the_same_state_as_the_contract():
    """The UI must not recompute gating. One backend verdict, rendered."""
    for env in ({}, {KEY: FAKE_KEY}, {KEY: FAKE_KEY, ENABLE: "true"},
                FULLY_ENABLED_ENV):
        snapshot = workspace._provider_policy_snapshot(env=env, mode="balanced")
        contract = _readiness(env)

        assert snapshot["readiness_state"] == contract.state.value
        assert snapshot["provider_ready"] is contract.ready
        assert snapshot["readiness_reason"] == contract.reason
        assert snapshot["readiness_required_action"] == contract.required_action
        # `provider_enabled` means "the enable switches are on", not "a call may
        # happen". It stays true with the key absent so the panel can open and
        # name the credential as the remaining blocker.
        assert snapshot["provider_enabled"] is (
            contract.state not in (ReadinessState.DISABLED,
                                   ReadinessState.TEST_PERMISSION_REQUIRED,
                                   ReadinessState.CONFIGURATION_ERROR))


def test_the_snapshot_keeps_the_keys_the_existing_ui_reads():
    """Additive change. Removing a key here breaks panels this task must not
    touch."""
    snapshot = workspace._provider_policy_snapshot(env={}, mode="balanced")

    for key in ("provider_enabled", "provider_name", "configured_model",
                "operating_mode", "model_alias", "model_supports_images",
                "model_allowlisted", "credential_available",
                "external_call_attempted", "external_call_count",
                "reason_not_attempted", "final_workflow_state", "no_data_sent"):
        assert key in snapshot


def test_the_snapshot_never_carries_the_key():
    snapshot = workspace._provider_policy_snapshot(
        env=dict(FULLY_ENABLED_ENV), mode="balanced")

    assert FAKE_KEY not in repr(snapshot)


# ----------------------------------------------------------------- helpers


def _config_with_allowlist(allowlist: list) -> dict:
    config = yaml.safe_load(yaml.safe_dump(REPO_CONFIG))
    config["live_provider"]["model_allowlist"] = allowlist
    config["operating_mode_models"] = REPO_CONFIG.get("operating_mode_models")
    return config


def _request(width: int, height: int, *, page_px, synthetic: bool) -> MultimodalRequest:
    image = Image.new("RGB", (width, height), "white")
    return MultimodalRequest(
        field_name="total_charge",
        crop=CropImage.from_pil(image, source_page_px=page_px,
                                region_px=(width, height)),
        expectation="", doc_id="synthetic-doc", page_id="p1",
        synthetic=synthetic)


def _synthetic_crop_request(*, synthetic: bool = True) -> MultimodalRequest:
    # ~1% of the page: unambiguously a field crop under max_page_fraction 0.25.
    return _request(120, 40, page_px=(1200, 1600), synthetic=synthetic)


def _full_page_request() -> MultimodalRequest:
    return _request(1200, 1600, page_px=(1200, 1600), synthetic=True)
