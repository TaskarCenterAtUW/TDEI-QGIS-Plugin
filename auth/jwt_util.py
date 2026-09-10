# -*- coding: utf-8 -*-
"""Decode JWT access-token payloads (no signature verification)."""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

_TDEI_ADMIN_ROLE = "tdei-admin"


def decode_jwt_payload(token: Optional[str]) -> Dict[str, Any]:
    """Return the JSON payload of a JWT, or ``{}`` if it cannot be decoded."""
    if not token or token.count(".") != 2:
        return {}
    try:
        payload = token.split(".")[1]
        # Match TDEI portal AuthProvider decode (base64url → standard)
        normalized = payload.replace("-", "+").replace("_", "/")
        padding = "=" * (-len(normalized) % 4)
        raw = base64.b64decode(normalized + padding)
        data = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def jwt_sub(token: Optional[str]) -> str:
    """Return the JWT ``sub`` claim (TDEI user id), or empty string."""
    value = decode_jwt_payload(token).get("sub")
    return str(value).strip() if value else ""


def jwt_realm_roles(token: Optional[str]) -> List[str]:
    """Return ``realm_access.roles`` from the JWT (empty when missing)."""
    payload = decode_jwt_payload(token)
    realm = payload.get("realm_access")
    if not isinstance(realm, dict):
        return []
    roles = realm.get("roles")
    if not isinstance(roles, list):
        return []
    return [str(role).strip() for role in roles if str(role).strip()]


def is_tdei_admin(token: Optional[str]) -> bool:
    """True when the JWT includes the ``tdei-admin`` realm role."""
    wanted = _TDEI_ADMIN_ROLE.casefold()
    return any(role.casefold() == wanted for role in jwt_realm_roles(token))
