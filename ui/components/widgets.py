# -*- coding: utf-8 -*-
"""Reusable UI primitives — no business logic."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyleFactory,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..styles import colors
from ..styles import dimensions
from ..a11y import keyboard_focus

_ICONS = Path(__file__).resolve().parents[1] / "icons"


def icon_path(name: str) -> str:
    return str((_ICONS / name).resolve())


def tinted_pixmap(name: str, color, size: int = 24, dpr: float = 0.0) -> QPixmap:
    """Render and recolor an SVG at an exact logical size (HiDPI-safe)."""
    if not isinstance(color, QColor):
        color = QColor(color)
    if dpr <= 0:
        dpr = dimensions.device_pixel_ratio()
    dpr = max(1.0, float(dpr))
    physical = max(1, int(round(float(size) * dpr)))
    path = icon_path(name)

    painted = QPixmap(physical, physical)
    painted.fill(Qt.transparent)
    painter = QPainter(painted)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    rendered = False
    try:
        from qgis.PyQt.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(path)
        if renderer.isValid():
            # Draw into the full physical rect; DPR is applied on the pixmap.
            renderer.render(painter)
            rendered = True
    except Exception:
        rendered = False

    if not rendered:
        # Logical size only — let Qt apply devicePixelRatio once.
        source = QIcon(path).pixmap(QSize(size, size))
        if not source.isNull():
            painter.drawPixmap(painted.rect(), source)

    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(painted.rect(), color)
    painter.end()
    painted.setDevicePixelRatio(dpr)
    return painted


def tinted_icon(name: str, color, size: int = 24, dpr: float = 0.0) -> QIcon:
    pixmap = tinted_pixmap(name, color, size, dpr=dpr)
    if pixmap.isNull():
        return QIcon()
    icon = QIcon()
    # Register the HiDPI pixmap explicitly so QPushButton/QToolButton do not
    # re-rasterize the SVG at 1x and blur on Retina displays.
    icon.addPixmap(pixmap, QIcon.Normal, QIcon.Off)
    icon.addPixmap(pixmap, QIcon.Active, QIcon.Off)
    icon.addPixmap(pixmap, QIcon.Selected, QIcon.Off)
    icon.addPixmap(pixmap, QIcon.Disabled, QIcon.Off)
    return icon


# Soft pill tones for table status cells (bg, border, text).
_STATUS_TONES = {
    "success": ("#e8f6ee", "#b6dfc6", colors.SUCCESS),
    "danger": ("#fdeeee", "#f0c0c0", colors.ERROR),
    "warning": ("#fff7e6", "#efd39a", colors.WARNING),
    "info": ("#eef4fc", "#b9cef0", colors.INFO),
    "accent": ("#f2ecf9", "#d2c0e8", colors.PRIMARY),
    "neutral": ("#f3f4f7", "#d8dbe3", colors.TEXT_MUTED),
}


def status_badge(
    text: str,
    kind: str = "neutral",
    parent=None,
    *,
    tooltip: str = "",
) -> QWidget:
    """Compact status pill for table cells."""
    host = QWidget(parent)
    host.setObjectName("StatusBadgeHost")
    host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    row = QHBoxLayout(host)
    row.setContentsMargins(4, 6, 4, 6)
    row.setSpacing(0)

    label = (text or "—").strip() or "—"
    badge = QLabel(label)
    badge.setObjectName("StatusBadge")
    badge.setAlignment(Qt.AlignCenter)
    badge.setWordWrap(False)
    badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    badge.setProperty("kind", kind if kind in _STATUS_TONES else "neutral")
    if tooltip:
        badge.setToolTip(tooltip)
        host.setToolTip(tooltip)
    badge.setAccessibleName(label)
    badge.setFocusPolicy(Qt.NoFocus)

    bg, border, fg = _STATUS_TONES.get(kind, _STATUS_TONES["neutral"])
    badge.setStyleSheet(
        "QLabel#StatusBadge {{"
        "  background-color: {bg};"
        "  color: {fg};"
        "  border: 1px solid {border};"
        "  border-radius: 11px;"
        "  padding: 3px 10px;"
        "  font-size: 11px;"
        "  font-weight: 600;"
        "  min-height: 16px;"
        "}}".format(bg=bg, fg=fg, border=border)
    )
    # Pad covers stylesheet horizontal padding + border so the pill never clips.
    pad = 28
    try:
        width = badge.fontMetrics().boundingRect(label).width() + pad
        badge.setFixedWidth(max(width, 48))
    except Exception:
        pass
    row.addStretch(1)
    row.addWidget(badge, 0, Qt.AlignVCenter)
    row.addStretch(1)
    return host


class PrimaryButton(QPushButton):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self)
        if text:
            self.setAccessibleName(text)


class SecondaryButton(QPushButton):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SecondaryButton")
        self.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self)
        if text:
            self.setAccessibleName(text)


class DangerButton(QPushButton):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("DangerButton")
        self.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self)
        if text:
            self.setAccessibleName(text)


class IconButton(QPushButton):
    """Square icon-only control (e.g. refresh)."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        parent=None,
        *,
        size: int = 36,
        icon_size: int = 18,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self)
        self.setFixedSize(size, size)
        self.setIcon(QIcon(icon_path(icon_name)))
        self.setIconSize(QSize(icon_size, icon_size))
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
            self.setAccessibleDescription(tooltip)


