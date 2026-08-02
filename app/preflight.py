"""Everything that must be true BEFORE one paid synthetic call, reported safely.

A paid call that fails tells you almost nothing: the money is gone and the
message is whatever the provider felt like returning. This module answers the
answerable questions first, cheaply, and names exactly which one is wrong.

Four reports, in the order an operator needs them:

    environment_report()   which switches this process actually sees
    provider_report()      which endpoint, model and budgets are actually loaded
    dry_run_receipt()      what a specific call WOULD send, and whether it may
    check_credentials()    whether the credential works, without sending a crop

NOTHING HERE IS AUTHORISATION. ``LiveCallGovernor`` remains the only authority
and re-runs every check immediately before transport. These reports exist so a
human can see why, not so anything can proceed.

SAFETY, uniformly: no function here returns, logs, or renders the API key, its
length, its prefix, or a hash of it. Presence is a boolean. Crop bytes, prompts,
extracted values and raw provider bodies never appear either — a dry-run receipt
is designed to be screenshotted into a chat window.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from engine.escalation.errors import ErrorCategory, MultimodalError, explain
from engine.escalation.live_policy import (DEFAULT_KEY_ENV,
                                           LIVE_CONFIG_ENABLED_ENV,
                                           LIVE_TEST_ENV,
                                           MULTIMODAL_ENABLED_ENV,
                                           ConfigurationFlagError,
                                           LiveCallGovernor, fingerprint,
                                           parse_optional_flag)

APP_MODE_ENV = "CLAIMROUTE_APP_MODE"

# Values that are obviously not a credential. Someone pasting the instructions
# instead of the key is a real thing, and the resulting 401 is indistinguishable
# from a revoked key unless it is caught here.
_PLACEHOLDERS = frozenset({
    "your_correct_key", "your_api_key", "your-api-key", "yourkeyhere",
    "sk-xxx", "changeme", "replace_me", "todo", "none", "null",
    "openrouter_api_key", "<your key>", "xxx",
})

# OpenRouter's credential introspection endpoint. It returns the key's own
# metadata and BILLS NOTHING, which is the entire reason it is used here: a
# connectivity check that costs money is not a check anyone will run twice.
CREDENTIAL_ENDPOINT = "https://openrouter.ai/api/v1/key"


# ------------------------------------------------------------- environment

def environment_report(env: Optional[dict] = None) -> dict:
    """The switches this process sees. Presence only, never the credential."""
    def get(name: str):
        if env is not None:
            return env.get(name)
        import os
        return os.environ.get(name)

    raw_key = get(DEFAULT_KEY_ENV)
    # Stripped before every test. A key pasted with a trailing newline is
    # present, is not blank, and still fails at the provider with a 401 that
    # says nothing about whitespace.
    key = str(raw_key or "").strip()

    def flag(name: str):
        try:
            return parse_optional_flag(name, get(name)) is True
        except ConfigurationFlagError:
            return "MALFORMED"

    return {
        f"{DEFAULT_KEY_ENV}_PRESENT": bool(key),
        f"{DEFAULT_KEY_ENV}_IS_PLACEHOLDER": key.lower() in _PLACEHOLDERS,
        # Reported because it is a real and silent failure: the value is
        # present and wrong only in ways stripping fixes.
        f"{DEFAULT_KEY_ENV}_HAD_SURROUNDING_WHITESPACE": bool(
            raw_key) and str(raw_key) != key,
        MULTIMODAL_ENABLED_ENV: flag(MULTIMODAL_ENABLED_ENV),
        LIVE_TEST_ENV: flag(LIVE_TEST_ENV),
        LIVE_CONFIG_ENABLED_ENV: flag(LIVE_CONFIG_ENABLED_ENV),
        APP_MODE_ENV: get(APP_MODE_ENV) or "public_synthetic",
    }


# ---------------------------------------------------------------- provider

def provider_report(config: dict, *, mode: str = "balanced",
                    env: Optional[dict] = None) -> dict:
    """Which endpoint, model and budgets are actually loaded for this session.

    Reads the SAME governor the call will use, so this cannot describe one
    configuration while the call uses another.
    """
    governor = LiveCallGovernor(config, env=env, mode=mode)
    live = config.get("live_provider") or {}
    spec = (config.get("providers") or {}).get(governor.provider_name) or {}
    resolved = governor.resolved
    entry = governor.allowlist_entry(resolved.model_id) or {}
    limits = governor.limits
    try:
        live_path = governor.live_path_enabled
    except ConfigurationFlagError:
        live_path = "MALFORMED"

    return {
        "provider_name": governor.provider_name,
        "endpoint": spec.get("endpoint") or "",
        "key_env": governor.key_env,
        "operating_mode": resolved.mode,
        "model_alias": resolved.alias,
        "selected_model": resolved.model_id,
        "config_provider_enabled": bool(config.get("enabled", False)),
        "config_live_provider_enabled": bool(live.get("enabled", False)),
        "runtime_override": live_path,
        "model_allowlisted": entry != {},
        "model_image_capable": entry.get("vision") is True,
        "model_blocked_reason": resolved.blocked_reason,
        "max_calls_per_field": limits.max_calls_per_field,
        "max_calls_per_document": limits.max_calls_per_document,
        "max_paid_attempts_per_field": limits.max_paid_attempts_per_field,
        "document_budget_usd": limits.max_document_spend_usd,
        "session_budget_usd": limits.max_session_spend_usd,
        "session_remaining_usd": governor.session_remaining_usd,
        "fallback_models_allowed": limits.allow_fallback_models,
        "automatic_reruns_allowed": limits.allow_automatic_reruns,
    }


def endpoint_warnings(report: dict) -> list[str]:
    """Named suspicions about the endpoint, so a misroute is not silent.

    A call that goes somewhere unintended is worse than a call that fails: it
    can succeed, bill a different account, and look exactly like success.
    """
    endpoint = str(report.get("endpoint") or "")
    warnings = []
    if not endpoint:
        warnings.append("no endpoint is configured for the selected provider")
        return warnings
    if not endpoint.startswith("https://"):
        warnings.append(f"endpoint is not HTTPS: {endpoint}")
    if report.get("provider_name") == "openrouter" and "openrouter.ai" not in endpoint:
        warnings.append(
            f"provider is openrouter but the endpoint is {endpoint}; refusing to "
            "assume an aggregator request may go to another host")
    for marker in ("localhost", "127.0.0.1", "example.com", "mock", "test"):
        if marker in endpoint.lower():
            warnings.append(f"endpoint looks like a test target: {endpoint}")
            break
    return warnings


# ----------------------------------------------------------------- dry run

def dry_run_receipt(request, *, governor: LiveCallGovernor, config: dict,
                    mode: str = "balanced") -> dict:
    """What this exact call WOULD send, and whether policy permits it.

    Safe metadata only: dimensions, a MIME type, a model id, a budget, and the
    request fingerprint. Deliberately absent are the crop bytes, the prompt, the
    field's current value and anything derived from the image — this receipt is
    meant to be shown to another person before money is spent.

    Uses ``preview_authorization``, which runs every live-policy check on a deep
    copy: no counter moves and no fingerprint is reserved by looking.
    """
    model = governor.model
    crop = getattr(request, "crop", None)
    outcome = governor.preview_authorization(request, model=model)
    limits = governor.limits

    return {
        "provider": governor.provider_name,
        "model": model,
        "operating_mode": governor.resolved.mode,
        "field_name": getattr(request, "field_name", ""),
        "crop_width_px": getattr(crop, "width", None),
        "crop_height_px": getattr(crop, "height", None),
        # Size, never content. engine/cropper.py encodes PNG at the PHI
        # boundary, so the type is a fact about the encoder, not a guess.
        "crop_bytes": len(getattr(crop, "png_bytes", b"") or b""),
        "crop_mime_type": "image/png",
        "crop_sha256": getattr(crop, "sha256", ""),
        "crop_page_fraction": getattr(crop, "page_fraction", None),
        "synthetic": bool(getattr(request, "synthetic", False)),
        "full_page": False,
        "crop_only": True,
        "organiser_data": False,
        "max_calls": limits.max_calls_per_field,
        "document_budget_usd": limits.max_document_spend_usd,
        "session_budget_usd": limits.max_session_spend_usd,
        "estimated_maximum_cost_usd": min(
            limits.max_document_spend_usd, limits.max_session_spend_usd),
        "request_fingerprint": fingerprint(request, model),
        "duplicate_protection": "active",
        "authorization": outcome.decision.value,
        "authorized": outcome.allowed,
        "authorization_reason": outcome.reason,
    }


def render_dry_run(receipt: dict) -> str:
    """The approval receipt as text, for a terminal or a Streamlit code block."""
    lines = [
        f"Provider:                 {receipt['provider']}",
        f"Model:                    {receipt['model']}",
        f"Operating mode:           {receipt['operating_mode']}",
        f"Field:                    {receipt['field_name']}",
        f"Input:                    synthetic field crop only",
        f"Crop:                     {receipt['crop_width_px']}x"
        f"{receipt['crop_height_px']} px, {receipt['crop_mime_type']}, "
        f"{receipt['crop_bytes']} bytes",
        f"Page fraction:            {receipt['crop_page_fraction']}",
        f"Full page:                no",
        f"Organiser data:           no",
        f"Maximum calls:            {receipt['max_calls']}",
        f"Document budget:          ${receipt['document_budget_usd']:.4f}",
        f"Session budget:           ${receipt['session_budget_usd']:.4f}",
        f"Estimated maximum cost:   ${receipt['estimated_maximum_cost_usd']:.4f}",
        f"Request fingerprint:      {receipt['request_fingerprint']}",
        f"Duplicate protection:     {receipt['duplicate_protection']}",
        f"Authorization:            {receipt['authorization']}",
    ]
    if not receipt["authorized"]:
        lines.append(f"Blocked because:          {receipt['authorization_reason']}")
    return "\n".join(lines)


# ------------------------------------------------------------- credential

class CredentialCheck:
    """The outcome of one non-billing credential probe."""

    def __init__(self, ok: bool, category: Optional[ErrorCategory] = None,
                 detail: str = "", status_code: Optional[int] = None,
                 latency_ms: float = 0.0):
        self.ok = ok
        self.category = category
        self.detail = detail
        self.status_code = status_code
        self.latency_ms = latency_ms

    @property
    def guidance(self) -> tuple[str, str]:
        if self.ok:
            return ("The credential is valid and the provider is reachable.", "")
        return explain(self.category or ErrorCategory.UNKNOWN_PROVIDER_ERROR)

    def to_dict(self) -> dict:
        summary, action = self.guidance
        return {"ok": self.ok,
                "category": self.category.value if self.category else "",
                "detail": self.detail, "status_code": self.status_code,
                "latency_ms": round(self.latency_ms, 1),
                "summary": summary, "required_action": action}


def check_credentials(*, key: Optional[str] = None, timeout_s: float = 15.0,
                      endpoint: str = CREDENTIAL_ENDPOINT,
                      opener=None) -> CredentialCheck:
    """Probe the credential WITHOUT sending a crop and without being billed.

    This exists so a 401 is never discovered by spending money on an image
    request. It distinguishes an invalid credential from an empty balance, an
    unreachable host, a rate limit and a provider outage — conditions that need
    four different people to do four different things, and which a single
    "multimodal failed" message made indistinguishable.

    The key is read from the environment when not supplied, is sent only in the
    Authorization header, and is never returned, logged, or placed in a detail
    string — including on failure, where an error message is most likely to be
    pasted somewhere public.
    """
    if key is None:
        import os
        key = os.environ.get(DEFAULT_KEY_ENV)
    key = str(key or "").strip()
    if not key:
        return CredentialCheck(
            False, ErrorCategory.CONFIGURATION_ERROR,
            f"{DEFAULT_KEY_ENV} is not set in this process")
    if key.lower() in _PLACEHOLDERS:
        return CredentialCheck(
            False, ErrorCategory.CONFIGURATION_ERROR,
            f"{DEFAULT_KEY_ENV} is still a placeholder value")

    request = urllib.request.Request(
        endpoint, method="GET",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    send = opener or urllib.request.urlopen
    started = time.perf_counter()
    try:
        with send(request, timeout=timeout_s) as response:
            body = response.read()
            elapsed = (time.perf_counter() - started) * 1000
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as error:
        elapsed = (time.perf_counter() - started) * 1000
        from engine.escalation.errors import category_for_status
        status = int(getattr(error, "code", 0) or 0)
        # The provider's human-readable body can echo request content and is
        # never surfaced. The status code carries everything needed.
        return CredentialCheck(False, category_for_status(status),
                               f"provider returned HTTP {status}",
                               status_code=status, latency_ms=elapsed)
    except urllib.error.URLError as error:
        elapsed = (time.perf_counter() - started) * 1000
        reason = getattr(error, "reason", "")
        category = (ErrorCategory.TIMEOUT
                    if isinstance(reason, TimeoutError) or "timed out" in str(reason)
                    else ErrorCategory.NETWORK_ERROR)
        return CredentialCheck(False, category, f"{type(reason).__name__}",
                               latency_ms=elapsed)
    except (TimeoutError, OSError) as error:
        elapsed = (time.perf_counter() - started) * 1000
        return CredentialCheck(False, ErrorCategory.NETWORK_ERROR,
                               f"{type(error).__name__}", latency_ms=elapsed)

    try:
        payload = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return CredentialCheck(False, ErrorCategory.INVALID_RESPONSE,
                               "credential endpoint did not return JSON",
                               status_code=status, latency_ms=elapsed)

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return CredentialCheck(False, ErrorCategory.INVALID_RESPONSE,
                               "credential endpoint returned an unexpected shape",
                               status_code=status, latency_ms=elapsed)

    # A key with a usage limit already reached will 402 on the real call. Saying
    # so here is the difference between one wasted request and none.
    limit = data.get("limit")
    usage = data.get("usage")
    if isinstance(limit, (int, float)) and isinstance(usage, (int, float)) \
            and not isinstance(limit, bool) and limit > 0 and usage >= limit:
        return CredentialCheck(False, ErrorCategory.INSUFFICIENT_CREDIT,
                               "the key has reached its configured usage limit",
                               status_code=status, latency_ms=elapsed)

    return CredentialCheck(True, None, "credential accepted",
                           status_code=status, latency_ms=elapsed)


def preflight(config: dict, *, mode: str = "balanced",
              env: Optional[dict] = None) -> dict:
    """Every local check, as one report. Opens no socket."""
    report = provider_report(config, mode=mode, env=env)
    return {
        "environment": environment_report(env),
        "provider": report,
        "endpoint_warnings": endpoint_warnings(report),
    }
