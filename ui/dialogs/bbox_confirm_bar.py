# -*- coding: utf-8 -*-
"""Floating clip toolbar — theme-aligned exclusive map tools."""

from __future__ import annotations

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
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
from ..styles import colors, dimensions, typography


def _theme_or_tinted(qgis_names, fallback_svg: str, color: str, size: int) -> QIcon:
    try:
        from qgis.core import QgsApplication

        for name in qgis_names:
            icon = QgsApplication.getThemeIcon(name)
            if icon is not None and not icon.isNull():
                return icon
    except Exception:  # noqa: BLE001
        pass
    return tinted_icon(fallback_svg, color, size=size)


def _format_bbox_display(bbox_csv: str) -> str:
    """Short W,S,E,N for the bar (full precision kept for the API)."""
    try:
        parts = [float(p.strip()) for p in bbox_csv.split(",")]
        if len(parts) != 4:
            return bbox_csv
        return "{:.5f}, {:.5f}, {:.5f}, {:.5f}".format(*parts)
    except Exception:  # noqa: BLE001
        return bbox_csv


_HINTS = {
    "draw": "Draw — drag on the map to set the clip rectangle.",
    "pan": "Pan — drag to move the map.",
    "zoom_in": "Zoom in — click the map to zoom in.",
    "zoom_out": "Zoom out — click the map to zoom out.",
}


