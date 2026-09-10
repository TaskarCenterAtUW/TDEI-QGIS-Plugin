# -*- coding: utf-8 -*-
"""Qt / PyQt compatibility helpers for QGIS-bundled bindings."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog

# Prefer Qt enums available across PyQt5 (QGIS 3.x)
AlignCenter = Qt.AlignCenter
AlignLeft = Qt.AlignLeft
AlignRight = Qt.AlignRight
AlignVCenter = Qt.AlignVCenter
PointingHandCursor = Qt.PointingHandCursor
WaitCursor = Qt.WaitCursor
KeepAspectRatio = Qt.KeepAspectRatio
KeepAspectRatioByExpanding = Qt.KeepAspectRatioByExpanding
SmoothTransformation = Qt.SmoothTransformation
WA_StyledBackground = Qt.WA_StyledBackground
PasswordEcho = None  # set below after QLineEdit import

DialogAccepted = QDialog.Accepted
DialogRejected = QDialog.Rejected

Horizontal = Qt.Horizontal
Vertical = Qt.Vertical
UserRole = Qt.UserRole


def orientation_horizontal():
    return Qt.Horizontal
