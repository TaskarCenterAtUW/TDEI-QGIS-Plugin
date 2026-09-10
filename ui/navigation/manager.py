# -*- coding: utf-8 -*-
"""Central page navigation."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QWidget


class NavigationManager(QObject):
    page_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._factories: Dict[str, Callable[[], QWidget]] = {}
        self._pages: Dict[str, QWidget] = {}
        self._current: Optional[str] = None

    def register(self, key: str, factory: Callable[[], QWidget]) -> None:
        self._factories[key] = factory

    def navigate(self, key: str) -> QWidget:
        if key not in self._pages:
            if key not in self._factories:
                raise KeyError("Unknown page: {}".format(key))
            self._pages[key] = self._factories[key]()
        self._current = key
        self.page_changed.emit(key)
        return self._pages[key]

    def page_if_loaded(self, key: str) -> Optional[QWidget]:
        return self._pages.get(key)

    @property
    def current(self) -> Optional[str]:
        return self._current
