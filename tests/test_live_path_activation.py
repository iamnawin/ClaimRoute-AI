"""The one controlled activation path for approved synthetic field crops.

THE DEFECT THESE COVER. Every gate on the paid path had an operator-reachable
route to "on" except one. `live_provider.enabled` was read straight out of
configs/multimodal_providers.yaml with no environment override anywhere in the
codebase, so the only way to run a single approved synthetic crop end to end was
to edit a tracked file — and a tracked file that says `true` travels with the
clone, to every machine, for every document. The safe act (one session) and the
dangerous act (a committed default) were the same edit.

`CLAIMROUTE_LIVE_PROVIDER_CONFIG_ENABLED` closes that gap in the direction the
repository already documents everywhere else:

    secure environment override  ->  application configuration  ->  safe default

The environment may OPEN a gate the tracked file leaves closed, so a session can
be authorised without a commit. It may also CLOSE one the file opened, so a
machine can refuse regardless of what arrives in a checkout. A shipped file can
never open a gate the environment closed, because the file travels and the
environment does not.

WIDENING THE SWITCH DOES NOT WIDEN WHAT MAY BE SENT. The override replaces one
boolean and nothing else. Synthetic attestation, proven crop provenance, the
model allowlist, both budgets, duplicate protection and explicit UI consent are
untouched and are asserted here to still refuse — an activation path that also
relaxed the input policy would be a data-exfiltration path with a friendly name.

No test in this file can make a network call. Every provider is a local double.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app import multimodal_permission, service, streamlit_app, workspace
from app.intake import inspect_content
from engine.escalation.client import load_config, request_from_page
from engine.escalation.contract import (CostBreakdown, MultimodalResult,
                                        ParsedAnswer, UsageMetadata)
from engine.escalation.live_policy import (LIVE_CONFIG_ENABLED_ENV,
                                           ConfigurationFlagError,
                                           LiveCallGovernor, LiveDecision,
                                           parse_optional_flag)
from engine.escalation.readiness import ReadinessState, evaluate_readiness
from engine.schemas import Attempt, FieldResult, FieldState, PageResult

KEY = "OPENROUTER_API_KEY"
ENABLE = "CLAIMROUTE_MULTIMODAL_ENABLED"
LIVE_TEST = "CLAIMROUTE_LIVE_PROVIDER_TEST"

# Never a realistic key shape. A fixture that looks like a credential invites
# someone to paste a real one in beside it.
FAKE_KEY = "test-key-not-a-credential"

# Every environment gate satisfied, but the tracked config still says the live
# path is closed. This is the state a correctly-configured operator reaches on a
# fresh clone, and it must still refuse.
ENV_READY = {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true"}

# The same, plus the one documented activation override.
ENV_ACTIVATED = {**ENV_READY, LIVE_CONFIG_ENABLED_ENV: "true"}

REPO_CONFIG = load_config()


def _governor(env, *, config=None, mode="balanced") -> LiveCallGovernor:
    return LiveCallGovernor(config if config is not None else REPO_CONFIG,
                            env=dict(env), mode=mode)


def _synthetic_crop(*, synthetic: bool = True, field_name="billing_provider_npi",
                    doc_id="synthetic-doc"):
    """A bounded field crop of a page generated in this process.

    Nothing is read from disk. There is no organiser document, no local claim,
    and no PHI anywhere in this fixture — only an image created here.
    """
    page = Image.new("RGB", (1200, 1600), "white")
    return request_from_page(page, (100, 200, 340, 244), field_name,
                             doc_id=doc_id, page_id="p1", synthetic=synthetic)


def _full_page_request():
    """A full page, built by bypassing the cropper on purpose.

    engine/cropper.py refuses to produce this at all, which is the structural
    boundary. Constructing one by hand proves the governor refuses it a SECOND
    time, independently — a single boundary is a single edit away from gone.
    """
    from engine.escalation.client import build_request

    page = Image.new("RGB", (1200, 1600), "white")
    return build_request(page, "billing_provider_npi",
                         source_page_px=(1200, 1600), region_px=(1200, 1600),
                         doc_id="synthetic-doc", page_id="p1", synthetic=True)


def _unprovable_request():
    """An image with no recorded source-page size.

    This is the shape an arbitrary local file or an organiser document takes
    when someone hands it straight to the adapter: there is no page geometry to
    check it against, so it cannot be PROVEN to be a field crop.
    """
    from engine.escalation.client import build_request

    page = Image.new("RGB", (240, 44), "white")
    return build_request(page, "billing_provider_npi", doc_id="organiser-doc",
                         page_id="p1", synthetic=True)


def _fake_result(request_id: str, value: str | None = "1234567893"):
    return MultimodalResult(
        request_id=request_id, provider="openrouter",
        model="google/gemini-3.5-flash-lite",
        actual_model="google/gemini-3.5-flash-lite",
        field_name="billing_provider_npi",
        answer=ParsedAnswer(value, value is not None, .99),
        usage=UsageMetadata(input_tokens=120, output_tokens=8),
        cost=CostBreakdown(basis="provider_reported", reported_usd=.000004),
        latency_ms=11.0, attempts=1, called_provider=True,
        raw_sha256="safe-hash")


class _FakeClient:
    """Stands in for MultimodalClient. Records calls; opens no socket."""

    def __init__(self, value: str | None = "1234567893", **kwargs):
        self.value = value
        self.seen: list[str] = []

    def __call__(self, **kwargs):
        return self

    def read_field(self, request):
        self.seen.append(request.request_id)
        return _fake_result(request.request_id, self.value)


# ------------------------------------------------------- the override itself


@pytest.mark.parametrize("raw", ["true", "TRUE", "  True ", "1", "yes", "on"])
def test_documented_truthy_values_open_the_live_path(raw):
    assert parse_optional_flag(LIVE_CONFIG_ENABLED_ENV, raw) is True


@pytest.mark.parametrize("raw", ["false", "FALSE", " 0 ", "no", "off"])
def test_documented_falsy_values_close_the_live_path(raw):
    assert parse_optional_flag(LIVE_CONFIG_ENABLED_ENV, raw) is False


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_is_neither_open_nor_closed_but_defers_to_configuration(raw):
    """The tri-state is the whole point. Reading "unset" as False would make the
    override unable to express "leave the tracked file in charge", and reading it
    as True would open the path on every machine that never set it."""
    assert parse_optional_flag(LIVE_CONFIG_ENABLED_ENV, raw) is None


@pytest.mark.parametrize("raw", ["maybe", "TRUE-ish", "2", "y", "enabled"])
def test_a_malformed_override_is_an_error_not_a_silent_false(raw):
    with pytest.raises(ConfigurationFlagError) as excinfo:
        parse_optional_flag(LIVE_CONFIG_ENABLED_ENV, raw)

    assert LIVE_CONFIG_ENABLED_ENV in str(excinfo.value)


# ------------------------------------------------------------ 1. config gate


def test_shipped_configuration_alone_blocks_the_live_path():
    """Item 1. A fresh clone with every environment gate satisfied still refuses,
    and names the configuration as the reason rather than a budget or a model."""
    outcome = _governor(ENV_READY).preview_authorization(_synthetic_crop())

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED
    assert REPO_CONFIG["live_provider"]["enabled"] is False


def test_the_override_opens_the_live_path_without_editing_tracked_config():
    """Item 3, the gate this whole task turns on. Nothing on disk changes."""
    governor = _governor(ENV_ACTIVATED)

    assert governor.live_path_enabled is True
    assert governor.preview_authorization(_synthetic_crop()).allowed is True
    # The committed default is still false. If this ever fails, the override
    # stopped being an override and became a commit.
    assert load_config()["live_provider"]["enabled"] is False


def test_an_explicit_false_override_closes_a_config_the_file_opened():
    """Precedence runs one way only. A checkout that arrives with the live path
    enabled must still be refusable by the machine it lands on, or the safety
    property depends on what someone else committed."""
    config = {**REPO_CONFIG,
              "live_provider": {**REPO_CONFIG["live_provider"], "enabled": True}}
    env = {**ENV_READY, LIVE_CONFIG_ENABLED_ENV: "false"}

    governor = _governor(env, config=config)

    assert governor.live_path_enabled is False
    assert (governor.preview_authorization(_synthetic_crop()).decision
            is LiveDecision.BLOCKED_LIVE_PATH_DISABLED)


def test_a_malformed_override_refuses_the_call_as_a_typed_outcome():
    """The governor's contract is that every refusal is a typed outcome, never
    an exception. A malformed flag must not become the one path that raises
    through the UI, and must not be read as "on" either."""
    env = {**ENV_READY, LIVE_CONFIG_ENABLED_ENV: "yeah-sure"}

    outcome = _governor(env).preview_authorization(_synthetic_crop())

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_LIVE_PATH_DISABLED
    assert LIVE_CONFIG_ENABLED_ENV in outcome.reason


# ------------------------------------------------- 2. environment gate states


@pytest.mark.parametrize("missing,expected", [
    (KEY, LiveDecision.BLOCKED_NO_API_KEY),
    (ENABLE, LiveDecision.BLOCKED_ADAPTER_DISABLED),
    (LIVE_TEST, LiveDecision.BLOCKED_LIVE_TEST_FLAG_UNSET),
])
def test_the_override_does_not_substitute_for_any_other_environment_gate(
        missing, expected):
    """Item 2. The override replaces ONE boolean. Every other requirement stands,
    and each names itself, so an operator is told the next thing to fix."""
    env = {k: v for k, v in ENV_ACTIVATED.items() if k != missing}

    outcome = _governor(env).preview_authorization(_synthetic_crop())

    assert outcome.allowed is False
    assert outcome.decision is expected


# ------------------------------------------------------ 4-6. input eligibility


def test_an_activated_path_still_refuses_a_non_synthetic_document():
    """Items 4 and 5. An arbitrary local claim and an organiser document reach
    the governor as "not attested synthetic". Opening the switch must not open
    this: the two were never the same decision."""
    outcome = _governor(ENV_ACTIVATED).preview_authorization(
        _synthetic_crop(synthetic=False))

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_NOT_SYNTHETIC


def test_an_activated_path_still_refuses_an_image_of_unprovable_provenance():
    """Item 5. An organiser document handed straight to the adapter has no page
    geometry, so "it is only a small crop" is an assertion nobody can check.
    Unverifiable provenance is refused rather than assumed safe."""
    outcome = _governor(ENV_ACTIVATED).preview_authorization(_unprovable_request())

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_NOT_A_CROP
    assert "provenance" in outcome.reason or "proven" in outcome.reason


def test_an_activated_path_still_refuses_a_full_page_twice():
    """Item 6, at both boundaries. The cropper will not build one; the governor
    refuses it anyway. Defence in depth here is not ceremony — a full page is
    the difference between one form box and a patient's entire record."""
    from engine.cropper import CropPolicyError

    page = Image.new("RGB", (1200, 1600), "white")
    with pytest.raises(CropPolicyError):
        request_from_page(page, (0, 0, 1200, 1600), "billing_provider_npi",
                          doc_id="synthetic-doc", page_id="p1", synthetic=True)

    outcome = _governor(ENV_ACTIVATED).preview_authorization(_full_page_request())

    assert outcome.allowed is False
    assert outcome.decision is LiveDecision.BLOCKED_NOT_A_CROP
    assert "full pages are never sent" in outcome.reason


