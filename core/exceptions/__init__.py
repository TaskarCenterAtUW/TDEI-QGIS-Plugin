# -*- coding: utf-8 -*-
"""Application-level exceptions (UI should not parse HTTP codes)."""

from __future__ import annotations

from typing import Optional


class TdeiError(Exception):
    """Base plugin exception."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.cause = cause


class AuthenticationError(TdeiError):
    """Invalid credentials or missing auth."""


class AuthorizationError(TdeiError):
    """Authenticated but not allowed."""


class SessionExpiredError(TdeiError):
    """Access token expired and refresh failed or unavailable."""


class ValidationError(TdeiError):
    """Client-side or API validation failure."""


class NetworkError(TdeiError):
    """Connectivity failure."""


class TimeoutError(TdeiError):  # noqa: A001 — domain name matches prompt
    """Request timed out."""


class ServerError(TdeiError):
    """5xx from API."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        *,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message, cause=cause)
        self.status_code = status_code


class NotFoundError(TdeiError):
    """404."""


class RateLimitError(TdeiError):
    """429."""


class UnexpectedApiError(TdeiError):
    """Unmapped API failure."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        *,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message, cause=cause)
        self.status_code = status_code


class ConfigurationError(TdeiError):
    """Invalid plugin configuration."""


class CancelledError(TdeiError):
    """User or system cancelled an operation."""
