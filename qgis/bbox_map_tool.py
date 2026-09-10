# -*- coding: utf-8 -*-
"""Map tool: draw bbox with draw / pan / zoom interaction modes."""

from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.core import QgsPointXY, QgsRectangle, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand


class BBoxMapTool(QgsMapTool):
    """One tool, several interactions — keeps clip session alive."""

    INTERACT_DRAW = "draw"
    INTERACT_PAN = "pan"
    INTERACT_ZOOM_IN = "zoom_in"
    INTERACT_ZOOM_OUT = "zoom_out"

    PHASE_DRAW = "draw"
    PHASE_CONFIRM = "confirm"

    bbox_drawn = pyqtSignal(object)  # QgsRectangle
    cancelled = pyqtSignal()
    interaction_changed = pyqtSignal(str)

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self._start = None  # type: Optional[QgsPointXY]
        self._dragging = False
        self._panning = False
        self._interaction = self.INTERACT_DRAW
        self._phase = self.PHASE_DRAW
        self._preserve = False
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber.setColor(QColor(50, 0, 110, 60))
        self._rubber.setStrokeColor(QColor(50, 0, 110, 220))
        self._rubber.setWidth(2)
        self._update_cursor()

    def interaction(self) -> str:
        return self._interaction

    def set_interaction(self, mode: str) -> None:
        allowed = (
            self.INTERACT_DRAW,
            self.INTERACT_PAN,
            self.INTERACT_ZOOM_IN,
            self.INTERACT_ZOOM_OUT,
        )
        mode = mode if mode in allowed else self.INTERACT_DRAW
        if mode == self._interaction and not self._panning:
            self._update_cursor()
            return
        if self._panning:
            self._end_pan(None)
        self._interaction = mode
        self._dragging = False
        self._start = None
        self._update_cursor()
        self.interaction_changed.emit(self._interaction)

    def set_phase(self, phase: str) -> None:
        self._phase = (
            self.PHASE_CONFIRM if phase == self.PHASE_CONFIRM else self.PHASE_DRAW
        )
        if self._phase == self.PHASE_DRAW:
            self._preserve = False
        self._dragging = False
        self._start = None
        self._update_cursor()

    # Back-compat helpers used by older controller paths
    def set_mode(self, mode: str) -> None:
        self.set_phase(
            self.PHASE_CONFIRM if mode == "confirm" else self.PHASE_DRAW
        )

    def set_pan_mode(self, enabled: bool) -> None:
        self.set_interaction(
            self.INTERACT_PAN if enabled else self.INTERACT_DRAW
        )

    def pan_mode(self) -> bool:
        return self._interaction == self.INTERACT_PAN

    def canvasPressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            if (
                self._phase == self.PHASE_DRAW
                and self._interaction == self.INTERACT_DRAW
            ):
                self.reset()
                self.cancelled.emit()
            return

        if event.button() == Qt.MiddleButton:
            self._start_pan(event)
            return

        if event.button() != Qt.LeftButton:
            return

        if self._interaction == self.INTERACT_PAN:
            self._start_pan(event)
            return

        if self._interaction == self.INTERACT_ZOOM_IN:
            try:
                self._canvas.zoomWithCenter(event.pos(), True)
            except Exception:  # noqa: BLE001
                self._canvas.zoomIn()
            return

        if self._interaction == self.INTERACT_ZOOM_OUT:
            try:
                self._canvas.zoomWithCenter(event.pos(), False)
            except Exception:  # noqa: BLE001
                self._canvas.zoomOut()
            return

        # Draw rectangle only in draw interaction + draw phase
        if self._interaction != self.INTERACT_DRAW:
            return
        if self._phase != self.PHASE_DRAW:
            return

        self._start = self.toMapCoordinates(event.pos())
        self._dragging = True
        if not self._preserve:
            self._rubber.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            try:
                self._canvas.panAction(event)
            except Exception:  # noqa: BLE001
                pass
            return
        if not self._dragging or self._start is None:
            return
        current = self.toMapCoordinates(event.pos())
        self._set_rect(self._start, current)

    def canvasReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._end_pan(event)
            return

        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        if self._start is None:
            return
        end = self.toMapCoordinates(event.pos())
        rect = QgsRectangle(self._start, end)
        rect.normalize()
        if rect.isEmpty() or rect.width() == 0 or rect.height() == 0:
            if not self._preserve:
                self._rubber.reset(QgsWkbTypes.PolygonGeometry)
            return
        self._set_rect(self._start, end)
        self.bbox_drawn.emit(QgsRectangle(rect))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            if self._interaction != self.INTERACT_DRAW:
                self.set_interaction(self.INTERACT_DRAW)
                event.accept()
                return
            self.reset()
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
        self._start = None
        self._dragging = False
        if not self._preserve:
            self._rubber.reset(QgsWkbTypes.PolygonGeometry)
        super().deactivate()

    def reset(self) -> None:
        self._preserve = False
        self._start = None
        self._dragging = False
        if self._panning:
            self._end_pan(None)
        self._rubber.reset(QgsWkbTypes.PolygonGeometry)

    def keep_rectangle(self, rect: QgsRectangle) -> None:
        self._preserve = True
        self._phase = self.PHASE_CONFIRM
        self._dragging = False
        self._start = None
        self._rubber.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
        self._rubber.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
        self._rubber.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
        self._rubber.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), True)
        self._update_cursor()

    def clear(self) -> None:
        self._phase = self.PHASE_DRAW
        self.set_interaction(self.INTERACT_DRAW)
        self.reset()

    def _start_pan(self, event) -> None:
        self._panning = True
        self._dragging = False
        self._start = None
        self._apply_cursor(QCursor(Qt.ClosedHandCursor))

    def _end_pan(self, event) -> None:
        if event is not None:
            try:
                self._canvas.panActionEnd(event.pos())
            except Exception:  # noqa: BLE001
                pass
        self._panning = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        """Match the mouse pointer to the active clip toolbar tool."""
        if self._panning:
            cursor = QCursor(Qt.ClosedHandCursor)
        elif self._interaction == self.INTERACT_PAN:
            cursor = QCursor(Qt.OpenHandCursor)
        elif self._interaction == self.INTERACT_ZOOM_IN:
            cursor = self._theme_cursor("ZoomIn")
        elif self._interaction == self.INTERACT_ZOOM_OUT:
            cursor = self._theme_cursor("ZoomOut")
        elif self._interaction == self.INTERACT_DRAW:
            cursor = self._theme_cursor("CrossHair")
        else:
            cursor = QCursor(Qt.ArrowCursor)
        self._apply_cursor(cursor)

    def _apply_cursor(self, cursor: QCursor) -> None:
        self.setCursor(cursor)
        # QgsMapCanvas sometimes keeps a stale cursor; force it while we own the tool.
        try:
            if self._canvas is not None and self._canvas.mapTool() is self:
                self._canvas.setCursor(cursor)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _theme_cursor(name: str) -> QCursor:
        """Prefer QGIS themed cursors (ZoomIn / ZoomOut / CrossHair)."""
        try:
            from qgis.core import QgsApplication

            cursor_enum = getattr(QgsApplication, name, None)
            if cursor_enum is not None:
                cursor = QgsApplication.getThemeCursor(cursor_enum)
                if cursor is not None:
                    return cursor
        except Exception:  # noqa: BLE001
            pass
        if name == "ZoomIn":
            return BBoxMapTool._zoom_cursor(zoom_in=True)
        if name == "ZoomOut":
            return BBoxMapTool._zoom_cursor(zoom_in=False)
        return QCursor(Qt.CrossCursor)

    @staticmethod
    def _zoom_cursor(*, zoom_in: bool) -> QCursor:
        """Build a simple + / − magnifier cursor if QGIS theme cursor is unavailable."""
        try:
            from qgis.PyQt.QtGui import QPixmap, QPainter, QPen, QFont

            size = 32
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(26, 29, 35))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawEllipse(4, 4, 18, 18)
            painter.drawLine(18, 18, 27, 27)
            painter.setFont(QFont("Sans Serif", 11, QFont.Bold))
            painter.drawText(
                4, 4, 18, 18, int(Qt.AlignCenter), "+" if zoom_in else "−"
            )
            painter.end()
            return QCursor(pixmap, 10, 10)
        except Exception:  # noqa: BLE001
            return QCursor(Qt.CrossCursor)

    def _set_rect(self, start: QgsPointXY, end: QgsPointXY) -> None:
        self._rubber.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber.addPoint(QgsPointXY(start.x(), start.y()), False)
        self._rubber.addPoint(QgsPointXY(end.x(), start.y()), False)
        self._rubber.addPoint(QgsPointXY(end.x(), end.y()), False)
        self._rubber.addPoint(QgsPointXY(start.x(), end.y()), True)
