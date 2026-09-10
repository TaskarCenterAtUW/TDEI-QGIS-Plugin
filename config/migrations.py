# -*- coding: utf-8 -*-
"""Configuration schema migrations between plugin versions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Tuple

from .defaults import CONFIG_VERSION, DEFAULTS

if TYPE_CHECKING:
    from .settings import SettingsManager

Migration = Tuple[int, Callable[["SettingsManager"], None]]


class MigrationManager:
    """Apply ordered migrations until ``CONFIG_VERSION`` is reached."""

    def __init__(self, settings: "SettingsManager") -> None:
        self._settings = settings
        self._migrations: List[Migration] = [
            (1, self._migrate_to_v1),
            (2, self._migrate_to_v2),
        ]

    def ensure_current(self) -> None:
        current = self._settings.config_version()
        if current <= 0:
            current = 0
        for target, migrate in self._migrations:
            if current < target:
                migrate(self._settings)
                self._settings.set_config_version(target)
                current = target
        if current < CONFIG_VERSION:
            self._settings.set_config_version(CONFIG_VERSION)

    @staticmethod
    def _migrate_to_v1(settings: "SettingsManager") -> None:
        """Seed defaults for first production schema."""
        for key, value in DEFAULTS.items():
            if settings.get(key, None) is None:
                settings.set(key, value)

    @staticmethod
    def _migrate_to_v2(settings: "SettingsManager") -> None:
        """Add per-environment URL override keys (empty = use presets)."""
        for key in (
            "env.development.api_base_url",
            "env.development.user_management_api_base_url",
            "env.staging.api_base_url",
            "env.staging.user_management_api_base_url",
            "env.production.api_base_url",
            "env.production.user_management_api_base_url",
        ):
            if settings.get(key, None) is None:
                settings.set(key, DEFAULTS.get(key, ""))
        # Drop legacy "custom" active env onto production if still selected.
        if settings.get("environment") == "custom":
            settings.set("environment", "production")
