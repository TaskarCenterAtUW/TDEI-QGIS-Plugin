# -*- coding: utf-8 -*-
"""Map tool: pick a start edge / destination point, with pan and zoom."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.gui import QgsMapTool

from .bbox_map_tool import BBoxMapTool


class RouteMapTool(QgsMapTool):
    """One tool for the whole routability session (keeps it alive on pan/zoom)."""

    INTERACT_START = "start"
    INTERACT_DEST = "dest"
    INTERACT_PAN = "pan"
    INTERACT_ZOOM_IN = "zoom_in"
    INTERACT_ZOOM_OUT = "zoom_out"

    point_picked = pyqtSignal(str, object)  # interaction, QgsPointXY (canvas CRS)
    cancelled = pyqtSignal()
    interaction_changed = pyqtSignal(str)

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self._interaction = self.INTERACT_START
        self._panning = False
        self._update_cursor()

    def interaction(self) -> str:
        return self._interaction

    def set_interaction(self, mode: str) -> None:
        allowed = (
            self.INTERACT_START,
            self.INTERACT_DEST,
            self.INTERACT_PAN,
            self.INTERACT_ZOOM_IN,
            self.INTERACT_ZOOM_OUT,
        )
        mode = mode if mode in allowed else self.INTERACT_START
        if self._panning:
            self._end_pan(None)
        changed = mode != self._interaction
        self._interaction = mode
        self._update_cursor()
        if changed:
            self.interaction_changed.emit(mode)

    def canvasPressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton
            and self._interaction == self.INTERACT_PAN
        ):
            self._panning = True
            self._apply_cursor(QCursor(Qt.ClosedHandCursor))
            return
        if event.button() != Qt.LeftButton:
            return
        if self._interaction in (self.INTERACT_ZOOM_IN, self.INTERACT_ZOOM_OUT):
            zoom_in = self._interaction == self.INTERACT_ZOOM_IN
            try:
                self._canvas.zoomWithCenter(event.pos(), zoom_in)
            except Exception:  # noqa: BLE001
                if zoom_in:
                    self._canvas.zoomIn()
                else:
                    self._canvas.zoomOut()

    def canvasMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            try:
                self._canvas.panAction(event)
            except Exception:  # noqa: BLE001
                pass

    def canvasReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._end_pan(event)
            return
        if event.button() != Qt.LeftButton:
            return
        if self._interaction in (self.INTERACT_START, self.INTERACT_DEST):
            point = self.toMapCoordinates(event.pos())
            self.point_picked.emit(self._interaction, point)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def activate(self) -> None:
        super().activate()
        self._update_cursor()

    def deactivate(self) -> None:
        if self._panning:
            self._end_pan(None)
        super().deactivate()

    def _end_pan(self, event) -> None:
        if event is not None:
            try:
                self._canvas.panActionEnd(event.pos())
            except Exception:  # noqa: BLE001
                pass
        self._panning = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._panning:
            cursor = QCursor(Qt.ClosedHandCursor)
        elif self._interaction == self.INTERACT_PAN:
            cursor = QCursor(Qt.OpenHandCursor)
        elif self._interaction == self.INTERACT_ZOOM_IN:
            cursor = BBoxMapTool._theme_cursor("ZoomIn")
        elif self._interaction == self.INTERACT_ZOOM_OUT:
            cursor = BBoxMapTool._theme_cursor("ZoomOut")
        else:
            cursor = BBoxMapTool._theme_cursor("CrossHair")
        self._apply_cursor(cursor)

    def _apply_cursor(self, cursor: QCursor) -> None:
        self.setCursor(cursor)
        try:
            if self._canvas is not None and self._canvas.mapTool() is self:
                self._canvas.setCursor(cursor)
        except Exception:  # noqa: BLE001
            pass
