# -*- coding: utf-8 -*-
"""Login page — grid-aligned form; auth via LoginService + workers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from qgis.PyQt.QtCore import QEvent, QObject, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.exceptions import AuthenticationError, TdeiError
from ..a11y import label_for, live_status, set_name, set_page, set_tab_order
from ..components import PrimaryButton
from ..styles import colors, dimensions, typography
from ..styles.theme import theme

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer


class _LoginBackgroundFilter(QObject):
    def __init__(self, pixmap, parent=None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            painter = QPainter(obj)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled = self._pixmap.scaled(
                obj.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (obj.width() - scaled.width()) // 2
            y = (obj.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            return True
        return False


class _PasswordField(QFrame):
    """Single-width control: password edit + eye, shared outer border."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("passwordField")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(dimensions.LOGIN_FIELD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.edit = QLineEdit(self)
        self.edit.setObjectName("txtPasswordEmbedded")
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("Enter password")
        self.edit.setFixedHeight(dimensions.LOGIN_FIELD_HEIGHT)
        self.edit.installEventFilter(self)

        self.toggle = QToolButton(self)
        self.toggle.setObjectName("btnShowPassword")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setFocusPolicy(Qt.StrongFocus)
        self.toggle.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.toggle.setFixedSize(
            dimensions.LOGIN_EYE_WIDTH, dimensions.LOGIN_FIELD_HEIGHT
        )
        self.toggle.setToolTip("Show password")
        self.toggle.setAccessibleName("Show password")
        self.toggle.setAccessibleDescription(
            "Toggle password visibility"
        )

        row.addWidget(self.edit, 1)
        row.addWidget(self.toggle)

    def eventFilter(self, obj, event):
        if obj is self.edit:
            if event.type() == QEvent.FocusIn:
                self.setProperty("focused", True)
                self.style().unpolish(self)
                self.style().polish(self)
            elif event.type() == QEvent.FocusOut:
                self.setProperty("focused", False)
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(obj, event)


