# -*- coding: utf-8 -*-
"""API v1 user-profile helpers (portal user-management)."""

from __future__ import annotations

from typing import Any, Tuple


def parse_user_profile_names(payload: Any) -> Tuple[str, str]:
    """Extract first / last name from a user-profile response."""
    data = _as_dict(payload)
    first = _pick(
        data,
        (
            "first_name",
            "firstname",
            "firstName",
            "given_name",
            "givenName",
        ),
    )
    last = _pick(
        data,
        (
            "last_name",
            "lastname",
            "lastName",
            "family_name",
            "familyName",
            "surname",
        ),
    )
    return first, last


def _as_dict(payload: Any) -> dict:
    if isinstance(payload, dict):
        for key in ("data", "user", "profile", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return nested
        return payload
    return {}


def _pick(data: dict, keys: tuple) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
