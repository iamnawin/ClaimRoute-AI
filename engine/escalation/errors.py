"""Typed failure categories for the multimodal boundary.

A provider can fail in ways that mean very different things operationally: a bad
key is a deployment defect, a 429 is a pacing problem, a malformed answer is a
schema problem, and a blocked response is a policy event. Collapsing them into
one "call failed" string loses exactly the information an operator needs, so the
category is part of the result contract rather than prose in a log line.

Retryability is a property of the category, decided once here, so no caller can
accidentally retry an authentication failure until the budget is gone.

Error details are SAFE BY CONSTRUCTION: they carry categories, HTTP status
codes, sizes and hashes — never crop bytes, extracted values, prompts, or
response bodies.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    # 402. A funding problem, not a credential problem. They arrive as adjacent
    # status codes and mean completely different things to whoever is on call:
    # one needs a new key, the other needs a payment. Reporting both as
    # "authentication failed" sends someone to rotate a key that works.
    INSUFFICIENT_CREDIT = "INSUFFICIENT_CREDIT"
    # 404 on an aggregator. The id was refused by the catalogue, which is a
    # configuration fact about the allowlist rather than an outage.
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    # 400. Our request was malformed. Retrying it reproduces it exactly.
    INVALID_REQUEST = "INVALID_REQUEST"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_5XX = "PROVIDER_5XX"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CONTENT_BLOCKED = "CONTENT_BLOCKED"
    UNSUPPORTED_IMAGE = "UNSUPPORTED_IMAGE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


# What an operator should DO about each category, and what it means. Safe to
# render verbatim: no category name here can carry request content.
OPERATOR_GUIDANCE = {
    ErrorCategory.AUTHENTICATION_ERROR: (
        "The provider rejected the credential.",
        "Check that OPENROUTER_API_KEY is a current, active key and restart the "
        "application. Local OCR, retry, review and exports are unaffected."),
    ErrorCategory.INSUFFICIENT_CREDIT: (
        "The credential is valid but the account cannot fund this call.",
        "Add credit to the OpenRouter account. No retry will succeed until then."),
    ErrorCategory.MODEL_NOT_AVAILABLE: (
        "The provider does not recognise the requested model id.",
        "Verify the id on openrouter.ai/models and correct it in "
        "configs/multimodal_models.yaml before allowlisting it."),
    ErrorCategory.INVALID_REQUEST: (
        "The provider rejected the request as malformed.",
        "This is a defect in the request we built, not in your configuration. "
        "Retrying reproduces it exactly."),
    ErrorCategory.RATE_LIMIT: (
        "The provider is rate limiting this account.",
        "Wait for the interval the provider reported and try once more."),
    ErrorCategory.TIMEOUT: (
        "The provider did not respond within the configured timeout.",
        "The field is routed to human review. One retry is safe."),
    ErrorCategory.NETWORK_ERROR: (
        "The provider could not be reached.",
        "Check network and TLS egress to openrouter.ai. Nothing was billed."),
    ErrorCategory.PROVIDER_5XX: (
        "The provider reported a server-side failure.",
        "This is an outage on their side. One retry is safe."),
    ErrorCategory.INVALID_RESPONSE: (
        "The provider answered, but not in the required structure.",
        "The answer is discarded and the field goes to human review. The call "
        "was still billed; a retry would bill again for the same defect."),
    ErrorCategory.CONTENT_BLOCKED: (
        "The provider's safety filter blocked the response.",
        "The field goes to human review. Retrying reproduces the block."),
    ErrorCategory.UNSUPPORTED_IMAGE: (
        "The crop is not in a format the provider accepts.",
        "The field goes to human review; no further call is made."),
    ErrorCategory.CONFIGURATION_ERROR: (
        "The provider could not be configured for this call.",
        "Check configs/multimodal_providers.yaml and the selected operating "
        "mode. No call was attempted."),
    ErrorCategory.UNKNOWN_PROVIDER_ERROR: (
        "The provider failed in a way this application does not recognise.",
        "The field goes to human review. The safe error detail is recorded."),
}


def explain(category: "ErrorCategory | str") -> tuple[str, str]:
    """-> (what happened, what to do). Never generic, never payload-bearing.

    "Multimodal failed" is not an explanation: a bad key, an empty balance, a
    wrong model id and an outage all need different people to do different
    things, and one message for all four sends every one of them to guess.
    """
    try:
        key = ErrorCategory(category)
    except ValueError:
        return OPERATOR_GUIDANCE[ErrorCategory.UNKNOWN_PROVIDER_ERROR]
    return OPERATOR_GUIDANCE.get(
        key, OPERATOR_GUIDANCE[ErrorCategory.UNKNOWN_PROVIDER_ERROR])


# Transient conditions only. A retry must be able to succeed without anything
# else changing — which is why AUTHENTICATION_ERROR, CONFIGURATION_ERROR,
# CONTENT_BLOCKED and UNSUPPORTED_IMAGE are absent: retrying them burns money to
# reach the identical outcome.
RETRYABLE = frozenset({
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.TIMEOUT,
    ErrorCategory.NETWORK_ERROR,
    ErrorCategory.PROVIDER_5XX,
})


class MultimodalError(RuntimeError):
    """A categorised provider failure. Detail must stay free of payload content."""

    def __init__(self, category: ErrorCategory, detail: str = "",
                 *, status_code: Optional[int] = None,
                 retry_after_s: Optional[float] = None):
        self.category = category
        self.detail = detail
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        super().__init__(f"{category.value}: {detail}" if detail else category.value)

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "detail": self.detail,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }


def category_for_status(status: int) -> ErrorCategory:
    """HTTP status -> category. Shared by every HTTP provider so two adapters
    cannot disagree about what a 429 means.

    402, 404 and 400 used to fall through to UNKNOWN_PROVIDER_ERROR, which put
    an empty balance, a wrong model id and a malformed request behind one
    message. Each needs a different person to do a different thing, so each has
    its own category now.
    """
    if status in (401, 403):
        return ErrorCategory.AUTHENTICATION_ERROR
    if status == 402:
        return ErrorCategory.INSUFFICIENT_CREDIT
    if status == 404:
        return ErrorCategory.MODEL_NOT_AVAILABLE
    if status == 408:
        return ErrorCategory.TIMEOUT
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status >= 500:
        return ErrorCategory.PROVIDER_5XX
    if status == 400:
        return ErrorCategory.INVALID_REQUEST
    return ErrorCategory.UNKNOWN_PROVIDER_ERROR
