# -*- coding: utf-8 -*-
"""Login use-case service consumed by UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .auth_manager import AuthManager
    from ..core.models import UserSession


class LoginService:
    def __init__(self, auth_manager: "AuthManager") -> None:
        self._auth = auth_manager

    def sign_in(self, username: str, password: str) -> "UserSession":
        return self._auth.login(username.strip(), password)

    def sign_out(self) -> None:
        self._auth.logout()

    def is_authenticated(self) -> bool:
        return self._auth.is_authenticated()

    def refresh_profile(self):
        return self._auth.refresh_profile()
