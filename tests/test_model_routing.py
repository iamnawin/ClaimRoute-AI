"""Operating mode -> model alias -> exact model id routing.

The defect these cover: the UI and the live-call governor both read the model
from `providers.<name>.model` in configs/multimodal_providers.yaml, so every
operating mode resolved to the same static id (`openai/gpt-5-nano`) and the
mode-to-model table in configs/multimodal_models.yaml was never loaded.

No test here makes, or can make, a network call.
"""
from pathlib import Path

import pytest
import yaml
from PIL import Image

from app import multimodal_permission
from engine.escalation.client import load_config
from engine.escalation.contract import CropImage, MultimodalRequest
from engine.escalation.live_policy import LiveCallGovernor, LiveDecision
from engine.escalation.model_router import (DEFAULT_MODE, ModelResolutionError,
                                            ModelRouter, load_models_config)

REPO_MODELS = load_models_config()
# Through load_config so the fixture is the config the app actually runs on,
# including the attached operating-mode model table.
REPO_PROVIDERS = load_config()

# The model each mode is REQUIRED to select. Written as literals rather than
# read back from the config so an accidental edit to the config fails a test
# instead of silently redefining the expectation.
EXPECTED = {
    "economy": ("qwen_flash", "qwen/qwen3.7-flash"),
    "balanced": ("gemini_35_flash_lite", "google/gemini-3.5-flash-lite"),
    "accuracy": ("qwen_plus", "qwen/qwen3.7-plus"),
}


def _router(models=None, providers=None):
    return ModelRouter(models_config=models if models is not None else REPO_MODELS,
                       provider_config=providers if providers is not None else REPO_PROVIDERS)


# --------------------------------------------------------------- resolution

@pytest.mark.parametrize(("mode", "alias", "model_id"),
                         [(m, a, i) for m, (a, i) in EXPECTED.items()])
def test_each_mode_resolves_to_its_configured_model(mode, alias, model_id):
    resolved = _router().resolve(mode)

    assert resolved.mode == mode
    assert resolved.alias == alias
    assert resolved.model_id == model_id
    assert resolved.supports_images is True


def test_modes_resolve_to_three_distinct_models():
    """The bug's signature was one id for every mode."""
    ids = {_router().resolve(mode).model_id for mode in EXPECTED}

    assert len(ids) == 3
    assert "openai/gpt-5-nano" not in ids


def test_provider_static_model_does_not_override_the_selected_model():
    """A provider entry supplies transport, never the choice of model."""
    providers = {
        **REPO_PROVIDERS,
        "providers": {**REPO_PROVIDERS["providers"],
                      "openrouter": {**REPO_PROVIDERS["providers"]["openrouter"],
                                     "model": "openai/gpt-5-nano"}},
    }
    for mode, (_, model_id) in EXPECTED.items():
        assert _router(providers=providers).resolve(mode).model_id == model_id


def test_governor_model_follows_the_operating_mode():
    """LiveCallGovernor.model previously read the provider entry directly."""
    for mode, (_, model_id) in EXPECTED.items():
        governor = LiveCallGovernor(REPO_PROVIDERS, mode=mode)
        assert governor.model == model_id
        assert governor.resolved.alias == EXPECTED[mode][0]


def test_unknown_mode_falls_back_to_provider_model_and_says_so():
    resolved = _router().resolve("no-such-mode")

    assert resolved.model_id == "openai/gpt-5-nano"
    assert resolved.alias == ""
    assert "no operating-mode entry" in resolved.source


def test_mode_naming_an_undefined_alias_is_an_authoring_error():
    broken = {"models": {}, "operating_modes": {"economy": {"primary": "ghost"}}}

    with pytest.raises(ModelResolutionError, match="ghost"):
        _router(models=broken).resolve("economy")


# ---------------------------------------------------------------- capability

