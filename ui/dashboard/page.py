# -*- coding: utf-8 -*-
"""Dashboard landing page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..a11y import set_page

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer


class DashboardPage(QWidget):
    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel(self.tr("Dashboard"))
        title.setObjectName("PageTitle")
        title.setFocusPolicy(Qt.NoFocus)
        env = container.environment()
        body_text = self.tr(
            "Welcome to TDEI for QGIS.\n\n"
            "Environment: {env}\n"
            "API: {api}\n\n"
            "Use Datasets to browse and load OpenSidewalks layers.\n"
            "Use Jobs to track job status and open downloadable results.\n"
            "Right-click a loaded TDEI layer group to submit jobs."
        ).format(env=env.label, api=env.api_base_url)
        body = QLabel(body_text)
        body.setObjectName("PageSubtitle")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setFocusPolicy(Qt.NoFocus)
        body.setAccessibleName(self.tr("Dashboard overview"))
        body.setAccessibleDescription(body_text)
        set_page(self, self.tr("Dashboard"), body_text)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch()
