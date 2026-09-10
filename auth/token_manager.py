# -*- coding: utf-8 -*-
"""Token storage, expiry, and refresh orchestration.

Assumption: Current TDEI authenticate endpoint returns an access token and
may omit refresh tokens. TokenManager still models refresh so a future API
change requires only Auth API wiring — not UI or client rewrites.

Tokens are stored in QSettings under an obfuscated key. QGIS plugins do not
have a portable OS keychain API; we avoid logging tokens and clear them on
logout. Prefer short-lived access tokens from the server.
"""

from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING, Callable, List, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core.models import TokenPair
from ..logging.logger import get_logger

if TYPE_CHECKING:
    from ..config.settings import SettingsManager

LOG = get_logger(__name__)


class TokenManager(QObject):
    """Owns access/refresh tokens and expiry metadata."""

    tokens_changed = pyqtSignal()
    tokens_cleared = pyqtSignal()

    _ACCESS_KEY = "secure/at"
    _REFRESH_KEY = "secure/rt"
    _EXPIRES_KEY = "secure/exp"
    _TYPE_KEY = "secure/tt"

    def __init__(self, settings: "SettingsManager") -> None:
        super().__init__()
        self._settings = settings
        self._memory: Optional[TokenPair] = None
        self._listeners: List[Callable[[], None]] = []

    def store(self, tokens: TokenPair) -> None:
        self._memory = tokens
        self._settings.set(self._ACCESS_KEY, self._encode(tokens.access_token))
        if tokens.refresh_token:
            self._settings.set(
                self._REFRESH_KEY, self._encode(tokens.refresh_token)
            )
        else:
            self._settings.remove(self._REFRESH_KEY)
        if tokens.expires_at is not None:
            self._settings.set(self._EXPIRES_KEY, float(tokens.expires_at))
        else:
            self._settings.remove(self._EXPIRES_KEY)
        self._settings.set(self._TYPE_KEY, tokens.token_type or "Bearer")
        LOG.info("Authentication tokens updated")
        self.tokens_changed.emit()

    def load(self) -> Optional[TokenPair]:
        if self._memory is not None:
            return self._memory
        encoded = self._settings.get(self._ACCESS_KEY, "")
        if not encoded:
            return None
        access = self._decode(str(encoded))
        if not access:
            return None
        refresh_enc = self._settings.get(self._REFRESH_KEY, "")
        refresh = self._decode(str(refresh_enc)) if refresh_enc else None
        expires = self._settings.get(self._EXPIRES_KEY, None)
        try:
            expires_at = float(expires) if expires is not None else None
        except (TypeError, ValueError):
            expires_at = None
        token_type = str(self._settings.get(self._TYPE_KEY, "Bearer") or "Bearer")
        self._memory = TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            token_type=token_type,
        )
        return self._memory

    def get_access_token(self) -> Optional[str]:
        tokens = self.load()
        return tokens.access_token if tokens else None

    def get_refresh_token(self) -> Optional[str]:
        tokens = self.load()
        return tokens.refresh_token if tokens else None

    def clear(self) -> None:
        self._memory = None
        self._settings.remove(self._ACCESS_KEY)
        self._settings.remove(self._REFRESH_KEY)
        self._settings.remove(self._EXPIRES_KEY)
        self._settings.remove(self._TYPE_KEY)
        LOG.info("Authentication tokens cleared")
        self.tokens_cleared.emit()

    def is_expired(self, skew_seconds: Optional[int] = None) -> bool:
        tokens = self.load()
        if tokens is None:
            return True
        if tokens.expires_at is None:
            return False
        skew = (
            skew_seconds
            if skew_seconds is not None
            else self._settings.int("token_refresh_skew_seconds", 60)
        )
        return time.time() >= (tokens.expires_at - skew)

    def has_refresh_token(self) -> bool:
        return bool(self.get_refresh_token())

    @staticmethod
    def _encode(value: str) -> str:
        # Obfuscation only — not encryption. Documented limitation.
        return base64.b64encode(value.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode(value: str) -> str:
        try:
            return base64.b64decode(value.encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001
            return ""
