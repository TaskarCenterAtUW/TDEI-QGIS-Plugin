# -*- coding: utf-8 -*-
"""Reusable background worker abstractions.

Workers must not touch Qt widgets or QgsProject — emit signals only.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from qgis.PyQt.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(int, str)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    finished = pyqtSignal()
    cancelled = pyqtSignal()


class Worker(QRunnable):
    """Run a callable off the UI thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancelled = False
        # Keep alive until slots have run (autoDelete races with queued signals)
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            if self._cancelled:
                self.signals.cancelled.emit()
                return
            outcome = self.fn(*self.args, **self.kwargs)
            if self._cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.result.emit(outcome)
        except Exception as exc:  # noqa: BLE001 — delivered via signal
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()


class WorkerPool:
    """Thin wrapper around the global QThreadPool."""

    def __init__(self, pool: Optional[QThreadPool] = None) -> None:
        self._pool = pool or QThreadPool.globalInstance()
        self._active: list = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Worker:
        worker = Worker(fn, *args, **kwargs)
        self._active.append(worker)

        def _cleanup(*_a):
            def _drop():
                if worker in self._active:
                    self._active.remove(worker)

            # Defer drop so queued result/error slots run first
            QTimer.singleShot(0, _drop)

        worker.signals.finished.connect(_cleanup)
        self._pool.start(worker)
        return worker

    def wait_for_done(self, timeout_ms: int = 3000) -> bool:
        return self._pool.waitForDone(timeout_ms)

    def shutdown(self) -> None:
        for worker in list(self._active):
            worker.cancel()
        self.wait_for_done(2000)
        self._active.clear()