def outline_action_button(
    text: str,
    *,
    color: str,
    hover_bg: str = "",
    width: int = 86,
    height: int = 28,
    expand: bool = False,
    icon_name: str = "",
    icon_size: int = 18,
) -> QToolButton:
    """Compact outlined table action button with a crisp HiDPI icon prefix."""
    btn = QToolButton()
    btn.setText(text)
    btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setAutoRaise(False)
    keyboard_focus(btn)
    btn.setAccessibleName(text)
    btn.setFixedHeight(height)
    if icon_name:
        # Same HiDPI path as sidebar / more-menu icons: scale token + DPR pixmap.
        logical = dimensions.s(icon_size)
        dpr = dimensions.device_pixel_ratio(btn)
        btn.setIcon(tinted_icon(icon_name, color, size=logical, dpr=dpr))
        btn.setIconSize(QSize(logical, logical))
    if expand:
        btn.setMinimumWidth(width)
        btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    else:
        btn.setFixedWidth(width)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    btn.setStyleSheet(
        "QToolButton {{ background: {surface}; color: {color}; "
        "border: 1px solid {color}; border-radius: 4px; "
        "padding: 0 8px 0 6px; font-size: 12px; font-weight: 600; "
        "spacing: 6px; }}"
        "QToolButton:hover {{ background: {hover}; }}"
        "QToolButton:focus {{ border: 2px solid {focus}; }}"
        "QToolButton:disabled {{ color: {muted}; border-color: {border}; "
        "background: {surface}; }}"
        "QToolButton::menu-indicator {{ image: none; width: 0; }}".format(
            surface=colors.SURFACE,
            color=color,
            hover=hover_bg or colors.SURFACE_ALT,
            muted=colors.TEXT_MUTED,
            border=colors.BORDER,
            focus=colors.FOCUS,
        )
    )
    return btn


def _style_mapped_checkbox(checkbox: QCheckBox) -> None:
    """Force Fusion + clear indicator so macOS native style does not hide borders."""
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        checkbox.setStyle(fusion)
    checkbox.setFixedSize(20, 20)
    checkbox.setAttribute(Qt.WA_MacShowFocusRect, False)


def centered_checkbox(*, tooltip: str = "", parent=None):
    """Return (host widget, checkbox) with the box centered in the cell."""
    host = QWidget(parent)
    host.setObjectName("CenteredCheckHost")
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.setAlignment(Qt.AlignCenter)
    checkbox = QCheckBox()
    checkbox.setObjectName("MappedTableCheck")
    _style_mapped_checkbox(checkbox)
    checkbox.setCursor(Qt.PointingHandCursor)
    keyboard_focus(checkbox)
    if tooltip:
        checkbox.setToolTip(tooltip)
        checkbox.setAccessibleName(tooltip)
    else:
        checkbox.setAccessibleName("Select row")
    layout.addWidget(checkbox, 0, Qt.AlignCenter)
    return host, checkbox


