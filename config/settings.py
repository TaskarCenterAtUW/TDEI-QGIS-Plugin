# -*- coding: utf-8 -*-
"""Persistent plugin settings via QSettings (non-secret)."""

from __future__ import annotations

from typing import Any, Optional

from qgis.core import QgsSettings

from .defaults import CONFIG_VERSION, DEFAULTS
from .migrations import MigrationManager


class SettingsManager:
    """Typed access to plugin QSettings under a dedicated root key."""

    ROOT = "tdei_plugin"

    def __init__(self, qsettings: Optional[QgsSettings] = None) -> None:
        self._qs = qsettings or QgsSettings()
        MigrationManager(self).ensure_current()

    def get(self, key: str, default: Any = None) -> Any:
        if default is None and key in DEFAULTS:
            default = DEFAULTS[key]
        return self._qs.value(self._path(key), default)

    def set(self, key: str, value: Any) -> None:
        self._qs.setValue(self._path(key), value)

    def remove(self, key: str) -> None:
        self._qs.remove(self._path(key))

    def bool(self, key: str, default: Optional[bool] = None) -> bool:
        if default is None:
            default = bool(DEFAULTS.get(key, False))
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes")
        return bool(value)

    def int(self, key: str, default: Optional[int] = None) -> int:
        if default is None:
            default = int(DEFAULTS.get(key, 0))
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def feature_enabled(self, name: str) -> bool:
        return self.bool("feature.{}".format(name), True)

    def config_version(self) -> int:
        return self.int("config_version", CONFIG_VERSION)

    def set_config_version(self, version: int) -> None:
        self.set("config_version", version)

    def _path(self, key: str) -> str:
        return "{}/{}".format(self.ROOT, key)
