# -*- coding: utf-8 -*-
"""Map HTTP failures to domain exceptions."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError

from ..core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    UnexpectedApiError,
)


def map_http_error(exc: HTTPError) -> Exception:
    status = exc.code
    message = _extract_message(exc)
    if status == 401:
        return AuthenticationError(message or "Not authorized. Please sign in again.")
    if status == 403:
        return AuthorizationError(message or "You do not have permission for this action.")
    if status == 404:
        return NotFoundError(message or "The requested resource was not found.")
    if status == 429:
        return RateLimitError(message or "Too many requests. Please wait and try again.")
    if 400 <= status < 500:
        return UnexpectedApiError(message or "Request failed.", status_code=status)
    if status >= 500:
        return ServerError(
            message or "The server could not complete the request.",
            status_code=status,
        )
    return UnexpectedApiError(message or "Unexpected API error.", status_code=status)


def map_url_error(exc: URLError) -> Exception:
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if "timed out" in text.lower() or isinstance(reason, TimeoutError):
        return TimeoutError("The request timed out. Please try again.")
    return NetworkError(
        "Unable to connect to TDEI. Please check your network connection."
    )


def _extract_message(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        raw = ""
    payload: Any = {}
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "title"):
            value = payload.get(key)
            if value:
                return str(value)
    if raw:
        return raw[:300]
    return ""