def test_unlisted_model_resolves_but_is_blocked():
    """Resolution names the model; the allowlist decides if it may be sent.

    RESOLUTION IS NOT AUTHORISATION. The three shipped modes are now all
    allowlisted, so this uses an id that is deliberately absent to keep testing
    the gate rather than the current contents of the allowlist.
    """
    models = {"models": {"unlisted": {"model_id": "qwen/qwen3.7-max",
                                      "supports_images": True}},
              "operating_modes": {"economy": {"primary": "unlisted"}}}
    resolved = _router(models=models).resolve("economy")

    assert resolved.model_id == "qwen/qwen3.7-max"
    assert resolved.allowlisted is False
    assert resolved.usable is False
    assert "not on live_provider.model_allowlist" in resolved.blocked_reason


def test_shipped_mode_models_resolve_as_usable():
    """The counterpart: verification moved these from blocked to usable."""
    for mode, (alias, model_id) in EXPECTED.items():
        resolved = _router().resolve(mode)
        assert resolved.alias == alias
        assert resolved.model_id == model_id
        assert resolved.allowlisted is True
        assert resolved.supports_images is True
        assert resolved.usable is True
        assert resolved.blocked_reason == ""


def test_allowlisted_vision_model_is_usable():
    models = {"models": {"ok": {"model_id": "openai/gpt-5-nano",
                                "supports_images": True}},
              "operating_modes": {"economy": {"primary": "ok"}}}
    resolved = _router(models=models).resolve("economy")

    assert resolved.allowlisted is True
    assert resolved.usable is True
    assert resolved.blocked_reason == ""


def test_model_without_image_support_is_rejected():
    models = {"models": {"textonly": {"model_id": "openai/gpt-5-nano",
                                      "supports_images": False}},
              "operating_modes": {"economy": {"primary": "textonly"}}}
    resolved = _router(models=models).resolve("economy")

    assert resolved.supports_images is False
    assert resolved.usable is False
    assert "supports_images" in resolved.blocked_reason


@pytest.mark.parametrize("model_id", ["openrouter/auto", "qwen/qwen3.7-flash:free"])
def test_refused_model_classes_are_rejected_by_identity(model_id):
    """Auto Router and :free outrank the allowlist and are refused regardless."""
    models = {"models": {"bad": {"model_id": model_id, "supports_images": True}},
              "operating_modes": {"economy": {"primary": "bad"}}}
    providers = {**REPO_PROVIDERS,
                 "live_provider": {**REPO_PROVIDERS["live_provider"],
                                   "model_allowlist": [{"id": model_id,
                                                        "vision": True}]}}
    resolved = _router(models=models, providers=providers).resolve("economy")

    assert resolved.usable is False
    assert resolved.blocked_reason


# ----------------------------------------------------------------- fallback

def test_no_fallback_occurs_when_fallbacks_are_disabled():
    """Balanced and Accuracy define a fallback; limits must still veto it."""
    assert REPO_PROVIDERS["live_provider"]["limits"]["allow_fallback_models"] is False
    router = _router()

    for mode in ("balanced", "accuracy"):
        resolved = router.resolve(mode)
        assert resolved.fallback_model_id            # a fallback IS configured
        assert resolved.fallback_allowed is False    # and is not permitted
        assert resolved.is_fallback is False
        assert resolved.model_id == EXPECTED[mode][1]


def test_fallback_requires_both_a_configured_model_and_permissive_limits():
    permissive = {**REPO_PROVIDERS,
                  "live_provider": {**REPO_PROVIDERS["live_provider"],
                                    "limits": {**REPO_PROVIDERS["live_provider"]["limits"],
                                               "allow_fallback_models": True}}}
    router = _router(providers=permissive)

    assert router.resolve("balanced").fallback_allowed is True
    # Economy has fallback: null, so permissive limits alone change nothing.
    assert router.resolve("economy").fallback_allowed is False


def test_balanced_fallback_resolves_to_its_configured_model():
    resolved = _router().resolve("balanced", use_fallback=True)

    assert resolved.is_fallback is True
    assert resolved.model_id == "qwen/qwen3.7-plus"


# ------------------------------------------------------------------ config

def test_shipped_config_has_no_provider_contradiction():
    """active_provider and live_provider.provider disagreed (openai/openrouter)."""
    assert REPO_PROVIDERS["active_provider"] == REPO_PROVIDERS["live_provider"]["provider"]


