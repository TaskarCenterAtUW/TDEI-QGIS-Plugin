# -*- coding: utf-8 -*-
"""QGIS version compatibility helpers.

All QGIS version checks should live here — not scattered in feature code.
"""

from __future__ import annotations

from typing import Tuple

from qgis.core import Qgis


def qgis_version_tuple() -> Tuple[int, int, int]:
    version = Qgis.QGIS_VERSION_INT  # e.g. 33400 for 3.34.0
    major = version // 10000
    minor = (version % 10000) // 100
    patch = version % 100
    return major, minor, patch


def qgis_at_least(major: int, minor: int = 0, patch: int = 0) -> bool:
    return qgis_version_tuple() >= (major, minor, patch)


def message_level_info():
    return Qgis.Info


def message_level_warning():
    return Qgis.Warning


def message_level_critical():
    return Qgis.Critical


def message_level_success():
    # Qgis.Success exists from QGIS 3.x modern builds
    return getattr(Qgis, "Success", Qgis.Info)
