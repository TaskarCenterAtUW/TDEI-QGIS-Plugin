# -*- coding: utf-8 -*-
"""Floating routability toolbar (same look as the clip toolbar)."""

from __future__ import annotations

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..a11y import keyboard_focus, set_name
from ..components import PrimaryButton, SecondaryButton, tinted_icon
from ..styles import colors, dimensions
from .bbox_confirm_bar import BBoxConfirmBar, _theme_or_tinted

_HINTS = {
    "start": "Start edge — click an edge (line) on the map.",
    "dest": "Destination — click anywhere; it snaps to the nearest edge.",
    "pan": "Pan — drag to move the map.",
    "zoom_in": "Zoom in — click the map to zoom in.",
    "zoom_out": "Zoom out — click the map to zoom out.",
}


class RouteBar(QFrame):
    """Shown over the map while the routability tool is active."""

    tool_changed = pyqtSignal(str)  # start | dest | pan | zoom_in | zoom_out
    clear_requested = pyqtSignal()
    done = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Reuse the clip toolbar stylesheet selectors.
        self.setObjectName("BBoxConfirmBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setFocusPolicy(Qt.StrongFocus)
        set_name(
            self,
            self.tr("Routability"),
            self.tr("Pick a start edge and a destination to draw a route."),
        )
        self.setStyleSheet(BBoxConfirmBar._stylesheet())
        self._syncing = False

        icon_px = dimensions.s(18)
        icons = {
            "start": tinted_icon("tool_route_start.svg", colors.TEXT, size=icon_px),
            "dest": tinted_icon("tool_route_dest.svg", colors.TEXT, size=icon_px),
            "zoom_out": _theme_or_tinted(
                ["/mActionZoomOut.svg"], "tool_zoom_out.svg", colors.TEXT, icon_px
            ),
            "zoom_in": _theme_or_tinted(
                ["/mActionZoomIn.svg"], "tool_zoom_in.svg", colors.TEXT, icon_px
            ),
            "pan": _theme_or_tinted(
                ["/mActionPan.svg"], "tool_pan.svg", colors.TEXT, icon_px
            ),
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        eyebrow = QLabel(self.tr("ROUTABILITY"))
        eyebrow.setObjectName("BBoxBarEyebrow")
        eyebrow.setFocusPolicy(Qt.NoFocus)

        self._title = QLabel(self.tr("Edges"))
        self._title.setObjectName("BBoxBarTitle")
        self._title.setWordWrap(True)
        self._title.setFocusPolicy(Qt.NoFocus)

        self._hint = QLabel(self.tr(_HINTS["start"]))
        self._hint.setObjectName("BBoxBarHint")
        self._hint.setWordWrap(True)
        self._hint.setFocusPolicy(Qt.NoFocus)

        tool_host = QFrame()
        tool_host.setObjectName("BBoxToolStrip")
        strip = QHBoxLayout(tool_host)
        strip.setContentsMargins(6, 6, 6, 6)
        strip.setSpacing(4)

        self._buttons = {}
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        tool_defs = (
            ("start", self.tr("Pick start edge"),
             self.tr("Click an edge on the map to start the route.")),
            ("dest", self.tr("Pick destination"),
             self.tr("Click the map to set the destination.")),
            ("zoom_out", self.tr("Zoom out"), self.tr("Click the map to zoom out.")),
            ("zoom_in", self.tr("Zoom in"), self.tr("Click the map to zoom in.")),
            ("pan", self.tr("Pan map"), self.tr("Drag the map to pan.")),
        )
        for key, name, desc in tool_defs:
            btn = self._tool_button(icons[key], name, desc)
            self._buttons[key] = btn
            self._mode_group.addButton(btn)
            strip.addWidget(btn)
        strip.addStretch(1)
        self._mode_group.buttonToggled.connect(self._on_tool_toggled)

        self._result = QLabel("")
        self._result.setObjectName("BBoxBarCoords")
        self._result.setWordWrap(True)
        self._result.setFocusPolicy(Qt.NoFocus)
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._result.setVisible(False)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        clear = SecondaryButton(self.tr("Clear"))
        clear.setAccessibleDescription(
            self.tr("Remove the start, destination and route, and start over.")
        )
        clear.clicked.connect(self.clear_requested.emit)
        finish = PrimaryButton(self.tr("Done"))
        finish.setAccessibleDescription(
            self.tr("Close the routability tool. The route layer stays on the map.")
        )
        finish.clicked.connect(self.done.emit)
        actions.addWidget(clear)
        actions.addStretch(1)
        actions.addWidget(finish)

        root.addWidget(eyebrow)
        root.addWidget(self._title)
        root.addWidget(self._hint)
        root.addWidget(tool_host)
        root.addWidget(self._result)
        root.addLayout(actions)

        self.setMinimumWidth(dimensions.s(400))
        self.setMaximumWidth(dimensions.s(480))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.set_tool("start")

    def _tool_button(self, icon: QIcon, name: str, description: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("BBoxToolButton")
        button.setIcon(icon)
        button.setIconSize(QSize(dimensions.s(18), dimensions.s(18)))
        button.setCheckable(True)
        button.setAutoExclusive(False)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(dimensions.s(36), dimensions.s(36))
        button.setToolTip(name)
        keyboard_focus(button)
        set_name(button, name, description)
        return button

    def set_title(self, text: str) -> None:
        self._title.setText(text)
        self._title.setToolTip(text)

    def set_tool(self, mode: str) -> None:
        """Update the checked tool without re-emitting tool_changed."""
        if mode not in self._buttons:
            mode = "start"
        self._syncing = True
        for key, btn in self._buttons.items():
            btn.setChecked(key == mode)
        self._syncing = False
        self._hint.setText(self.tr(_HINTS.get(mode, _HINTS["start"])))

    def set_result(self, text: str) -> None:
        self._result.setText(text)
        self._result.setVisible(bool(text))
        self.adjustSize()

    def _on_tool_toggled(self, button, checked: bool) -> None:
        if self._syncing or not checked:
            return
        for key, btn in self._buttons.items():
            if btn is button:
                self._hint.setText(self.tr(_HINTS.get(key, _HINTS["start"])))
                self.tool_changed.emit(key)
                return

    def position_on_canvas(self, canvas: QWidget) -> None:
        if canvas is None:
            return
        self.adjustSize()
        top_left = canvas.mapToGlobal(canvas.rect().topLeft())
        self.move(top_left.x() + 16, top_left.y() + 16)
        self.raise_()
        self.show()
