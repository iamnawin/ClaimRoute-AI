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
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_5XX = "PROVIDER_5XX"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CONTENT_BLOCKED = "CONTENT_BLOCKED"
    UNSUPPORTED_IMAGE = "UNSUPPORTED_IMAGE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


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
    cannot disagree about what a 429 means."""
    if status in (401, 403):
        return ErrorCategory.AUTHENTICATION_ERROR
    if status == 408:
        return ErrorCategory.TIMEOUT
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status >= 500:
        return ErrorCategory.PROVIDER_5XX
    return ErrorCategory.UNKNOWN_PROVIDER_ERROR