def test_paid_path_ships_disabled():
    assert REPO_PROVIDERS["enabled"] is False
    assert REPO_PROVIDERS["live_provider"]["enabled"] is False


def test_every_mode_model_declares_image_support():
    for spec in REPO_MODELS["models"].values():
        assert spec["supports_images"] is True


def test_models_file_carries_no_credential():
    assert "api_key" not in yaml.dump(REPO_MODELS).casefold()


# ------------------------------------------------------- governor + UI wiring

def _request(field_name="patient_name"):
    """A request that satisfies provenance and crop-fraction checks.

    Built through `from_pil` so the sha256 and png_bytes are genuine; a
    hand-written digest would not survive the governor's provenance check.
    """
    crop = Image.new("RGB", (80, 20), "white")
    return MultimodalRequest(
        field_name=field_name,
        crop=CropImage.from_pil(crop, source_page_px=(2550, 3300),
                                region_px=(80, 20)),
        doc_id="doc-1", page_id="p1", synthetic=True)


def _live_env(providers):
    key_env = providers["providers"]["openrouter"]["api_key_env"]
    return {"CLAIMROUTE_MULTIMODAL_ENABLED": "true",
            "CLAIMROUTE_LIVE_PROVIDER_TEST": "true",
            key_env: "synthetic-test-key"}


def test_governor_blocks_the_unlisted_mode_model_even_when_fully_switched_on():
    """Every other gate open; the model alone must still stop the call.

    The mode is pointed at an id that is absent from the allowlist, because the
    shipped mode models are now all approved. This is the gate that makes
    allowlisting a real authorisation step rather than a label.
    """
    providers = {**REPO_PROVIDERS, "enabled": True,
                 "live_provider": {**REPO_PROVIDERS["live_provider"], "enabled": True},
                 "operating_mode_models": {
                     "models": {"unlisted": {"model_id": "qwen/qwen3.7-max",
                                             "supports_images": True}},
                     "operating_modes": {"economy": {"primary": "unlisted"}}}}
    governor = LiveCallGovernor(providers, mode="economy",
                                env=_live_env(providers), adapter_enabled=True)

    outcome = governor.authorize(_request())

    assert outcome.model == "qwen/qwen3.7-max"
    assert outcome.decision is LiveDecision.BLOCKED_MODEL_NOT_ALLOWLISTED
    assert outcome.allowed is False
    assert outcome.route_to_human_review is True


def test_disabled_configuration_blocks_calls_for_every_mode():
    for mode in EXPECTED:
        governor = LiveCallGovernor(REPO_PROVIDERS, mode=mode,
                                    env=_live_env(REPO_PROVIDERS),
                                    adapter_enabled=True)
        outcome = governor.authorize(_request())

        assert outcome.decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED
        assert outcome.allowed is False