class CheckHeaderView(QHeaderView):
    """Horizontal header with a centered MappedTableCheck in section 0."""

    check_toggled = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._enabled = True
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._checkbox = QCheckBox(self)
        self._checkbox.setObjectName("MappedTableCheck")
        _style_mapped_checkbox(self._checkbox)
        self._checkbox.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self._checkbox)
        self._checkbox.setToolTip("Select all")
        self._checkbox.setAccessibleName("Select all rows")
        self._checkbox.setAccessibleDescription(
            "Select or clear all mapped items in this table."
        )
        self._checkbox.stateChanged.connect(self._on_checkbox_changed)
        self.sectionResized.connect(lambda *_: self._position_checkbox())
        self.geometriesChanged.connect(self._position_checkbox)

    def set_checked(self, checked: bool) -> None:
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(bool(checked))
        self._checkbox.blockSignals(False)

    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

    def set_check_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._checkbox.setEnabled(self._enabled)
        if not self._enabled:
            self.set_checked(False)
        self._position_checkbox()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_checkbox()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_checkbox()

    def _on_checkbox_changed(self, state: int) -> None:
        self.check_toggled.emit(state == Qt.Checked)

    def _position_checkbox(self) -> None:
        if self.count() <= 0:
            self._checkbox.hide()
            return
        size = 20
        x = self.sectionViewportPosition(0) + (self.sectionSize(0) - size) // 2
        y = (self.height() - size) // 2
        self._checkbox.setGeometry(max(0, x), max(0, y), size, size)
        self._checkbox.show()
        self._checkbox.raise_()

    def mousePressEvent(self, event) -> None:
        if (
            self._enabled
            and event.button() == Qt.LeftButton
            and self.logicalIndexAt(event.pos()) == 0
        ):
            if not self._checkbox.geometry().contains(event.pos()):
                self._checkbox.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.logicalIndexAt(event.pos()) == 0:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LoadingOverlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LoadingOverlay")
        layout = QVBoxLayout(self)
        self._label = QLabel("Loading…")
        self._label.setAlignment(Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(self._label)
        layout.addStretch()
        self.setStyleSheet(
            "background-color: rgba(245, 246, 250, 180); color: {};".format(
                colors.TEXT_MUTED
            )
        )
        self.hide()

    def start(self, message: str = "Loading…") -> None:
        self._label.setText(message)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()

    def stop(self) -> None:
        self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())


