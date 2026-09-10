# -*- coding: utf-8 -*-
"""Modal progress dialog for zip + job upload."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from ..a11y import keyboard_focus
from ..styles import colors, dimensions, typography
from ..styles.theme import theme


class JobProgressDialog(QDialog):
    def __init__(self, title: str = "Submitting job", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(dimensions.s(360))
        self.setStyleSheet(theme.application_stylesheet() + self._extra())
        # Block close while work is in flight
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowCloseButtonHint
        )
        self.setAccessibleName(title)
        self.setAccessibleDescription(
            self.tr("Job submission in progress. Please wait.")
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self._title = QLabel(title)
        self._title.setObjectName("JobProgressTitle")
        self._title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._title.setFocusPolicy(Qt.NoFocus)
        self._title.setAccessibleName(title)

        self._status = QLabel(self.tr("Starting…"))
        self._status.setObjectName("JobProgressStatus")
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._status.setFocusPolicy(Qt.NoFocus)
        self._status.setAccessibleName(self.tr("Status"))
        self._status.setAccessibleDescription(self.tr("Starting…"))

        self._bar = QProgressBar()
        self._bar.setObjectName("JobProgressBar")
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(True)
        self._bar.setFormat(self.tr("Working…"))
        self._bar.setFixedHeight(16)
        keyboard_focus(self._bar)
        self._bar.setAccessibleName(self.tr("Progress"))
        self._bar.setAccessibleDescription(self.tr("Starting…"))

        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._bar)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._bar.setFocus(Qt.OtherFocusReason)

    def set_status(self, message: str, percent: int = -1) -> None:
        text = message or ""
        self._status.setText(text)
        self._status.setAccessibleDescription(text)
        self.setAccessibleDescription(text or self.tr("Job submission in progress."))

        if percent is None or percent < 0:
            self._bar.setRange(0, 0)
            self._bar.setFormat(text or self.tr("Working…"))
            self._bar.setAccessibleDescription(
                text or self.tr("Progress indeterminate")
            )
        else:
            value = max(0, min(100, int(percent)))
            self._bar.setRange(0, 100)
            self._bar.setValue(value)
            self._bar.setFormat("%p% — {}".format(text) if text else "%p%")
            self._bar.setAccessibleDescription(
                self.tr("{} percent. {}").format(value, text)
            )

    @staticmethod
    def _extra() -> str:
        return """
            QDialog {{
                background-color: {surface};
            }}
            QLabel#JobProgressTitle {{
                color: {text};
                font-size: {fs_lg}px;
                font-weight: {fw_semi};
            }}
            QLabel#JobProgressStatus {{
                color: {text_secondary};
                font-size: {fs_sm}px;
            }}
            QProgressBar#JobProgressBar {{
                background: {surface_alt};
                border: 1px solid {border};
                border-radius: 5px;
                text-align: center;
                color: {text};
                font-size: {fs_xs}px;
            }}
            QProgressBar#JobProgressBar:focus {{
                border: 2px solid {focus};
            }}
            QProgressBar#JobProgressBar::chunk {{
                background: {primary};
                border-radius: 4px;
            }}
        """.format(
            surface=colors.SURFACE,
            surface_alt=colors.SURFACE_ALT,
            text=colors.TEXT,
            text_secondary=colors.TEXT_SECONDARY,
            border=colors.BORDER,
            primary=colors.PRIMARY,
            focus=colors.FOCUS,
            fs_xs=typography.FONT_SIZE_XS,
            fs_sm=typography.FONT_SIZE_SM,
            fs_lg=typography.FONT_SIZE_LG,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
        )
