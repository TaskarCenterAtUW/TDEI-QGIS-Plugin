# -*- coding: utf-8 -*-
"""Session restoration and user identity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core.models import AuthState, UserSession

if TYPE_CHECKING:
    from .token_manager import TokenManager


class SessionManager(QObject):
    auth_state_changed = pyqtSignal(object)
    user_changed = pyqtSignal(object)

    def __init__(self, token_manager: "TokenManager") -> None:
        super().__init__()
        self._tokens = token_manager
        self._user: Optional[UserSession] = None
        self._state = AuthState.ANONYMOUS

    @property
    def state(self) -> AuthState:
        return self._state

    @property
    def user(self) -> Optional[UserSession]:
        return self._user

    def restore(self) -> bool:
        tokens = self._tokens.load()
        if tokens and tokens.access_token and not self._tokens.is_expired():
            self._set_state(AuthState.AUTHENTICATED)
            return True
        if tokens and self._tokens.is_expired():
            self._set_state(AuthState.EXPIRED)
            return False
        self._set_state(AuthState.ANONYMOUS)
        return False

    def set_user(self, user: Optional[UserSession]) -> None:
        self._user = user
        self.user_changed.emit(user)

    def mark_authenticated(self, user: UserSession) -> None:
        self._user = user
        self._set_state(AuthState.AUTHENTICATED)
        self.user_changed.emit(user)

    def mark_expired(self) -> None:
        self._set_state(AuthState.EXPIRED)

    def mark_refreshing(self) -> None:
        self._set_state(AuthState.REFRESHING)

    def clear(self) -> None:
        self._user = None
        self._set_state(AuthState.ANONYMOUS)
        self.user_changed.emit(None)

    def _set_state(self, state: AuthState) -> None:
        if self._state != state:
            self._state = state
            self.auth_state_changed.emit(state)
