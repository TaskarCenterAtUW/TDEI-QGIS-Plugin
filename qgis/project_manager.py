# -*- coding: utf-8 -*-
"""Thin QgsProject wrapper with change notifications for the plugin UI."""

from __future__ import annotations

from typing import Callable, List

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject, QTimer


class ProjectManager(QObject):
    """Tracks QGIS project open/clear and a generation counter for stale work."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listeners: List[Callable[[], None]] = []
        self._wired = False
        self._generation = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(50)
        self._debounce.timeout.connect(self._emit_changed)

    def instance(self) -> QgsProject:
        return QgsProject.instance()

    @property
    def generation(self) -> int:
        """Increments on every project clear/open; use to drop stale async work."""
        return self._generation

    def connect_project_signals(self) -> None:
        """Listen for project open/clear so Mapped/List can refresh safely."""
        if self._wired:
            return
        project = QgsProject.instance()
        # Opening another project: cleared then readProject — coalesce via timer.
        project.cleared.connect(self._on_project_transition)
        project.readProject.connect(self._on_project_transition)
        self._wired = True

    def on_project_changed(self, callback: Callable[[], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)
        self.connect_project_signals()

    def _on_project_transition(self, *_args) -> None:
        # Bump immediately so in-flight Sync/Download skip add_to_map.
        self._generation += 1
        self._debounce.start()

    def _emit_changed(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 — page refresh must not break QGIS
                pass
