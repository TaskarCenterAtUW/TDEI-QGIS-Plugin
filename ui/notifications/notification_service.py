# -*- coding: utf-8 -*-
"""Toast + QGIS message-bar notification service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QEvent, QObject, QTimer, Qt
from qgis.PyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.compatibility import qgis_compat
from ..styles import colors, dimensions, typography

if TYPE_CHECKING:
    from qgis.gui import QgsInterface
    from ...config.settings import SettingsManager

# Soft surfaces + accent + readable text (never rely on inherited QFrame color)
_TOAST_THEME: Dict[str, Tuple[str, str, str, str]] = {
    # level: (background, border/accent, text, marker)
    "info": (colors.SURFACE, colors.PRIMARY, colors.TEXT, "ℹ"),
    "success": ("#e8f5e9", colors.SUCCESS, "#0f5132", "✓"),
    "warning": ("#fff8e6", "#e0a800", "#664d03", "!"),
    "error": ("#fdecea", colors.ERROR, "#7f1d1d", "✕"),
}

_TOAST_WIDTH = 360
_TOAST_MAX_VISIBLE = 4
_MARKER_SIZE = 28
_CLOSE_SIZE = 28
_H_MARGIN = 14
_H_SPACING = 10


class Toast(QFrame):
    """Elevated toast sized to its message (word-wrap aware)."""

    def __init__(self, message: str, level: str = "info", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

        level = level if level in _TOAST_THEME else "info"
        bg, accent, text, marker = _TOAST_THEME[level]

        self.setStyleSheet(
            """
            QFrame#Toast {{
                background-color: {bg};
                border: 1px solid {border};
                border-left: 4px solid {accent};
                border-radius: {radius}px;
            }}
            """.format(
                bg=bg,
                border=colors.BORDER,
                accent=accent,
                radius=dimensions.RADIUS_MD,
            )
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_H_MARGIN, 12, 10, 12)
        layout.setSpacing(_H_SPACING)

        mark = QLabel(marker)
        mark.setObjectName("ToastMarker")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(_MARKER_SIZE, _MARKER_SIZE)
        mark.setStyleSheet(
            "color: {0}; font-size: 15px; font-weight: 700; background: transparent; "
            "border: none; padding: 0; margin: 0;".format(accent)
        )

        self._label = QLabel(message)
        self._label.setObjectName("ToastMessage")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._label.setStyleSheet(
            "color: {0}; font-size: {1}px; font-weight: {2}; background: transparent; "
            "border: none; padding: 0; margin: 0;".format(
                text,
                typography.FONT_SIZE_MD,
                typography.FONT_WEIGHT_MEDIUM,
            )
        )

        close = QPushButton("×")
        close.setObjectName("ToastClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setFlat(True)
        close.setFixedSize(_CLOSE_SIZE, _CLOSE_SIZE)
        close.setToolTip("Dismiss")
        close.setStyleSheet(
            """
            QPushButton#ToastClose {{
                color: {muted};
                background: transparent;
                border: none;
                font-size: 18px;
                font-weight: 600;
                padding: 0;
                margin: 0;
            }}
            QPushButton#ToastClose:hover {{
                color: {text};
                background-color: rgba(0, 0, 0, 0.06);
                border-radius: 4px;
            }}
            """.format(
                muted=colors.TEXT_MUTED, text=colors.TEXT
            )
        )
        close.clicked.connect(self._close)

        # Top-align chrome so multi-line text is never vertically clipped.
        layout.addWidget(mark, 0, Qt.AlignTop)
        layout.addWidget(self._label, 1)
        layout.addWidget(close, 0, Qt.AlignTop)

        self.apply_width(_TOAST_WIDTH)

    def apply_width(self, width: int) -> None:
        """Constrain width so word-wrap height is computed correctly."""
        width = max(240, int(width))
        self.setFixedWidth(width)
        label_width = (
            width
            - layout_h_chrome()
        )
        self._label.setMinimumWidth(label_width)
        self._label.setMaximumWidth(label_width)
        # Force QLabel to recompute height-for-width before the host stacks us.
        self._label.adjustSize()
        needed = self.sizeHint().height()
        self.setMinimumHeight(needed)
        self.setMaximumHeight(16777215)
        self.resize(width, needed)

    def _close(self) -> None:
        self.hide()
        self.deleteLater()


def layout_h_chrome() -> int:
    """Horizontal space used by margins, marker, close, and spacings."""
    return (
        _H_MARGIN
        + 10  # right margin
        + _MARKER_SIZE
        + _CLOSE_SIZE
        + (2 * _H_SPACING)
    )


class ToastHost(QWidget):
    """Stacks toasts in the top-right, below the app header.

    Sized to toast content only — never a full-height overlay that would
    steal clicks from the Datasets Actions column.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastHost")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#ToastHost { background: transparent; }")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._toasts_box = QVBoxLayout()
        self._toasts_box.setContentsMargins(0, 0, 0, 0)
        self._toasts_box.setSpacing(8)
        self._layout.addLayout(self._toasts_box)
        self.setFixedWidth(_TOAST_WIDTH)
        self.hide()

    def show_toast(self, message: str, level: str, duration_ms: int) -> None:
        self._prune_closed()
        while self._visible_count() >= _TOAST_MAX_VISIBLE:
            oldest = self._oldest_toast()
            if oldest is None:
                break
            oldest._close()
            self._prune_closed()

        toast = Toast(message, level=level, parent=self)
        toast.apply_width(self.width())
        # Newest on top so rapid bursts stack downward without covering each other.
        self._toasts_box.insertWidget(0, toast)
        toast.destroyed.connect(self._on_toast_gone)
        self._reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(max(duration_ms, 1500), toast._close)

    def _visible_count(self) -> int:
        count = 0
        for i in range(self._toasts_box.count()):
            item = self._toasts_box.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None and widget.isVisible():
                count += 1
        return count

    def _oldest_toast(self) -> Optional[Toast]:
        # Newest inserted at 0 → oldest is the last widget.
        for i in range(self._toasts_box.count() - 1, -1, -1):
            item = self._toasts_box.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, Toast):
                return widget
        return None

    def _prune_closed(self) -> None:
        for i in range(self._toasts_box.count() - 1, -1, -1):
            item = self._toasts_box.itemAt(i)
            widget = item.widget() if item else None
            if widget is None:
                self._toasts_box.takeAt(i)

    def _on_toast_gone(self, *_args) -> None:
        QTimer.singleShot(0, self._reposition)

    def _content_height(self) -> int:
        spacing = self._toasts_box.spacing()
        total = 0
        visible = 0
        for i in range(self._toasts_box.count()):
            item = self._toasts_box.itemAt(i)
            widget = item.widget() if item else None
            if widget is None or not widget.isVisible():
                continue
            if isinstance(widget, Toast):
                widget.apply_width(self.width())
            total += max(widget.height(), widget.sizeHint().height())
            visible += 1
        if visible > 1:
            total += spacing * (visible - 1)
        return total

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self._prune_closed()
        if self._visible_count() == 0:
            self.hide()
            self.resize(self.width(), 1)
            return

        height = max(48, self._content_height())
        # Cap so a flood of toasts cannot cover the whole window.
        max_h = max(120, parent.height() - dimensions.HEADER_HEIGHT - 24)
        height = min(height, max_h)
        top = dimensions.HEADER_HEIGHT + 12
        self.setFixedHeight(height)
        self.move(parent.width() - self.width() - 16, top)
        self.show()
        self.raise_()