# --------------------------------------------------------- 7-10. execution


def test_an_approved_synthetic_crop_runs_end_to_end_against_a_fake_provider():
    """Item 7 and item 9. The activated path is not a status message: the crop
    goes to the adapter, the answer re-enters validation, and an accepted value
    comes back for the field."""
    governor = _governor(ENV_ACTIVATED)
    client = _FakeClient()

    receipt, value = multimodal_permission.run_one_candidate(
        _synthetic_crop(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0,
        provider_builder=lambda *args: _StubProvider(governor.model),
        client_factory=client)

    assert receipt["external_calls_made"] == 1
    assert receipt["policy_decision"] == "ALLOW"
    assert receipt["healthcare_validators_passed"] is True
    assert receipt["final_field_outcome"] == "ACCEPTED"
    assert value == "1234567893"
    assert len(client.seen) == 1


def test_a_provider_answer_that_fails_validation_leaves_the_field_unresolved():
    """Item 10. A paid call is not an answer. An NPI whose checksum fails is
    still wrong, and the money is still spent — reporting it as resolved would
    make the spend look like accuracy."""
    governor = _governor(ENV_ACTIVATED)
    client = _FakeClient(value="0000000000")

    receipt, value = multimodal_permission.run_one_candidate(
        _synthetic_crop(), enabled=True, confirmed=True, synthetic_attested=True,
        governor=governor, config=REPO_CONFIG, calls_used=0,
        provider_builder=lambda *args: _StubProvider(governor.model),
        client_factory=client)

    assert receipt["external_calls_made"] == 1
    assert receipt["healthcare_validators_passed"] is False
    assert receipt["final_field_outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert value is None


def test_a_repeated_request_never_pays_twice():
    """Item 13, at the policy layer. A Streamlit rerun re-executes the whole
    script, so the same crop arrives again with no user action at all."""
    governor = _governor(ENV_ACTIVATED)
    client = _FakeClient()
    request = _synthetic_crop()
    run = dict(enabled=True, confirmed=True, synthetic_attested=True,
               governor=governor, config=REPO_CONFIG,
               provider_builder=lambda *args: _StubProvider(governor.model),
               client_factory=client)

    first, _ = multimodal_permission.run_one_candidate(
        request, calls_used=0, **run)
    second, repeated = multimodal_permission.run_one_candidate(
        request, calls_used=1, **run)

    assert first["external_calls_made"] == 1
    assert second["external_calls_made"] == 0
    assert repeated is None
    assert governor.calls_made == 1
    assert len(client.seen) == 1


class _StubProvider:
    """Satisfies the model-identity check in run_one_candidate. Never invoked."""

    def __init__(self, model: str):
        self.model = model


# ------------------------------------------------- 11-12. document and exports


def _synthetic_document_state():
    """One synthetic PNG producing one unresolved critical field with a bbox.

    Generated in this process. It is not a claim, not an organiser file, and not
    read from the dataset directory.
    """
    stream = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(stream, format="PNG")
    item = inspect_content("synthetic.png", stream.getvalue())
    page = PageResult(item.safe_source_id, "p1", "cms1500", quality_score=.9)
    field = FieldResult(item.safe_source_id, "p1", "billing_provider_npi", None,
                        FieldState.ESCALATE, .2, bbox=(30, 30, 100, 55))
    field.attempts = [Attempt("primary_ocr", "stub", None, .2)]
    page.fields = {field.field_name: field}
    page.decisions = {field.field_name: [("ESCALATE", "synthetic unresolved")]}
    batch = workspace.run_batch(
        [item], processor=lambda *_: workspace.process_item(
            item, page_processor=lambda *_: service.build_receipt(
                page, [], "balanced", 10, source_kind="local_workspace")))
    return item, batch["documents"][0]


def test_the_governor_marks_the_synthetic_field_escalate_and_offers_a_crop():
    """Phase 4, items 1 and 2. Before anything can be sent there has to be a
    field asking to be sent, and a bbox to cut it from."""
    _, document = _synthetic_document_state()

    queue = streamlit_app._eligible_multimodal_fields(document)

    assert queue, "the synthetic fixture produced no eligible unresolved field"
    row = queue[0]
    assert row["field_name"] == "billing_provider_npi"
    assert row["bbox"]


def test_an_accepted_candidate_updates_the_field_and_the_exports():
    """Items 11 and 12. The run has to change the document, not just the log.

    Asserted through the export surfaces because those are what a judge reads:
    a value that never reaches the JSON and the CSV did not really land.
    """
    import json

    _, document = _synthetic_document_state()
    before = json.loads(workspace.export_document_json(document))
    before_unresolved = len(workspace.build_review_queue(document))

    updated = workspace.apply_multimodal_candidate(
        document, page=1, field_name="billing_provider_npi",
        value="1234567893",
        receipt={"final_field_outcome": "ACCEPTED", "measured_cost_usd": .000004,
                 "external_calls_made": 1, "latency_ms": 11.0})

    after = json.loads(workspace.export_document_json(updated))
    csv_text = workspace.export_document_csv(updated)

    assert before != after
    assert len(workspace.build_review_queue(updated)) == before_unresolved - 1
    assert "1234567893" in csv_text


def test_a_rejected_candidate_keeps_the_field_in_human_review():
    """The counterpart. A failed candidate must not silently shrink the review
    queue — that is how a spend gets reported as a resolution."""
    _, document = _synthetic_document_state()
    before_unresolved = len(workspace.build_review_queue(document))

    updated = workspace.apply_multimodal_candidate(
        document, page=1, field_name="billing_provider_npi", value=None,
        receipt={"final_field_outcome": "HUMAN_REVIEW_REQUIRED",
                 "measured_cost_usd": .000004, "external_calls_made": 1,
                 "latency_ms": 11.0})

    assert len(workspace.build_review_queue(updated)) == before_unresolved


# ------------------------------------------------------ 14-15. display truth


def test_the_latency_warning_does_not_change_provider_readiness():
    """Item 14. `Runtime accept threshold` is a CONFIDENCE threshold from
    configs/operating_modes.yaml, not a timer. Local processing being slow has
    never been a reason to send a field to a paid provider, and must never read
    as one — the two numbers share a screen, not a meaning.
    """
    fast = workspace.mode_policy("balanced")["accept_threshold"]
    strict = workspace.mode_policy("accuracy")["accept_threshold"]
    assert fast != strict

    for mode in ("economy", "balanced", "accuracy"):
        readiness = evaluate_readiness(config=REPO_CONFIG, env=ENV_ACTIVATED,
                                       mode=mode, request=_synthetic_crop())
        assert readiness.state is ReadinessState.READY
        assert readiness.live_path_enabled is True


def test_only_mode_eligible_fields_are_offered_to_the_provider():
    """Item 15. Economy escalates high-criticality fields only. A mode that
    silently widened what it sends would spend money the operator declined."""
    economy = workspace.mode_policy("economy")
    accuracy = workspace.mode_policy("accuracy")

    assert workspace._multimodal_eligible("billing_provider_npi", economy) is True
    assert economy["paid_escalation_criticalities"] == ["high"]
    assert set(accuracy["paid_escalation_criticalities"]) >= {"high", "med"}


# ------------------------------------------------------ separated status panel


def test_readiness_reports_the_live_path_as_its_own_dimension():
    """Phase 3. "External enabled: Yes/No" collapsed six independent facts into
    one boolean, and the one it silently dropped was the only gate still shut.
    An operator with every switch correct saw a panel that agreed with them and
    a call that refused anyway."""
    blocked = evaluate_readiness(config=REPO_CONFIG, env=ENV_READY,
                                 mode="balanced", request=_synthetic_crop())

    # READY is display state and keeps its meaning: nothing in the OPERATOR's
    # setup is missing. The live path is a separate fact, reported separately.
    assert blocked.state is ReadinessState.READY
    assert blocked.key_present is True
    assert blocked.adapter_flag is True
    assert blocked.live_test_flag is True
    assert blocked.input_eligible is True
    assert blocked.live_path_enabled is False
    assert blocked.paid_execution_authorized is False
    assert blocked.blocking_reason == LiveDecision.BLOCKED_LIVE_PATH_DISABLED.value


def test_readiness_reports_paid_execution_authorized_once_everything_is_open():
    activated = evaluate_readiness(config=REPO_CONFIG, env=ENV_ACTIVATED,
                                   mode="balanced", request=_synthetic_crop())

    assert activated.live_path_enabled is True
    assert activated.paid_execution_authorized is True
    assert activated.blocking_reason == ""


def test_an_ineligible_input_is_not_reported_as_authorized():
    """Authorisation is per input, not per session. A ready provider plus a page
    is still a refusal, and the panel must say which of the two is wrong."""
    activated = evaluate_readiness(config=REPO_CONFIG, env=ENV_ACTIVATED,
                                   mode="balanced", request=_full_page_request())

    assert activated.live_path_enabled is True
    assert activated.paid_execution_authorized is False
    assert activated.state is ReadinessState.INPUT_INELIGIBLE


def test_the_diagnostics_expose_the_live_path_and_never_the_key():
    readiness = evaluate_readiness(config=REPO_CONFIG, env=ENV_ACTIVATED,
                                   mode="balanced", request=_synthetic_crop())
    diagnostics = readiness.diagnostics()

    assert diagnostics["CONFIG_LIVE_PATH_ENABLED"] is True
    assert diagnostics["PAID_EXECUTION_AUTHORIZED"] is True
    assert FAKE_KEY not in repr(diagnostics)


# ---------------------------------------------------------- the UI checklist


def test_the_ui_checklist_follows_the_same_activation_contract():
    """The checklist read raw YAML, so it reported "provider configuration
    disabled" for a session the governor would have authorised — and the toggle
    it guards was never drawn. One contract, consulted in both places."""
    blocked = multimodal_permission.enablement_blockers(
        governor=_governor(ENV_READY), config=REPO_CONFIG,
        synthetic_attested=True, request=_synthetic_crop(), candidates=1)
    activated = multimodal_permission.enablement_blockers(
        governor=_governor(ENV_ACTIVATED), config=REPO_CONFIG,
        synthetic_attested=True, request=_synthetic_crop(), candidates=1)

    assert [row.key for row in multimodal_permission.unmet(blocked)] == [
        "provider_configuration"]
    assert multimodal_permission.unmet(activated) == []


# ------------------------------------------------------------ rendered panel


def _run_app(monkeypatch, env: dict):
    """Render the workspace Results tab under a given environment."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    for name in (KEY, ENABLE, LIVE_TEST, LIVE_CONFIG_ENABLED_ENV):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    _, document = _synthetic_document_state()
    item = inspect_content("synthetic.png", _synthetic_png())
    state = streamlit_app._new_workspace_state({})
    state["inventory"] = [item]
    state["selected_document_ids"] = [item.safe_source_id]
    streamlit_app._store_workspace_batch(
        state, {"documents": [document], **_batch_shell(document)})
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.session_state[streamlit_app.WORKSPACE_STATE_KEY] = state
    app.session_state["cr_workspace_tabs"] = "Results"
    app.run(timeout=30)
    return app


def _synthetic_png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(stream, format="PNG")
    return stream.getvalue()


def _batch_shell(document: dict) -> dict:
    return {k: v for k, v in workspace.run_batch(
        [], processor=lambda *_: None).items() if k != "documents"}


def test_the_blocked_panel_shows_every_dimension_not_one_boolean(monkeypatch):
    """Phase 9 items 1-4 and 8, rendered. The operator must be able to read
    which single gate is shut without exporting anything to find out."""
    app = _run_app(monkeypatch, {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true"})

    labels = {row["label"]: row["value"]
              for frame in app.dataframe for row in _rows(frame)
              if isinstance(row, dict) and "label" in row}

    assert labels.get("Provider credentials") == "Available"
    assert labels.get("Adapter enabled") == "Yes"
    assert labels.get("Live-test permission") == "Yes"
    assert labels.get("Configuration live path") == "Disabled"
    assert labels.get("Paid execution authorized") == "No"
    assert labels.get("Blocking reason") == "BLOCKED_LIVE_PATH_DISABLED"
    # And still no consent control, because execution is still impossible.
    assert not [row for row in app.toggle
                if row.label == "Enable paid multimodal AI calls"]


def test_the_override_makes_the_consent_control_reachable(monkeypatch):
    """Phase 9 items 5 and 7. The end of the blocker: with the documented
    override set, the panel offers consent instead of a list of refusals. The
    toggle still defaults to OFF, and no call happens by rendering."""
    app = _run_app(monkeypatch, {KEY: FAKE_KEY, ENABLE: "true", LIVE_TEST: "true",
                                 LIVE_CONFIG_ENABLED_ENV: "true"})

    toggle = next((row for row in app.toggle
                   if row.label == "Enable paid multimodal AI calls"), None)
    assert toggle is not None, "activation did not make the consent control reachable"
    assert toggle.value is False
    assert not [row for row in app.button
                if row.label == "Enablement requirements not satisfied"]


def test_the_latency_caption_is_separate_from_the_provider_caption(monkeypatch):
    """Phase 6, rendered. The confidence threshold and the provider state must
    not share a sentence: read together they were reported as one verdict, and
    a slow document was taken to mean the provider had switched itself off."""
    monkeypatch.setenv("CLAIMROUTE_APP_MODE", "local_workspace")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("app/streamlit_app.py", default_timeout=30)
    app.run(timeout=30)
    captions = [row.value for row in app.caption]

    threshold = next(row for row in captions if "accept threshold" in row)
    provider = next(row for row in captions if "configuration live path" in row)

    assert threshold is not provider
    assert "confidence, not latency" in threshold
    assert "External calls enabled" not in " ".join(captions)


def _rows(frame):
    """Streamlit renders a list-of-dicts dataframe; read it back either way."""
    data = frame.value
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    return data or []
