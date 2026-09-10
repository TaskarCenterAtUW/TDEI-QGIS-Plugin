# -*- coding: utf-8 -*-
"""Reusable confirmation dialog for destructive actions."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.compatibility.qt_compat import DialogAccepted
from ..a11y import keyboard_focus
from ..styles import colors, dimensions, typography


class ConfirmationDialog(QDialog):
    """Equal-height action row; destructive confirm stays visually distinct."""

    BUTTON_HEIGHT = 32
    BUTTON_MIN_WIDTH = 108

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_text: str = "Confirm",
        destructive: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setStyleSheet(self._dialog_stylesheet(destructive))
        self.setAccessibleName(title)
        self.setAccessibleDescription(message)
        self.setWhatsThis(message)
        self._initial_focus = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(0)

        heading = QLabel(title)
        heading.setObjectName("ConfirmTitle")
        heading.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        heading.setFocusPolicy(Qt.NoFocus)
        heading.setAccessibleName(title)

        body = QLabel(message)
        body.setObjectName("ConfirmBody")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setFocusPolicy(Qt.NoFocus)
        body.setAccessibleName(self.tr("Message"))
        body.setAccessibleDescription(message)

        layout.addWidget(heading)
        layout.addSpacing(8)
        layout.addWidget(body)
        layout.addSpacing(20)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addStretch(1)

        cancel = QPushButton(self.tr("Cancel"))
        cancel.setObjectName("ConfirmCancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(self.BUTTON_HEIGHT)
        cancel.setMinimumWidth(self.BUTTON_MIN_WIDTH)
        cancel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        keyboard_focus(cancel)
        cancel.setAutoDefault(False)
        cancel.setAccessibleName(self.tr("Cancel"))
        cancel.setAccessibleDescription(
            self.tr("Dismiss this dialog without confirming.")
        )
        cancel.clicked.connect(self.reject)

        confirm = QPushButton(confirm_text)
        confirm.setObjectName(
            "ConfirmDanger" if destructive else "ConfirmPrimary"
        )
        confirm.setCursor(Qt.PointingHandCursor)
        confirm.setFixedHeight(self.BUTTON_HEIGHT)
        confirm.setMinimumWidth(self.BUTTON_MIN_WIDTH)
        confirm.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        keyboard_focus(confirm)
        confirm.setAccessibleName(confirm_text)
        if destructive:
            confirm.setAccessibleDescription(
                self.tr("Confirm this destructive action.")
            )
            # Safer default focus for destructive confirms.
            cancel.setDefault(True)
            self._initial_focus = cancel
        else:
            confirm.setAccessibleDescription(
                self.tr("Confirm and continue.")
            )
            confirm.setDefault(True)
            self._initial_focus = confirm
        confirm.clicked.connect(self.accept)

        row.addWidget(cancel, 0, Qt.AlignVCenter)
        row.addWidget(confirm, 0, Qt.AlignVCenter)
        layout.addLayout(row)
        QWidget.setTabOrder(cancel, confirm)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._initial_focus is not None:
            self._initial_focus.setFocus(Qt.OtherFocusReason)

    @staticmethod
    def _dialog_stylesheet(destructive: bool) -> str:
        return """
            QDialog {{
                background-color: {surface};
            }}
            QLabel#ConfirmTitle {{
                color: {text};
                font-size: {fs_lg}px;
                font-weight: {fw_semi};
            }}
            QLabel#ConfirmBody {{
                color: {text_secondary};
                font-size: {fs_md}px;
            }}
            QPushButton#ConfirmCancel {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 0 16px;
                font-size: {fs_md}px;
                font-weight: {fw_medium};
            }}
            QPushButton#ConfirmCancel:hover {{
                background-color: {surface_alt};
                border-color: {border_strong};
            }}
            QPushButton#ConfirmCancel:focus {{
                border: 2px solid {focus};
            }}
            QPushButton#ConfirmPrimary {{
                background-color: {primary};
                color: #ffffff;
                border: 1px solid {primary};
                border-radius: {radius}px;
                padding: 0 16px;
                font-size: {fs_md}px;
                font-weight: {fw_semi};
            }}
            QPushButton#ConfirmPrimary:hover {{
                background-color: {primary_hover};
            }}
            QPushButton#ConfirmPrimary:focus {{
                border: 2px solid {primary_light};
            }}
            QPushButton#ConfirmDanger {{
                background-color: {error};
                color: #ffffff;
                border: 1px solid {error};
                border-radius: {radius}px;
                padding: 0 16px;
                font-size: {fs_md}px;
                font-weight: {fw_semi};
            }}
            QPushButton#ConfirmDanger:hover {{
                background-color: #a61f1f;
            }}
            QPushButton#ConfirmDanger:focus {{
                border: 2px solid {text};
            }}
        """.format(
            surface=colors.SURFACE,
            surface_alt=colors.SURFACE_ALT,
            text=colors.TEXT,
            text_secondary=colors.TEXT_SECONDARY,
            border=colors.BORDER,
            border_strong=colors.BORDER_STRONG,
            primary=colors.PRIMARY,
            primary_hover=colors.PRIMARY_HOVER,
            primary_light=colors.PRIMARY_LIGHT,
            error=colors.ERROR,
            focus=colors.FOCUS,
            fs_md=typography.FONT_SIZE_MD,
            fs_lg=typography.FONT_SIZE_LG,
            fw_medium=typography.FONT_WEIGHT_MEDIUM,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
            radius=dimensions.RADIUS_MD,
        )

    @staticmethod
    def ask(
        parent,
        title: str,
        message: str,
        *,
        confirm_text: str = "Confirm",
        destructive: bool = False,
    ) -> bool:
        dialog = ConfirmationDialog(
            title,
            message,
            confirm_text=confirm_text,
            destructive=destructive,
            parent=parent,
        )
        return dialog.exec_() == DialogAccepted