def test_openrouter_receives_the_resolved_model_id():
    """The id built into the outbound payload is the mode's, not the provider's."""
    sent = {}

    def _builder(name, spec):
        sent["model"] = spec["model"]

        class _P:
            """Records the model it was handed and refuses to transport."""
            model = spec["model"]

            def __init__(self):
                self.name = name

            def invoke(self, *_a, **_k):
                raise AssertionError("no transport may occur in tests")
        return _P()

    providers = {**REPO_PROVIDERS, "enabled": True,
                 "live_provider": {
                     **REPO_PROVIDERS["live_provider"], "enabled": True,
                     "model_allowlist": [{"id": "qwen/qwen3.7-flash", "vision": True}]}}
    governor = LiveCallGovernor(providers, mode="economy",
                                env=_live_env(providers), adapter_enabled=True)

    receipt, _ = multimodal_permission.run_one_candidate(
        _request(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=providers, calls_used=0,
        provider_builder=_builder)

    # The provider entry still says openai/gpt-5-nano; the mode's model wins.
    assert providers["providers"]["openrouter"]["model"] == "openai/gpt-5-nano"
    assert sent["model"] == "qwen/qwen3.7-flash"
    assert receipt["requested_model"] == "qwen/qwen3.7-flash"


def test_ui_panel_displays_the_runtime_resolved_model(monkeypatch):
    """The Streamlit panel must render the resolved id, not the static one."""
    from app import workspace

    for mode, (alias, model_id) in EXPECTED.items():
        snapshot = workspace._provider_policy_snapshot(REPO_PROVIDERS, env={},
                                                       mode=mode)
        assert snapshot["configured_model"] == model_id
        assert snapshot["model_alias"] == alias
        assert snapshot["operating_mode"] == mode
        # Verified and approved on 2026-08-02; the panel must say so, while
        # `reason_not_attempted` still shows the call is refused by policy.
        assert snapshot["model_allowlisted"] is True
        assert snapshot["model_supports_images"] is True
        # Shipped config is disabled, and policy outranks model status: an
        # operator must not be told "fix the allowlist" when the real blocker
        # is that the paid path is off.
        assert snapshot["reason_not_attempted"] == "disabled by policy"


def test_allowlist_reason_surfaces_once_policy_stops_blocking():
    """With policy enabled, a non-allowlisted model's own blocker is shown.

    The three shipped modes are now all allowlisted, so this drops the allowlist
    to gpt-5-nano only to recreate the condition. Asserting on a mode that IS
    allowlisted would test nothing.
    """
    from app import workspace

    live = {**REPO_PROVIDERS["live_provider"], "enabled": True,
            "model_allowlist": [{"id": "openai/gpt-5-nano", "vision": True,
                                 "price_row": "gpt-5-nano"}]}
    enabled = {**REPO_PROVIDERS, "enabled": True, "live_provider": live}
    snapshot = workspace._provider_policy_snapshot(enabled, env={}, mode="balanced")

    assert snapshot["configured_model"] == "google/gemini-3.5-flash-lite"
    assert snapshot["model_allowlisted"] is False
    assert "allowlist" in snapshot["reason_not_attempted"]


def test_shipped_modes_are_allowlisted_and_declare_vision():
    """Each shipped mode is billable-ready: allowlisted, vision, priced.

    This is the check that would have caught google/gemini-2.5-flash-lite, an
    id that resolved cleanly but does not exist on OpenRouter.
    """
    from engine.vision.base import price_call

    allowlist = {entry["id"]: entry
                 for entry in REPO_PROVIDERS["live_provider"]["model_allowlist"]}
    for mode, (_, model_id) in EXPECTED.items():
        assert model_id in allowlist, f"{mode} model {model_id} is not allowlisted"
        assert allowlist[model_id]["vision"] is True
        # A price row must exist, or cost degrades to basis="unknown".
        price_call(allowlist[model_id]["price_row"], 1000, 200)


def test_default_mode_matches_the_service_layer():
    from app import service

    assert DEFAULT_MODE == service.DEFAULT_MODE


def test_live_prices_do_not_live_in_the_frozen_price_file():
    """Live-provider rows must stay OUT of the frozen benchmark price table.

    configs/prices.yaml is hashed into the candidate freeze manifest
    (eval/official/freeze_readiness.py:FREEZE_FILES). A vendor price change
    written there would move a benchmark evidence hash, so live rows belong in
    the non-frozen overlay instead.
    """
    from eval.official.freeze_readiness import FREEZE_FILES

    frozen = yaml.safe_load(Path("configs/prices.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load(
        Path("configs/live_provider_prices.yaml").read_text(encoding="utf-8"))

    assert "configs/prices.yaml" in FREEZE_FILES
    assert "configs/live_provider_prices.yaml" not in FREEZE_FILES
    # Every live row is namespaced and absent from the frozen table, so the
    # overlay adds models rather than silently repricing a benchmarked one.
    for row in overlay["vision_models"]:
        assert row.startswith("openrouter_")
        assert row not in frozen["vision_models"]


def test_price_overlay_does_not_shadow_frozen_rows():
    """Frozen benchmark prices survive the overlay merge unchanged."""
    from engine.vision.base import _load_prices

    frozen = yaml.safe_load(Path("configs/prices.yaml").read_text(encoding="utf-8"))
    merged = _load_prices()

    for row, value in frozen["vision_models"].items():
        assert merged["vision_models"][row] == value
    assert merged["compute"] == frozen["compute"]
    assert merged["human_review"] == frozen["human_review"]
