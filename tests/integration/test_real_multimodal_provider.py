"""OPT-IN real-provider smoke test — makes ONE billable API call when enabled.

SKIPPED BY DEFAULT. It runs only when BOTH are true:

    CLAIMROUTE_REAL_PROVIDER_SMOKE=1
    OPENAI_API_KEY=<a real key>

so a normal `pytest tests/` run never reaches the network and never spends money.

DATA BOUNDARY: the crop is rendered here, in this process, from the synthetic
data factory with a seed used nowhere else. It is not read from data/generated,
not from the organiser sample, and not from the development or holdout splits.
Nothing real, and nothing that could be PHI, is ever sent.

WHAT IT PROVES: that the live transport, authentication, response schema, usage
reporting and cost path actually work against the provider. It asserts on SHAPE
only — never on the transcribed value, because a smoke test that asserts a model
read a specific string is an accuracy claim, and one call is not evidence of
accuracy.
"""
from __future__ import annotations

import json
import os

import pytest

from data_factory.generator import generate_claim
from data_factory.render_cms1500 import render
from engine.escalation.client import MultimodalClient, load_config, request_from_page
from engine.escalation.errors import ErrorCategory

SMOKE_ENV = "CLAIMROUTE_REAL_PROVIDER_SMOKE"
# Seed reserved for this test so the crop is freshly generated and shared with no
# dataset, split, or committed artifact.
SMOKE_SEED = 90210
SMOKE_FIELD = "billing_provider_npi"

_enabled = os.environ.get(SMOKE_ENV, "").strip() in {"1", "true", "yes", "on"}
_key = bool(os.environ.get("OPENAI_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (_enabled and _key),
    reason=f"real-provider smoke test is opt-in: set {SMOKE_ENV}=1 and OPENAI_API_KEY",
)


@pytest.fixture(scope="module")
def synthetic_crop_request():
    """A newly rendered synthetic CMS-1500 field crop. Zero PHI by construction."""
    claim = generate_claim(SMOKE_SEED)
    page, bboxes = render(claim)
    assert SMOKE_FIELD in bboxes, "synthetic renderer did not emit the smoke field"
    return request_from_page(page, bboxes[SMOKE_FIELD], SMOKE_FIELD,
                             doc_id=f"smoke_{SMOKE_SEED}", page_id="p1",
                             synthetic=True)


def test_real_provider_round_trip(synthetic_crop_request):
    """One live call through the full adapter. Enabled explicitly, never by config."""
    client = MultimodalClient(config=load_config(), enabled=True)
    result = client.read_field(synthetic_crop_request)

    if result.error in {ErrorCategory.RATE_LIMIT.value,
                        ErrorCategory.PROVIDER_5XX.value,
                        ErrorCategory.NETWORK_ERROR.value,
                        ErrorCategory.TIMEOUT.value}:
        pytest.skip(f"provider unavailable: {result.error} ({result.error_detail})")

    assert result.error is None, f"{result.error}: {result.error_detail}"
    assert result.called_provider is True
    assert 1 <= result.attempts <= 3
    assert result.latency_ms > 0 and result.provider_latency_ms

    # The raw body was hashed and dropped.
    assert len(result.raw_sha256) == 64
    assert not hasattr(result, "raw")

    # Shape only. A rejected answer is a legitimate outcome for a smoke test:
    # it proves the grounding path runs against a real response.
    if result.rejects:
        pytest.skip(f"live answer rejected by grounding: {result.rejects}")

    assert result.answer is not None
    assert isinstance(result.answer.visible, bool)
    assert 0.0 <= result.answer.confidence <= 1.0

    # Cost must be measured from reported usage, or explicitly flagged otherwise.
    assert result.cost.basis in {"measured_usage", "estimated_usage", "unknown"}
    if result.usage.billable_known:
        assert result.cost.basis == "measured_usage"
        assert result.cost.measured_usd is not None and result.cost.measured_usd > 0

    # The audit record is safe to persist: no transcribed value anywhere in it.
    serialised = json.dumps(result.audit)
    if result.answer.value:
        assert result.answer.value not in serialised


def test_real_provider_is_still_disabled_without_an_explicit_opt_in(
        synthetic_crop_request):
    """Even with a valid key present, shipped config must not permit a call."""
    client = MultimodalClient(config=load_config(), env={})
    result = client.read_field(synthetic_crop_request)

    assert client.enabled is False
    assert result.error == ErrorCategory.CONFIGURATION_ERROR.value
    assert result.called_provider is False