class LoginPage(QWidget):
    login_succeeded = pyqtSignal()

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self.setObjectName("LoginPage")
        set_page(
            self,
            self.tr("Sign in"),
            self.tr("Sign in to continue to TDEI"),
        )
        self._build()

    def _build(self) -> None:
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        logo_path = os.path.join(root, "tdei_logo.png")
        bg_path = os.path.join(root, "bg_login.png")
        eye_path = os.path.join(root, "visibility.svg")
        eye_off_path = os.path.join(root, "visibility_off.svg")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("loginHeader")
        header.setFixedHeight(dimensions.HEADER_HEIGHT)
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(8)
        self._header_logo = QLabel()
        self._header_logo.setObjectName("lblHeaderLogo")
        self._header_logo.setAlignment(Qt.AlignCenter)
        self._header_logo.setFixedSize(56, 44)
        brand = QLabel(self.tr("TDEI"))
        brand.setObjectName("lblHeaderBrand")
        brand.setFocusPolicy(Qt.NoFocus)
        brand.setAccessibleName(self.tr("TDEI"))
        self._header_logo.setAccessibleName(self.tr("TDEI logo"))
        self._header_logo.setFocusPolicy(Qt.NoFocus)
        header_layout.addWidget(self._header_logo, 0, Qt.AlignVCenter)
        header_layout.addWidget(brand, 0, Qt.AlignVCenter)
        header_layout.addStretch(1)
        outer.addWidget(header)

        self._body = QWidget()
        self._body.setObjectName("loginBody")
        body_layout = QGridLayout(self._body)
        body_layout.setContentsMargins(24, 24, 24, 24)
        body_layout.setHorizontalSpacing(0)
        body_layout.setVerticalSpacing(0)
        body_layout.setRowStretch(0, 1)
        body_layout.setRowStretch(1, 0)
        body_layout.setRowStretch(2, 1)
        body_layout.setColumnStretch(0, 1)
        body_layout.setColumnStretch(1, 0)
        body_layout.setColumnStretch(2, 1)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(dimensions.LOGIN_CARD_WIDTH)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(0)

        # Brand block
        brand_block = QWidget()
        brand_grid = QGridLayout(brand_block)
        brand_grid.setContentsMargins(0, 0, 0, 0)
        brand_grid.setHorizontalSpacing(0)
        brand_grid.setVerticalSpacing(0)
        brand_grid.setColumnStretch(0, 1)

        self._logo = QLabel()
        self._logo.setObjectName("lblLogo")
        self._logo.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._logo.setMinimumHeight(64)

        title = QLabel(self.tr("Welcome back"))
        title.setObjectName("lblTitle")
        title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        title.setFocusPolicy(Qt.NoFocus)
        title.setAccessibleName(self.tr("Welcome back"))

        subtitle = QLabel(self.tr("Sign in to continue to TDEI"))
        subtitle.setObjectName("lblSubtitle")
        subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle.setWordWrap(True)
        subtitle.setFocusPolicy(Qt.NoFocus)
        subtitle.setAccessibleDescription(
            self.tr("Sign in to continue to TDEI")
        )

        brand_grid.addWidget(self._logo, 0, 0)
        brand_grid.addItem(
            QSpacerItem(1, 12, QSizePolicy.Minimum, QSizePolicy.Fixed), 1, 0
        )
        brand_grid.addWidget(title, 2, 0)
        brand_grid.addItem(
            QSpacerItem(1, 6, QSizePolicy.Minimum, QSizePolicy.Fixed), 3, 0
        )
        brand_grid.addWidget(subtitle, 4, 0)
        brand_grid.addItem(
            QSpacerItem(1, 28, QSizePolicy.Minimum, QSizePolicy.Fixed), 5, 0
        )
        card_layout.addWidget(brand_block)

        # Form grid — single column so every control shares the same width
        form = QWidget()
        form.setObjectName("loginForm")
        grid = QGridLayout(form)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)

        user_lbl = QLabel(self.tr("Username / Email"))
        user_lbl.setObjectName("lblUsername")
        user_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._username = QLineEdit()
        self._username.setObjectName("txtUsername")
        self._username.setPlaceholderText(self.tr("Enter email or username"))
        self._username.setFixedHeight(dimensions.LOGIN_FIELD_HEIGHT)
        self._username.setFocusPolicy(Qt.StrongFocus)
        self._username.setAttribute(Qt.WA_MacShowFocusRect, False)
        remembered = self._container.settings.get("ui.last_username", "")
        if remembered:
            self._username.setText(str(remembered))
        label_for(
            user_lbl,
            self._username,
            name=self.tr("Username or email"),
            description=self.tr("Enter your TDEI username or email address."),
        )

        pass_lbl = QLabel(self.tr("Password"))
        pass_lbl.setObjectName("lblPassword")
        pass_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._password_field = _PasswordField()
        self._password = self._password_field.edit
        self._show = self._password_field.toggle
        self._password.setFocusPolicy(Qt.StrongFocus)
        self._password.setAttribute(Qt.WA_MacShowFocusRect, False)
        label_for(
            pass_lbl,
            self._password,
            name=self.tr("Password"),
            description=self.tr("Enter your TDEI password."),
        )
        self._eye = QIcon(eye_path)
        self._eye_off = QIcon(eye_off_path)
        self._show.setIcon(self._eye)
        self._show.setIconSize(QSize(20, 20))
        self._show.toggled.connect(self._toggle_password)

        self._status = QLabel("")
        self._status.setObjectName("lblStatus")
        self._status.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._status.setWordWrap(True)
        self._status.setProperty("error", False)
        self._status.setFocusPolicy(Qt.NoFocus)
        self._status.setAccessibleName(self.tr("Status"))

        self._login_btn = PrimaryButton(self.tr("Sign In"))
        self._login_btn.setObjectName("btnLogin")
        self._login_btn.setCursor(Qt.PointingHandCursor)
        self._login_btn.setDefault(True)
        self._login_btn.setAutoDefault(True)
        self._login_btn.setFixedHeight(dimensions.LOGIN_FIELD_HEIGHT)
        set_name(
            self._login_btn,
            self.tr("Sign In"),
            self.tr("Sign in to TDEI with the username and password above."),
        )
        self._login_btn.clicked.connect(self._on_login)
        self._username.returnPressed.connect(self._on_login)
        self._password.returnPressed.connect(self._on_login)

        version = QLabel("V {}".format(self._plugin_version(root)))
        version.setObjectName("lblVersion")
        version.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        version.setFocusPolicy(Qt.NoFocus)
        version.setAccessibleName(self.tr("Plugin version"))

        # Rows: label → gap → field → section gap → …
        grid.addWidget(user_lbl, 0, 0)
        grid.addItem(QSpacerItem(1, 8, QSizePolicy.Minimum, QSizePolicy.Fixed), 1, 0)
        grid.addWidget(self._username, 2, 0)
        grid.addItem(QSpacerItem(1, 16, QSizePolicy.Minimum, QSizePolicy.Fixed), 3, 0)
        grid.addWidget(pass_lbl, 4, 0)
        grid.addItem(QSpacerItem(1, 8, QSizePolicy.Minimum, QSizePolicy.Fixed), 5, 0)
        grid.addWidget(self._password_field, 6, 0)
        grid.addItem(QSpacerItem(1, 12, QSizePolicy.Minimum, QSizePolicy.Fixed), 7, 0)
        grid.addWidget(self._status, 8, 0)
        grid.addItem(QSpacerItem(1, 12, QSizePolicy.Minimum, QSizePolicy.Fixed), 9, 0)
        grid.addWidget(self._login_btn, 10, 0)
        grid.addItem(QSpacerItem(1, 16, QSizePolicy.Minimum, QSizePolicy.Fixed), 11, 0)
        grid.addWidget(version, 12, 0)

        card_layout.addWidget(form)
        body_layout.addWidget(card, 1, 1, Qt.AlignCenter)
        outer.addWidget(self._body, 1)

        set_tab_order(
            (
                self._username,
                self._password,
                self._show,
                self._login_btn,
            )
        )

        if os.path.exists(logo_path):
            logo = QPixmap(logo_path)
            self._header_logo.setPixmap(
                logo.scaled(44, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._logo.setPixmap(
                logo.scaledToWidth(88, Qt.SmoothTransformation)
            )
        if os.path.exists(bg_path):
            self._bg_filter = _LoginBackgroundFilter(QPixmap(bg_path), self)
            self._body.installEventFilter(self._bg_filter)

        self._apply_fonts()
        self.setStyleSheet(theme.login_stylesheet())

    def _apply_fonts(self) -> None:
        families = QFontDatabase().families()
        if "Open Sans" not in families:
            return
        for widget in (
            self,
            self._username,
            self._password,
            self._login_btn,
            self._status,
        ):
            font = widget.font()
            font.setFamily("Open Sans")
            widget.setFont(font)

    def _toggle_password(self, visible: bool) -> None:
        if visible:
            self._password.setEchoMode(QLineEdit.Normal)
            self._show.setIcon(self._eye_off)
            tip = self.tr("Hide password")
        else:
            self._password.setEchoMode(QLineEdit.Password)
            self._show.setIcon(self._eye)
            tip = self.tr("Show password")
        self._show.setToolTip(tip)
        self._show.setAccessibleName(tip)

    def _on_login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            self._set_status(
                self.tr("Enter both username and password."), error=True
            )
            if not username:
                self._username.setFocus(Qt.OtherFocusReason)
            else:
                self._password.setFocus(Qt.OtherFocusReason)
            return
        self._login_btn.setEnabled(False)
        self._set_status(self.tr("Signing in…"))
        status = getattr(self._container, "status", None)
        if status is not None:
            status.busy(self.tr("Signing in…"))
        worker = self._container.workers.submit(
            self._container.login_service.sign_in, username, password
        )
        worker.signals.result.connect(self._on_success)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(
            lambda: self._login_btn.setEnabled(True)
        )

    def _on_success(self, _user) -> None:
        self._password.clear()
        self._set_status("")
        self.login_succeeded.emit()

    def _on_error(self, exc) -> None:
        if isinstance(exc, AuthenticationError):
            message = str(exc)
        elif isinstance(exc, TdeiError):
            message = str(exc)
        else:
            message = self.tr("Unable to sign in. Please try again.")
        self._set_status(message, error=True)
        status = getattr(self._container, "status", None)
        if status is not None:
            status.show(message, 6000)
        self._password.setFocus()
        self._password.selectAll()

    def _set_status(self, message: str, error: bool = False) -> None:
        live_status(self._status, message, error=error)
        self._status.setProperty("error", error)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        color = colors.ERROR if error else colors.TEXT_MUTED
        self._status.setStyleSheet(
            "color: {0}; font-size: {1}px; min-height: 20px;".format(
                color, typography.FONT_SIZE_MD
            )
        )

    @staticmethod
    def _plugin_version(root: str) -> str:
        metadata = os.path.join(root, "metadata.txt")
        try:
            with open(metadata) as handle:
                for line in handle:
                    if line.startswith("version="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return "1.0.0"