class EmptyState(QFrame):
    retry = pyqtSignal()

    def __init__(
        self,
        title: str = "Nothing here yet",
        body: str = "",
        action_text: str = "Refresh",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self.setAccessibleName(title)
        self.setAccessibleDescription(body or title)
        layout = QVBoxLayout(self)
        self._title = QLabel(title)
        self._title.setObjectName("EmptyTitle")
        self._title.setFocusPolicy(Qt.NoFocus)
        self._body = QLabel(body)
        self._body.setObjectName("EmptyBody")
        self._body.setWordWrap(True)
        self._body.setFocusPolicy(Qt.NoFocus)
        self._action = SecondaryButton(action_text)
        self._action.clicked.connect(self.retry.emit)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addWidget(self._action, alignment=Qt.AlignLeft)
        layout.addStretch()

    def set_message(self, title: str, body: str) -> None:
        self._title.setText(title)
        self._body.setText(body)
        self.setAccessibleName(title)
        self.setAccessibleDescription(body or title)

    def set_action_text(self, text: str) -> None:
        self._action.setText(text)
        self._action.setAccessibleName(text)


class ErrorState(QFrame):
    retry = pyqtSignal()

    def __init__(
        self,
        title: str = "Something went wrong",
        body: str = "",
        action_text: str = "Retry",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ErrorState")
        self.setAccessibleName(title)
        self.setAccessibleDescription(body or title)
        layout = QVBoxLayout(self)
        self._title = QLabel(title)
        self._title.setObjectName("ErrorTitle")
        self._title.setFocusPolicy(Qt.NoFocus)
        self._body = QLabel(body)
        self._body.setObjectName("ErrorBody")
        self._body.setWordWrap(True)
        self._body.setFocusPolicy(Qt.NoFocus)
        self._action = PrimaryButton(action_text)
        self._action.clicked.connect(self.retry.emit)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addWidget(self._action, alignment=Qt.AlignLeft)
        layout.addStretch()

    def set_message(self, title: str, body: str) -> None:
        self._title.setText(title)
        self._body.setText(body)
        self.setAccessibleName(title)
        self.setAccessibleDescription(body or title)


class AppHeader(QWidget):
    logout_requested = pyqtSignal()
    sync_requested = pyqtSignal()
    minimize_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AppHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAccessibleName("Application header")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        self._logo = QLabel()
        self._logo.setObjectName("HeaderLogo")
        self._logo.setAlignment(Qt.AlignCenter)
        self._logo.setFixedSize(dimensions.s(40), dimensions.s(40))
        self._logo.setFocusPolicy(Qt.NoFocus)
        self._logo.setAccessibleName("TDEI logo")
        self._set_logo_pixmap()

        self._title = QLabel("TDEI")
        self._title.setObjectName("HeaderTitle")
        self._title.setFocusPolicy(Qt.NoFocus)
        self._title.setAccessibleName("TDEI")

        self._user = QLabel("")
        self._user.setObjectName("HeaderUser")
        self._user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._user.setFocusPolicy(Qt.NoFocus)
        self._user.setAccessibleName("Signed-in user")
        self._minimize = IconButton(
            "action_hide.svg",
            "Hide",
            size=36,
            icon_size=18,
        )
        self._minimize.setObjectName("HeaderMinimize")
        self._minimize.setToolTip("Hide panel")
        self._minimize.setAccessibleDescription(
            "Hide the TDEI panel on the map. Use the map TDEI control to show it again."
        )
        self._minimize.clicked.connect(self.minimize_requested.emit)
        self._sync = IconButton(
            "sync.svg",
            "Sync",
            size=36,
            icon_size=18,
        )
        self._sync.setObjectName("HeaderSync")
        self._sync.setToolTip(
            "Rebuild TDEI layers from local cache"
        )
        self._sync.setAccessibleDescription(
            "Rebuild TDEI layers from local cache"
        )
        self._sync.clicked.connect(self.sync_requested.emit)
        self._sync.hide()
        self._logout = IconButton(
            "logout.svg",
            "Logout",
            size=36,
            icon_size=18,
        )
        self._logout.setObjectName("HeaderLogout")
        self._logout.setAccessibleDescription("Sign out of TDEI")
        self._logout.clicked.connect(self.logout_requested.emit)
        self._logout.hide()
        layout.addWidget(self._logo, 0, Qt.AlignVCenter)
        layout.addWidget(self._title, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self._user, 0, Qt.AlignVCenter)
        layout.addWidget(self._minimize, 0, Qt.AlignVCenter)
        layout.addWidget(self._sync, 0, Qt.AlignVCenter)
        layout.addWidget(self._logout, 0, Qt.AlignVCenter)

    def _set_logo_pixmap(self) -> None:
        # Plugin root: …/tdei/ui/components → …/tdei
        root = Path(__file__).resolve().parents[2]
        for name in ("tdei_logo.png", "icon.png"):
            path = root / name
            if not path.is_file():
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            self._logo.setPixmap(
                pixmap.scaled(
                    dimensions.s(36),
                    dimensions.s(36),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            return

    def set_user(self, text: str) -> None:
        self._user.setText(text)
        self._user.setAccessibleDescription(text or "")
        signed_in = bool(text)
        self._logout.setVisible(signed_in)
        self._sync.setVisible(signed_in)

    def set_sync_enabled(self, enabled: bool) -> None:
        self._sync.setEnabled(bool(enabled))

    def set_user_tooltip(self, text: str) -> None:
        self._user.setToolTip(text or "")
        if text:
            self._user.setAccessibleDescription(text)
class _NavItem(QWidget):
    """Icon + label nav row with reliable vertical alignment."""

    clicked = pyqtSignal()

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self)
        self._label_text = label
        self._collapsed = False
        self._icon_size = dimensions.s(dimensions.NAV_ICON)
        self._row_height = dimensions.s(dimensions.NAV_ROW)

        self.setFixedHeight(self._row_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(label)
        self.setAccessibleDescription("Navigate to {}".format(label))

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignVCenter)

        self._icon = QLabel()
        self._icon.setObjectName("NavItemIcon")
        self._icon.setFixedSize(self._icon_size, self._icon_size)
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setScaledContents(False)
        self._icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.NoFocus)

        self._text = QLabel(label)
        self._text.setObjectName("NavItemLabel")
        self._text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._text.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text.setFocusPolicy(Qt.NoFocus)

        row.addWidget(self._icon, 0, Qt.AlignVCenter)
        row.addWidget(self._text, 1, Qt.AlignVCenter)

    def apply_metrics(self, icon_size: int, row_height: int) -> None:
        self._icon_size = icon_size
        self._row_height = row_height
        self.setFixedHeight(row_height)
        self._icon.setFixedSize(icon_size, icon_size)
        self.set_collapsed(self._collapsed)

    def set_icon(self, pixmap: QPixmap) -> None:
        self._icon.setScaledContents(False)
        self._icon.setFixedSize(self._icon_size, self._icon_size)
        self._icon.setPixmap(pixmap)
        self._icon.setAlignment(Qt.AlignCenter)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", bool(active))
        self._text.setProperty("active", bool(active))
        if active:
            self.setAccessibleDescription(
                "{}, current page".format(self._label_text)
            )
        else:
            self.setAccessibleDescription(
                "Navigate to {}".format(self._label_text)
            )
        _repolish(self)
        _repolish(self._text)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.setProperty("collapsed", self._collapsed)
        layout = self.layout()
        while layout.count():
            layout.takeAt(0)

        self.setFixedHeight(self._row_height)
        if self._collapsed:
            # Square-ish row: center icon both axes (fixes top-left HiDPI clip).
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.setAlignment(Qt.AlignCenter)
            self._text.hide()
            layout.addStretch(1)
            layout.addWidget(self._icon, 0, Qt.AlignCenter)
            layout.addStretch(1)
            self.setToolTip(self._label_text)
        else:
            layout.setContentsMargins(10, 0, 10, 0)
            layout.setSpacing(12)
            layout.setAlignment(Qt.AlignVCenter)
            self._text.show()
            layout.addWidget(self._icon, 0, Qt.AlignVCenter)
            layout.addWidget(self._text, 1, Qt.AlignVCenter)
            self.setToolTip("")
        _repolish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        if not self.property("active"):
            self.setProperty("hover", True)
            _repolish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hover", False)
        _repolish(self)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.setProperty("focus", True)
        _repolish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.setProperty("focus", False)
        _repolish(self)
        super().focusOutEvent(event)


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class Sidebar(QWidget):
    """Collapsible app navigation with icons; footer items stay at the bottom."""

    navigate = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)

    def __init__(
        self,
        items,
        parent=None,
        *,
        footer_items=None,
        collapsed: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAccessibleName("Main navigation")
        self.setAccessibleDescription(
            "Navigate between Dashboard, Datasets, Jobs, and Settings."
        )
        self._collapsed = bool(collapsed)
        self._active = ""
        self._buttons = {}
        self._meta = {}  # key -> (label, icon_name)
        self._icon_size = dimensions.s(dimensions.NAV_ICON)
        self._row_height = dimensions.s(dimensions.NAV_ROW)
        self._handle_w = dimensions.s(16)
        self._handle_h = dimensions.s(52)
        self._expanded_w = dimensions.s(dimensions.SIDEBAR_WIDTH)
        self._collapsed_w = dimensions.s(dimensions.SIDEBAR_COLLAPSED_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 16, 12, 16)
        root.setSpacing(4)

        for key, label, icon_name in items:
            root.addWidget(self._make_nav_button(key, label, icon_name))

        root.addStretch(1)

        self._divider = QFrame()
        self._divider.setObjectName("SidebarDivider")
        self._divider.setFrameShape(QFrame.HLine)
        self._divider.setFixedHeight(1)
        self._divider.setAccessibleName("")
        root.addWidget(self._divider)

        for key, label, icon_name in footer_items or ():
            root.addWidget(self._make_nav_button(key, label, icon_name))

        self._handle = QToolButton(self)
        self._handle.setObjectName("SidebarHandle")
        self._handle.setCursor(Qt.PointingHandCursor)
        keyboard_focus(self._handle)
        self._handle.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._handle.setAutoRaise(True)
        self._handle.setAccessibleName("Collapse or expand navigation")
        self._handle.clicked.connect(self._toggle_collapsed)
        self._handle.raise_()

        self.apply_metrics()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_handle()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_metrics()

    def apply_metrics(self) -> None:
        """Refresh sizes from the current UI scale / DPR."""
        self._icon_size = dimensions.s(dimensions.NAV_ICON)
        self._row_height = dimensions.s(dimensions.NAV_ROW)
        self._handle_w = dimensions.s(16)
        self._handle_h = dimensions.s(52)
        self._expanded_w = dimensions.s(dimensions.SIDEBAR_WIDTH)
        self._collapsed_w = dimensions.s(dimensions.SIDEBAR_COLLAPSED_WIDTH)

        self._handle.setFixedSize(self._handle_w, self._handle_h)
        self._handle.setIconSize(QSize(dimensions.s(14), dimensions.s(14)))

        for btn in self._buttons.values():
            btn.apply_metrics(self._icon_size, self._row_height)

        self._apply_collapsed()

    def _position_handle(self) -> None:
        handle_w = self._handle.width()
        handle_h = self._handle.height()
        x = self.width() - handle_w
        y = max(0, (self.height() - handle_h) // 2)
        self._handle.move(x, y)
        self._handle.raise_()

    def _make_nav_button(self, key: str, label: str, icon_name: str) -> _NavItem:
        self._meta[key] = (label, icon_name)
        btn = _NavItem(label)
        btn.clicked.connect(lambda k=key: self.navigate.emit(k))
        self._buttons[key] = btn
        self._paint_button(key)
        return btn

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_collapsed(animate=True)
        self.collapsed_changed.emit(self._collapsed)

    def _toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_active(self, key: str) -> None:
        self._active = key
        for name, btn in self._buttons.items():
            btn.set_active(name == key)
            self._paint_button(name)

    def _apply_collapsed(self, *, animate: bool = False) -> None:
        from ..motion import SIDEBAR_MS, animate_width, motion_enabled

        target = self._collapsed_w if self._collapsed else self._expanded_w
        right = 12 if not self._collapsed else 8
        self.layout().setContentsMargins(8, 16, right, 16)

        dpr = dimensions.device_pixel_ratio(self)
        chevron = (
            "sidebar_chevron_right.svg"
            if self._collapsed
            else "sidebar_chevron_left.svg"
        )
        self._handle.setIcon(
            tinted_icon(chevron, colors.TEXT_SECONDARY, dimensions.s(14), dpr=dpr)
        )
        self._handle.setToolTip(
            self.tr("Expand navigation")
            if self._collapsed
            else self.tr("Collapse navigation")
        )
        self._handle.setAccessibleName(
            self.tr("Expand navigation")
            if self._collapsed
            else self.tr("Collapse navigation")
        )

        # When collapsing, hide labels immediately so they don't clip mid-tween.
        if self._collapsed:
            for key, btn in self._buttons.items():
                btn.set_collapsed(True)
                self._paint_button(key)

        def _sync_widths(width_value=None) -> None:
            width = int(width_value) if width_value is not None else self.width()
            content_w = max(self._row_height, width - 16)
            for btn in self._buttons.values():
                btn.setFixedWidth(content_w)
            self._position_handle()

        def _finish() -> None:
            self.setFixedWidth(target)
            for key, btn in self._buttons.items():
                btn.set_collapsed(self._collapsed)
                self._paint_button(key)
            _sync_widths(target)

        if not animate or not motion_enabled():
            _finish()
            return

        animate_width(
            self,
            target,
            duration_ms=SIDEBAR_MS,
            on_value=_sync_widths,
            on_finished=_finish,
        )

    def _paint_button(self, key: str) -> None:
        btn = self._buttons[key]
        _label, icon_name = self._meta[key]
        active = key == self._active
        color = colors.TEXT_ON_PRIMARY if active else colors.TEXT
        dpr = dimensions.device_pixel_ratio(self)
        btn.set_icon(
            tinted_pixmap(icon_name, color, self._icon_size, dpr=dpr)
        )


class SegmentTabs(QWidget):
    """Compact List / Mapped style switcher."""

    changed = pyqtSignal(str)

    _ICONS = {
        "list": "tab_list.svg",
        "mapped": "tab_map.svg",
    }

    def __init__(self, items, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentTabs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAccessibleName("View mode")
        self.setAccessibleDescription("Switch between list and mapped views.")
        self._buttons = {}
        self._icon_names = {}
        self._current = items[0][0] if items else ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        for key, label in items:
            btn = QToolButton()
            btn.setText(label)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setObjectName("SegmentTab")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            keyboard_focus(btn)
            btn.setAccessibleName(label)
            btn.clicked.connect(lambda checked=False, k=key: self._select(k))
            self._buttons[key] = btn
            if key in self._ICONS:
                self._icon_names[key] = self._ICONS[key]
            layout.addWidget(btn)
        if self._current:
            self._sync()

    @property
    def current(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        if key not in self._buttons or key == self._current:
            return
        self._current = key
        self._sync()
        self.changed.emit(key)

    def _select(self, key: str) -> None:
        if key == self._current:
            self._sync()
            return
        self._current = key
        self._sync()
        self.changed.emit(key)

    def _sync(self) -> None:
        logical = dimensions.s(14)
        dpr = dimensions.device_pixel_ratio(self)
        for key, btn in self._buttons.items():
            selected = key == self._current
            btn.setChecked(selected)
            label = btn.text()
            if selected:
                btn.setAccessibleDescription("{}, selected".format(label))
            else:
                btn.setAccessibleDescription(label)
            icon_name = self._icon_names.get(key)
            if not icon_name:
                continue
            color = colors.TEXT if selected else colors.TEXT_MUTED
            btn.setIcon(tinted_icon(icon_name, color, size=logical, dpr=dpr))
            btn.setIconSize(QSize(logical, logical))


class PageContainer(QWidget):
    """Hosts pages inside a scroll area so tall content remains reachable."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageContainer")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("PageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setBackgroundRole(self.backgroundRole())
        self._layout.addWidget(self._scroll)

        self._current = None

    def set_page(self, widget: QWidget) -> None:
        if widget is self._current and self._scroll.widget() is widget:
            return
        previous = self._scroll.takeWidget()
        if previous is not None:
            # Keep NavigationManager-cached pages alive
            previous.setGraphicsEffect(None)
            previous.setParent(self)
            previous.hide()
        self._current = widget
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Inner padding lives on the page host so scrollbars sit at the edge
        if widget.layout() is not None and widget.property("_tdei_padded") != True:
            margins = widget.layout().contentsMargins()
            if margins.left() == 0 and margins.top() == 0:
                widget.layout().setContentsMargins(
                    dimensions.s(24),
                    dimensions.s(20),
                    dimensions.s(24),
                    dimensions.s(24),
                )
            widget.setProperty("_tdei_padded", True)
        self._scroll.setWidget(widget)
        widget.show()
        self._scroll.verticalScrollBar().setValue(0)
