# -*- coding: utf-8 -*-
"""Operations / jobs overview page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qgis.PyQt.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer


class OperationsPage(QWidget):
    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel(self.tr("Operations"))
        title.setObjectName("PageTitle")
        hint = QLabel(
            self.tr(
                "Available TDEI jobs. Run them from a dataset layer "
                "group context menu in QGIS after loading data."
            )
        )
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        self._list = QListWidget()
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self._list, 1)
        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        if not self._container.settings.feature_enabled("jobs"):
            self._list.addItem(self.tr("Jobs feature is disabled."))
            return
        for job in self._container.jobs.list_jobs():
            self._list.addItem(job.title)
