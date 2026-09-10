# -*- coding: utf-8 -*-
"""Brief busy/wait feedback for synchronous UI actions (zoom, API, etc.)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication


@contextmanager
def busy_action(container, message: str) -> Iterator[None]:
    """Show footer indeterminate progress + wait cursor for UI-thread work.

    Callers should finish with status.ready(...) / page _set_status(...) so the
    bar settles on a clear outcome message.
    """
    status = getattr(container, "status", None)
    app = QApplication.instance()
    if status is not None:
        try:
            status.busy(message)
        except Exception:  # noqa: BLE001
            pass
    if app is not None:
        app.setOverrideCursor(Qt.WaitCursor)
        try:
            # Let the status bar / progress paint before blocking work starts.
            app.processEvents()
        except Exception:  # noqa: BLE001
            pass
    try:
        yield
    finally:
        if app is not None:
            try:
                app.restoreOverrideCursor()
            except Exception:  # noqa: BLE001
                pass
            try:
                app.processEvents()
            except Exception:  # noqa: BLE001
                pass
