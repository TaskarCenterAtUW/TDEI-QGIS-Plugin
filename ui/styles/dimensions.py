# -*- coding: utf-8 -*-
"""Spacing and sizing tokens with screen-adaptive scaling."""

from __future__ import annotations

from typing import Optional

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24
SPACING_XXL = 32

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8

SIDEBAR_WIDTH = 220
SIDEBAR_COLLAPSED_WIDTH = 64
HEADER_HEIGHT = 52
CONTROL_HEIGHT = 32
LOGIN_CARD_WIDTH = 400
LOGIN_FIELD_HEIGHT = 36
MAP_SEARCH_FIELD_HEIGHT = 44
LOGIN_EYE_WIDTH = 36

ICON_SM = 16
ICON_MD = 24
ICON_LG = 28
NAV_ICON = 24
NAV_ROW = 40

# Design reference for adaptive scaling (logical pixels @ ~96 DPI).
_REF_WIDTH = 1440
_REF_HEIGHT = 900
_REF_DPI = 96.0
_UI_SCALE = 1.0


def ui_scale() -> float:
    return _UI_SCALE


def set_ui_scale(factor: float) -> None:
    global _UI_SCALE
    _UI_SCALE = max(0.9, min(1.35, float(factor)))


def s(value: float) -> int:
    """Scale a design-token pixel value for the current screen."""
    return max(1, int(round(float(value) * _UI_SCALE)))


def refresh_ui_scale(widget=None) -> float:
    """Recompute UI scale from the widget/screen geometry and DPI."""
    try:
        from qgis.PyQt.QtGui import QGuiApplication
    except Exception:
        set_ui_scale(1.0)
        return _UI_SCALE

    screen = None
    if widget is not None:
        try:
            screen = widget.screen()
        except Exception:
            screen = None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        set_ui_scale(1.0)
        return _UI_SCALE

    geo = screen.availableGeometry()
    size_factor = min(geo.width() / float(_REF_WIDTH), geo.height() / float(_REF_HEIGHT))
    dpi = float(screen.logicalDotsPerInch() or _REF_DPI)
    dpi_factor = dpi / _REF_DPI
    # Prefer geometry so large monitors get slightly larger chrome; clamp DPI
    # so Retina machines do not double-scale (Qt already applies devicePixelRatio).
    factor = (size_factor * 0.65) + (min(dpi_factor, 1.15) * 0.35)
    set_ui_scale(factor)
    return _UI_SCALE


def device_pixel_ratio(widget: Optional[object] = None) -> float:
    """Best-effort device pixel ratio for crisp pixmap rendering."""
    try:
        if widget is not None:
            dpr = float(widget.devicePixelRatioF())
            if dpr >= 1.0:
                return dpr
    except Exception:
        pass
    try:
        from qgis.PyQt.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            return max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        pass
    return 1.0


def overlay_panel_width(host_width: int) -> int:
    """Responsive sticky-panel width for the map canvas host (~90%)."""
    host_width = max(0, int(host_width or 0))
    margin = s(16)
    # Top-right map chrome + a thin strip of map still visible.
    chrome_reserve = s(160)
    available = max(s(360), host_width - margin * 2 - chrome_reserve)
    target = int(round(host_width * 0.90))
    minimum = s(560)
    return max(minimum, min(target, available))


def overlay_panel_height(host_height: int) -> int:
    """Responsive sticky-panel height for the map canvas host."""
    host_height = max(0, int(host_height or 0))
    margin = s(16)
    available = max(s(320), host_height - margin * 2)
    return available
