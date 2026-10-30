"""Errors raised by the client.

The subclasses let a caller branch on what to do next — wait, buy a plan,
fix the input — without parsing messages. The message itself is the API's
own, written in German for the person who reads it.
"""

from __future__ import annotations

from typing import Any


class InvoapiError(Exception):
    """Any refusal from the API, or a failure to reach it."""

    def __init__(
        self,
        message: str,
        http_status: int = 0,
        code: str | None = None,
        request_id: str | None = None,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: HTTP status, or 0 when the request never got an answer.
        self.http_status = http_status
        #: Stable error code such as ``RATE_LIMITED`` or ``QUOTA_EXHAUSTED``.
        self.code = code
        #: Quote this in a support request; it finds the call in the logs.
        self.request_id = request_id
        self.details: list[Any] = details or []


class InvalidRequestError(InvoapiError):
    """400/422: the invoice or document is faulty. ``details`` names the fields."""


class AuthenticationError(InvoapiError):
    """401/403: wrong key, unconfirmed email or suspended account."""


class QuotaExhaustedError(InvoapiError):
    """402: the free allowance is used up. Choose a plan at invoapi.de/preise."""


class RateLimitError(InvoapiError):
    """429: too many calls for the plan's rate. Wait ``retry_after`` seconds."""

    def __init__(self, *args: Any, retry_after: int = 60, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class ServiceUnavailableError(InvoapiError):
    """5xx: the service is briefly unavailable. Try again later."""


class APIConnectionError(InvoapiError):
    """No connection: DNS, TLS or timeout."""