class NotificationService(QObject):
    def __init__(
        self,
        iface: "QgsInterface",
        settings: "SettingsManager",
    ) -> None:
        super().__init__()
        self._iface = iface
        self._settings = settings
        self._host: Optional[ToastHost] = None
        self._history: List[str] = []

    def attach_host(self, window: QWidget) -> None:
        self._host = ToastHost(window)
        # Keep host above content when the window resizes
        window.installEventFilter(self)

    def eventFilter(self, obj, event):
        if self._host is not None and obj is self._host.parentWidget():
            if event.type() in (QEvent.Resize, QEvent.Show):
                self._host._reposition()
        return super().eventFilter(obj, event)

    def success(self, message: str) -> None:
        self._emit(message, "success", qgis_compat.message_level_success())

    def info(self, message: str) -> None:
        self._emit(message, "info", qgis_compat.message_level_info())

    def warning(self, message: str) -> None:
        self._emit(message, "warning", qgis_compat.message_level_warning())

    def error(self, message: str) -> None:
        self._emit(message, "error", qgis_compat.message_level_critical())

    def _emit(self, message: str, level: str, qgis_level) -> None:
        self._history.append(message)
        if self._settings.bool("ui.show_toasts", True) and self._host is not None:
            duration = self._settings.int("ui.toast_duration_ms", 4000)
            self._host.show_toast(message, level, duration)
        else:
            self._iface.messageBar().pushMessage(
                "TDEI", message, level=qgis_level, duration=6
            )