class BBoxConfirmBar(QFrame):
    """Shown over the map while clipping (draw + confirm)."""

    cancelled = pyqtSignal()
    confirmed = pyqtSignal(str)
    redraw_requested = pyqtSignal()
    tool_changed = pyqtSignal(str)  # draw | pan | zoom_in | zoom_out

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BBoxConfirmBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setFocusPolicy(Qt.StrongFocus)
        set_name(
            self,
            self.tr("Clip bounding box"),
            self.tr(
                "Draw or confirm a clip area using the toolbar tools."
            ),
        )
        self.setStyleSheet(self._stylesheet())
        self._confirming = False
        self._syncing = False

        icon_px = dimensions.s(18)
        # Clip uses our crop glyph (QGIS SelectExtent looks like zoom-to-area).
        icons = {
            "draw": tinted_icon("tool_clip.svg", colors.TEXT, size=icon_px),
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

        self._eyebrow = QLabel(self.tr("CLIP DATASET"))
        self._eyebrow.setObjectName("BBoxBarEyebrow")
        self._eyebrow.setFocusPolicy(Qt.NoFocus)

        self._title = QLabel(self.tr("Dataset"))
        self._title.setObjectName("BBoxBarTitle")
        self._title.setWordWrap(True)
        self._title.setFocusPolicy(Qt.NoFocus)

        self._hint = QLabel(self.tr(_HINTS["draw"]))
        self._hint.setObjectName("BBoxBarHint")
        self._hint.setWordWrap(True)
        self._hint.setFocusPolicy(Qt.NoFocus)

        self._tool_host = QFrame()
        self._tool_host.setObjectName("BBoxToolStrip")
        strip = QHBoxLayout(self._tool_host)
        strip.setContentsMargins(6, 6, 6, 6)
        strip.setSpacing(4)

        self._buttons = {}
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        tool_defs = (
            ("draw", icons["draw"], self.tr("Crop / clip"),
             self.tr("Drag a rectangle to clip. Re-select after zoom or pan.")),
            ("zoom_out", icons["zoom_out"], self.tr("Zoom out"),
             self.tr("Click the map to zoom out.")),
            ("zoom_in", icons["zoom_in"], self.tr("Zoom in"),
             self.tr("Click the map to zoom in.")),
            ("pan", icons["pan"], self.tr("Pan map"),
             self.tr("Drag the map to pan.")),
        )
        for key, icon, name, desc in tool_defs:
            btn = self._tool_button(icon, name, desc)
            self._buttons[key] = btn
            self._mode_group.addButton(btn)
            strip.addWidget(btn)

        self._mode_group.buttonToggled.connect(self._on_tool_toggled)

        self._coords = QLabel("")
        self._coords.setObjectName("BBoxBarCoords")
        self._coords.setWordWrap(True)
        self._coords.setFocusPolicy(Qt.NoFocus)
        self._coords.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._fmt_host = QWidget()
        fmt_row = QHBoxLayout(self._fmt_host)
        fmt_row.setContentsMargins(0, 0, 0, 0)
        fmt_row.setSpacing(10)
        fmt_label = QLabel(self.tr("Output"))
        fmt_label.setObjectName("BBoxBarLabel")
        self._file_type = QComboBox()
        self._file_type.setObjectName("BBoxCombo")
        self._file_type.addItem("OSW", "osw")
        self._file_type.addItem("OSM", "osm")
        self._file_type.setMinimumHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
        keyboard_focus(self._file_type)
        set_name(
            self._file_type,
            self.tr("Output format"),
            self.tr("Choose OSW or OSM for the clipped subgraph."),
        )
        fmt_row.addWidget(fmt_label)
        fmt_row.addWidget(self._file_type, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._redraw = SecondaryButton(self.tr("Redraw"))
        self._redraw.setAccessibleDescription(
            self.tr("Discard this rectangle and draw again.")
        )
        self._redraw.clicked.connect(self._on_redraw_clicked)
        self._cancel = SecondaryButton(self.tr("Cancel"))
        self._cancel.setAccessibleDescription(
            self.tr("Cancel clipping and return to the plugin.")
        )
        self._cancel.clicked.connect(self.cancelled.emit)
        self._run = PrimaryButton(self.tr("Run clip"))
        self._run.setDefault(True)
        self._run.setAutoDefault(True)
        self._run.setAccessibleDescription(
            self.tr("Submit the dataset-bbox job with this rectangle.")
        )
        self._run.clicked.connect(self._on_run)
        actions.addWidget(self._redraw)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._run)

        root.addWidget(self._eyebrow)
        root.addWidget(self._title)
        root.addWidget(self._hint)
        root.addWidget(self._tool_host)
        root.addWidget(self._coords)
        root.addWidget(self._fmt_host)
        root.addLayout(actions)

        self.setMinimumWidth(dimensions.s(400))
        self.setMaximumWidth(dimensions.s(480))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.set_tool("draw")
        self.set_drawing_mode(True)

    def _tool_button(self, icon: QIcon, name: str, description: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("BBoxToolButton")
        button.setIcon(icon)
        button.setIconSize(QSize(dimensions.s(18), dimensions.s(18)))
        button.setCheckable(True)
        button.setAutoExclusive(False)  # group owns exclusivity
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(dimensions.s(36), dimensions.s(36))
        button.setToolTip(name)
        keyboard_focus(button)
        set_name(button, name, description)
        return button

    def set_drawing_mode(self, drawing: bool) -> None:
        self._confirming = not drawing
        self._coords.setVisible(not drawing)
        self._fmt_host.setVisible(not drawing)
        self._redraw.setVisible(not drawing)
        self._run.setVisible(not drawing)
        if drawing:
            self._coords.clear()

    def set_tool(self, mode: str) -> None:
        """Update checked tool without re-emitting tool_changed."""
        if mode not in self._buttons:
            mode = "draw"
        self._syncing = True
        for key, btn in self._buttons.items():
            btn.setChecked(key == mode)
        self._syncing = False
        self._hint.setText(self.tr(_HINTS.get(mode, _HINTS["draw"])))

    def set_interaction_mode(self, mode: str) -> None:
        self.set_tool(mode)

    def set_pan_checked(self, checked: bool) -> None:
        self.set_tool("pan" if checked else "draw")

    def set_context(self, dataset_name: str, bbox_csv: str = "") -> None:
        name = dataset_name or self.tr("Dataset")
        self._title.setText(name)
        self._title.setToolTip(name)
        if bbox_csv:
            self.set_drawing_mode(False)
            display = _format_bbox_display(bbox_csv)
            self._coords.setText(
                self.tr("Bounding box (W, S, E, N)\n{}").format(display)
            )
            self._coords.setAccessibleDescription(bbox_csv)
            self.set_tool("pan")
        else:
            self.set_drawing_mode(True)
            self._coords.setAccessibleDescription("")
            self.set_tool("draw")

    def _on_tool_toggled(self, button, checked: bool) -> None:
        if self._syncing or not checked:
            return
        mode = "draw"
        for key, btn in self._buttons.items():
            if btn is button:
                mode = key
                break
        self._hint.setText(self.tr(_HINTS.get(mode, _HINTS["draw"])))
        self.tool_changed.emit(mode)

    def _on_redraw_clicked(self) -> None:
        self.set_tool("draw")
        self.redraw_requested.emit()

    def _on_run(self) -> None:
        data = self._file_type.currentData()
        self.confirmed.emit(str(data or "osw"))

    def position_on_canvas(self, canvas: QWidget) -> None:
        if canvas is None:
            return
        self.adjustSize()
        top_left = canvas.mapToGlobal(canvas.rect().topLeft())
        self.move(top_left.x() + 16, top_left.y() + 16)
        self.raise_()
        self.show()

    @staticmethod
    def _stylesheet() -> str:
        # Floating Tool window does not inherit the main plugin stylesheet.
        return """
            QFrame#BBoxConfirmBar {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: {radius_lg}px;
            }}
            QLabel#BBoxBarEyebrow {{
                color: {primary};
                font-size: {fs_xs}px;
                font-weight: {fw_semi};
                letter-spacing: 0.06em;
            }}
            QLabel#BBoxBarTitle {{
                color: {text};
                font-size: {fs_md}px;
                font-weight: {fw_semi};
            }}
            QLabel#BBoxBarHint {{
                color: {muted};
                font-size: {fs_sm}px;
            }}
            QLabel#BBoxBarCoords {{
                color: {secondary};
                font-size: {fs_sm}px;
                font-family: Menlo, Monaco, monospace;
                padding: 8px 10px;
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QLabel#BBoxBarLabel {{
                color: {muted};
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
            }}
            QFrame#BBoxToolStrip {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QToolButton#BBoxToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {radius_sm}px;
                padding: 0;
                margin: 0;
            }}
            QToolButton#BBoxToolButton:hover {{
                background-color: {surface};
                border-color: {border};
            }}
            QToolButton#BBoxToolButton:checked {{
                background-color: {surface};
                border: 2px solid {primary};
            }}
            QToolButton#BBoxToolButton:focus {{
                border: 2px solid {primary};
            }}
            QComboBox#BBoxCombo {{
                min-height: {ctrl}px;
                padding: 4px 10px;
                background-color: {surface};
                color: {text};
                border: 1px solid {border_strong};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
            }}
            QComboBox#BBoxCombo:focus {{
                border: 2px solid {primary};
            }}
            QComboBox#BBoxCombo::drop-down {{
                border: none;
                width: 24px;
            }}
            QPushButton#PrimaryButton {{
                min-height: {ctrl}px;
                max-height: {ctrl}px;
                padding: 4px 16px;
                color: {on_primary};
                background-color: {primary};
                border: 1px solid {primary};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {primary_hover};
                border-color: {primary_hover};
            }}
            QPushButton#PrimaryButton:focus {{
                border: 2px solid {primary_light};
            }}
            QPushButton#SecondaryButton {{
                min-height: {ctrl}px;
                max-height: {ctrl}px;
                padding: 4px 14px;
                color: {primary};
                background-color: {surface};
                border: 1px solid {border_strong};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
                font-weight: {fw_medium};
            }}
            QPushButton#SecondaryButton:hover {{
                background-color: {surface_alt};
                border-color: {primary};
            }}
            QPushButton#SecondaryButton:focus {{
                border: 2px solid {primary};
            }}
        """.format(
            surface=colors.SURFACE,
            surface_alt=colors.SURFACE_ALT,
            bg=colors.BACKGROUND,
            border=colors.BORDER,
            border_strong=colors.BORDER_STRONG,
            radius=dimensions.RADIUS_MD,
            radius_sm=dimensions.RADIUS_SM,
            radius_lg=dimensions.RADIUS_LG,
            text=colors.TEXT,
            secondary=colors.TEXT_SECONDARY,
            muted=colors.TEXT_MUTED,
            primary=colors.PRIMARY,
            primary_hover=colors.PRIMARY_HOVER,
            primary_light=colors.PRIMARY_LIGHT,
            on_primary=colors.TEXT_ON_PRIMARY,
            ctrl=dimensions.s(dimensions.CONTROL_HEIGHT),
            fs_xs=typography.FONT_SIZE_XS,
            fs_sm=typography.FONT_SIZE_SM,
            fs_md=typography.FONT_SIZE_MD,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
            fw_medium=getattr(typography, "FONT_WEIGHT_MEDIUM", 500),
        )
