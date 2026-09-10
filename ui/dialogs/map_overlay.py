# -*- coding: utf-8 -*-
"""Shared helpers for floating map overlays (glass chrome, cursor restore)."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QCursor


def apply_glass_frame(widget) -> None:
    """Enable styled translucent background painting for overlay frames."""
    try:
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setAttribute(Qt.WA_TranslucentBackground, False)
        widget.setAutoFillBackground(False)
    except Exception:  # noqa: BLE001
        pass


def pointer_over_overlay(widget, *, entering: bool, map_canvas=None) -> None:
    """Use a normal pointer on overlays so active map tools do not steal UI clicks.

    While the cursor is over the overlay, force ArrowCursor on the widget (and
    temporarily on the map canvas). On leave, restore the active map tool cursor.
    """
    try:
        if entering:
            widget.setCursor(QCursor(Qt.ArrowCursor))
            if map_canvas is not None:
                map_canvas.setCursor(QCursor(Qt.ArrowCursor))
            return
        widget.unsetCursor()
        if map_canvas is None:
            return
        tool = None
        try:
            tool = map_canvas.mapTool()
        except Exception:  # noqa: BLE001
            tool = None
        if tool is not None:
            try:
                map_canvas.setCursor(tool.cursor())
                return
            except Exception:  # noqa: BLE001
                pass
        map_canvas.unsetCursor()
    except Exception:  # noqa: BLE001
        pass
