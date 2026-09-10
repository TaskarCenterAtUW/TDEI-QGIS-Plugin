# -*- coding: utf-8 -*-
"""Sticky map-canvas chrome: TDEI / Map search / Close."""

from __future__ import annotations

import os

from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from ..a11y import keyboard_focus, set_name
from ..components import tinted_icon
from ..styles import colors, dimensions
from .map_overlay import apply_glass_frame, pointer_over_overlay


class MapChromeBar(QFrame):
    """Top-right overlay: show/hide TDEI, toggle map search, close plugin UI."""

    tdei_clicked = pyqtSignal()
    map_search_clicked = pyqtSignal()
    close_clicked = pyqtSignal()

    def __init__(self, parent=None, *, plugin_icon_path: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("MapChromeBar")
        apply_glass_frame(self)
        self.setWindowFlags(Qt.Widget)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        set_name(
            self,
            self.tr("TDEI map controls"),
            self.tr("Show or hide TDEI, toggle map search, or close the plugin. "
                    "TDEI and map search are mutually exclusive."),
        )
        self._canvas = None
        self._map_canvas_ref = None
        self.setStyleSheet(self._stylesheet())

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)

        self._tdei = self._make_button(
            object_name="MapChromeTdei",
            label=self.tr("TDEI"),
            description=self.tr("Show or hide the TDEI panel on the map."),
            checkable=True,
            slot=self.tdei_clicked.emit,
        )
        self._paint_tdei_icon(plugin_icon_path)

        self._search = self._make_button(
            object_name="MapChromeSearch",
            label=self.tr("Map search"),
            description=self.tr("Turn map dataset search on or off."),
            checkable=True,
            slot=self.map_search_clicked.emit,
            icon_name="action_map.svg",
        )

        self._close = self._make_button(
            object_name="MapChromeClose",
            label=self.tr("Close"),
            description=self.tr("Close the TDEI plugin UI."),
            checkable=False,
            slot=self.close_clicked.emit,
            icon_name="action_close.svg",
            color=colors.ERROR,
        )
        self._paint_close_button(self._close)

        row.addWidget(self._tdei)
        row.addWidget(self._search)
        row.addWidget(self._close)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.adjustSize()

    def set_tdei_visible(self, visible: bool) -> None:
        self._tdei.blockSignals(True)
        self._tdei.setChecked(bool(visible))
        self._tdei.blockSignals(False)

    def set_map_search_active(self, active: bool) -> None:
        self._search.blockSignals(True)
        self._search.setChecked(bool(active))
        self._search.blockSignals(False)
        # Always brand-purple; stronger when active.
        self._paint_mode_button(
            self._search,
            active=bool(active),
            icon_name="action_map.svg",
            color=colors.PRIMARY if active else colors.PRIMARY_LIGHT,
        )

    def position_on_canvas(self, canvas: QWidget) -> None:
        if canvas is None:
            return
        host = canvas
        try:
            viewport = canvas.viewport()
            if viewport is not None:
                host = viewport
        except Exception:  # noqa: BLE001
            host = canvas
        self._map_canvas_ref = canvas
        if self._canvas is not host:
            if self._canvas is not None:
                try:
                    self._canvas.removeEventFilter(self)
                except Exception:  # noqa: BLE001
                    pass
            self._canvas = host
            if self.parent() is not host:
                self.setParent(host)
            host.installEventFilter(self)
        self._reposition()
        self.raise_()
        self.show()

    def _reposition(self) -> None:
        self.adjustSize()
        host = self._canvas or self.parentWidget()
        if host is None:
            return
        margin = dimensions.s(16)
        x = max(margin, host.width() - self.width() - margin)
        self.move(x, margin)

    def enterEvent(self, event) -> None:
        pointer_over_overlay(
            self, entering=True, map_canvas=self._map_canvas_ref
        )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        pointer_over_overlay(
            self, entering=False, map_canvas=self._map_canvas_ref
        )
        super().leaveEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._canvas and event is not None:
            etype = event.type()
            if etype in (QEvent.Resize, QEvent.Show, QEvent.Move):
                self._reposition()
                self.raise_()
        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:
        # Do not tear down canvas hooks here — setParent()/hide cycles fire
        # hideEvent and would drop the event filter mid-session.
        super().hideEvent(event)

    def detach_from_canvas(self) -> None:
        if self._canvas is not None:
            try:
                self._canvas.removeEventFilter(self)
            except Exception:  # noqa: BLE001
                pass
            self._canvas = None
        self._map_canvas_ref = None

    def _make_button(
        self,
        *,
        object_name: str,
        label: str,
        description: str,
        checkable: bool,
        slot,
        icon_name: str = "",
        color: str = "",
    ) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName(object_name)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.StrongFocus)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setCheckable(bool(checkable))
        size = dimensions.s(34)
        icon_px = dimensions.s(18)
        btn.setFixedSize(size, size)
        btn.setIconSize(QSize(icon_px, icon_px))
        if icon_name:
            btn.setProperty("tdei_icon", icon_name)
            # Map search stays in TDEI purple; close keeps error red.
            paint_color = color or None
            if object_name == "MapChromeSearch" and not paint_color:
                paint_color = colors.PRIMARY_LIGHT
            self._paint_mode_button(
                btn,
                active=False,
                icon_name=icon_name,
                color=paint_color,
            )
        keyboard_focus(btn)
        set_name(btn, label, description)
        btn.setToolTip(description)
        btn.clicked.connect(slot)
        return btn

    def _paint_tdei_icon(self, plugin_icon_path: str) -> None:
        path = (plugin_icon_path or "").strip()
        icon_px = dimensions.s(18)
        if path and os.path.isfile(path):
            self._tdei.setIcon(QIcon(path))
        else:
            self._tdei.setIcon(
                tinted_icon(
                    "nav_dashboard.svg",
                    colors.PRIMARY,
                    size=icon_px,
                    dpr=dimensions.device_pixel_ratio(self._tdei),
                )
            )
        self._tdei.setIconSize(QSize(icon_px, icon_px))
        self._tdei.setProperty("tdei_icon", "")

    def _paint_mode_button(
        self,
        btn: QToolButton,
        *,
        active: bool,
        icon_name: str = "",
        color=None,
    ) -> None:
        name = icon_name or str(btn.property("tdei_icon") or "").strip()
        if not name:
            return
        icon_px = dimensions.s(18)
        if color is None:
            color = colors.PRIMARY if active else colors.TEXT_SECONDARY
        btn.setIcon(
            tinted_icon(
                name,
                color,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(icon_px, icon_px))

    def _paint_close_button(self, btn: QToolButton) -> None:
        """Solid chip + bold red X so close stays visible on glass panels."""
        icon_px = dimensions.s(16)
        btn.setIcon(
            tinted_icon(
                "action_close.svg",
                colors.ERROR,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(icon_px, icon_px))
        size = dimensions.s(34)
        btn.setFixedSize(size, size)
        btn.setAutoRaise(False)
        btn.setVisible(True)

    @staticmethod
    def _stylesheet() -> str:
        return """
            QFrame#MapChromeBar {{
                background-color: {glass};
                border: 1px solid {glass_border};
                border-radius: {radius}px;
            }}
            QToolButton#MapChromeTdei,
            QToolButton#MapChromeSearch {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: {radius_sm}px;
                padding: 2px;
            }}
            QToolButton#MapChromeClose {{
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(198, 40, 40, 0.45);
                border-radius: {radius_sm}px;
                padding: 2px;
            }}
            QToolButton#MapChromeTdei:hover,
            QToolButton#MapChromeSearch:hover {{
                background-color: rgba(50, 0, 110, 0.10);
            }}
            QToolButton#MapChromeClose:hover {{
                background-color: rgba(198, 40, 40, 0.16);
                border-color: {error};
            }}
            QToolButton#MapChromeClose:pressed {{
                background-color: rgba(198, 40, 40, 0.24);
            }}
            QToolButton#MapChromeTdei:checked,
            QToolButton#MapChromeSearch:checked {{
                background-color: rgba(50, 0, 110, 0.14);
                border: 1px solid {accent};
            }}
        """.format(
            glass=colors.GLASS_SURFACE,
            glass_border=colors.GLASS_BORDER_EDGE,
            accent=colors.PRIMARY,
            error=colors.ERROR,
            radius=dimensions.RADIUS_LG,
            radius_sm=dimensions.RADIUS_SM,
        )
