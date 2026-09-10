# -*- coding: utf-8 -*-
"""Window status-bar engagement + progress channel."""

from __future__ import annotations

from qgis.PyQt.QtCore import QObject, pyqtSignal


class StatusService(QObject):
    """Pages publish messages/progress; MainWindow renders the status bar."""

    message_requested = pyqtSignal(str, int)  # text, timeout_ms (0 = sticky)
    # visible, percent (-1 = indeterminate), detail message
    progress_requested = pyqtSignal(bool, int, str)

    def show(self, message: str, timeout_ms: int = 5000) -> None:
        self.message_requested.emit(message, timeout_ms)

    def busy(self, message: str) -> None:
        """Sticky status text + indeterminate progress."""
        self.message_requested.emit(message, 0)
        self.progress_requested.emit(True, -1, message)

    def progress(self, percent: int, message: str) -> None:
        """Determinate 0–100 progress with status text."""
        self.message_requested.emit(message, 0)
        self.progress_requested.emit(True, max(0, min(100, int(percent))), message)

    def ready(self, message: str = "Ready") -> None:
        self.progress_requested.emit(False, 0, "")
        self.message_requested.emit(message, 0)

    def clear(self) -> None:
        self.ready("Ready")
