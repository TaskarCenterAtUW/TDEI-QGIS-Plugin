# -*- coding: utf-8 -*-
"""Authentication orchestration (no UI)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core.exceptions import AuthenticationError, SessionExpiredError
from ..core.models import TokenPair, UserSession
from ..api.v1.user_profile import parse_user_profile_names
from ..logging.logger import get_logger

if TYPE_CHECKING:
    from ..api.client import ApiClient
    from ..config.settings import SettingsManager
    from .session_manager import SessionManager
    from .token_manager import TokenManager

LOG = get_logger(__name__)


class AuthManager(QObject):
    login_succeeded = pyqtSignal(object)
    login_failed = pyqtSignal(str)
    logged_out = pyqtSignal()
    session_expired = pyqtSignal()

    def __init__(
        self,
        api_client: "ApiClient",
        token_manager: "TokenManager",
        session_manager: "SessionManager",
        settings: "SettingsManager",
    ) -> None:
        super().__init__()
        self._api = api_client
        self._tokens = token_manager
        self._session = session_manager
        self._settings = settings

    def login(self, username: str, password: str) -> UserSession:
        if not username or not password:
            raise AuthenticationError("Enter both username and password.")
        tokens = self._api.authenticate(username, password)
        self._tokens.store(tokens)
        user = UserSession(username=username, display_name=username)
        user = self._enrich_profile(user)
        self._session.mark_authenticated(user)
        if self._settings.bool("remember_username", True):
            self._settings.set("ui.last_username", username)
        LOG.info("User signed in")
        self.login_succeeded.emit(user)
        return user

    def refresh_profile(self) -> Optional[UserSession]:
        """Fetch first/last name from portal user-profile for the header."""
        user = self._session.user
        if user is None:
            username = str(
                self._settings.get("ui.last_username", "") or ""
            ).strip()
            if not username:
                return None
            user = UserSession(username=username, display_name=username)
        user = self._enrich_profile(user)
        self._session.mark_authenticated(user)
        return user

    def _enrich_profile(self, user: UserSession) -> UserSession:
        try:
            payload = self._api.get_user_management(
                "user-profile",
                params={"user_name": user.username},
            )
            first, last = parse_user_profile_names(payload)
            if first or last:
                user.first_name = first
                user.last_name = last
                user.display_name = user.full_name
        except Exception as exc:  # noqa: BLE001 — keep email fallback
            LOG.warning(
                "user-profile lookup failed: %s", type(exc).__name__
            )
        return user

    def logout(self) -> None:
        self._tokens.clear()
        self._session.clear()
        LOG.info("User signed out")
        self.logged_out.emit()

    def is_authenticated(self) -> bool:
        return bool(self._tokens.get_access_token()) and not self._tokens.is_expired()

    def is_tdei_admin(self) -> bool:
        """True when the access token has realm role ``tdei-admin``."""
        from .jwt_util import is_tdei_admin as jwt_is_admin

        return jwt_is_admin(self._tokens.get_access_token())

    def try_restore(self) -> bool:
        return self._session.restore()

    def refresh_if_needed(self) -> bool:
        if not self._tokens.is_expired():
            return True
        refresh = self._tokens.get_refresh_token()
        if not refresh:
            self.handle_unauthorized()
            return False
        self._session.mark_refreshing()
        try:
            tokens = self._api.refresh_tokens(refresh)
            self._tokens.store(tokens)
            if self._session.user:
                self._session.mark_authenticated(self._session.user)
            return True
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Token refresh failed: %s", type(exc).__name__)
            self.handle_unauthorized()
            return False

    def handle_unauthorized(self) -> None:
        self._tokens.clear()
        self._session.mark_expired()
        self.session_expired.emit()

    def require_session(self) -> None:
        if not self.is_authenticated():
            if not self.refresh_if_needed():
                raise SessionExpiredError(
                    "Your session has expired. Please sign in again."
                )
