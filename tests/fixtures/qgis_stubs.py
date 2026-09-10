# -*- coding: utf-8 -*-
"""Shared fixtures and QGIS stubs for unit tests."""

from __future__ import annotations

import sys
import types
from typing import Any, Dict


def install_qgis_stubs() -> None:
    """Install minimal qgis stubs so pure unit tests import without QGIS."""
    if "qgis" in sys.modules:
        return

    qgis = types.ModuleType("qgis")
    qgis_core = types.ModuleType("qgis.core")
    qgis_gui = types.ModuleType("qgis.gui")
    pyqt = types.ModuleType("qgis.PyQt")
    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtgui = types.ModuleType("qgis.PyQt.QtGui")
    qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")

    class _Qgis:
        Info = 0
        Warning = 1
        Critical = 2
        Success = 3
        QGIS_VERSION_INT = 33400

    class QgsSettings:
        def __init__(self):
            self._data: Dict[str, Any] = {}

        def value(self, key, default=None):
            return self._data.get(key, default)

        def setValue(self, key, value):
            self._data[key] = value

        def remove(self, key):
            self._data.pop(key, None)

    class QObject:
        def __init__(self, *args, **kwargs):
            pass

    def pyqtSignal(*_a, **_k):
        class _Signal:
            def connect(self, *_a, **_k):
                pass

            def emit(self, *_a, **_k):
                pass

            def disconnect(self, *_a, **_k):
                pass

        return _Signal()

    def pyqtSlot(*_a, **_k):
        def decorator(fn):
            return fn

        return decorator

    class QRunnable:
        def setAutoDelete(self, *_a):
            pass

    class QThreadPool:
        @staticmethod
        def globalInstance():
            return QThreadPool()

        def start(self, *_a):
            pass

        def waitForDone(self, *_a):
            return True

    class QDialog:
        Accepted = 1
        Rejected = 0

    class Qt:
        AlignCenter = 0
        AlignLeft = 1
        AlignRight = 2
        AlignVCenter = 3
        PointingHandCursor = 4
        WaitCursor = 5
        KeepAspectRatio = 6
        KeepAspectRatioByExpanding = 7
        SmoothTransformation = 8
        WA_StyledBackground = 9
        Horizontal = 10
        Vertical = 11
        UserRole = 12
        WA_TransparentForMouseEvents = 13

    qgis_core.Qgis = _Qgis
    qgis_core.QgsSettings = QgsSettings
    qgis_core.QgsApplication = types.SimpleNamespace(
        qgisSettingsDirPath=lambda: "/tmp"
    )
    qgis_core.QgsProject = types.SimpleNamespace(instance=lambda: None)
    qtcore.QObject = QObject
    qtcore.pyqtSignal = pyqtSignal
    qtcore.pyqtSlot = pyqtSlot
    qtcore.QRunnable = QRunnable
    qtcore.QThreadPool = QThreadPool
    qtcore.Qt = Qt
    qtcore.QTimer = types.SimpleNamespace(singleShot=lambda *_a, **_k: None)
    qtcore.QCoreApplication = types.SimpleNamespace(
        translate=lambda *_a, **_k: _a[-1] if _a else "",
        installTranslator=lambda *_a: None,
    )
    qtcore.QLocale = types.SimpleNamespace
    qtcore.QTranslator = type("QTranslator", (), {"load": lambda *_a: True})
    qtwidgets.QDialog = QDialog

    sys.modules["qgis"] = qgis
    sys.modules["qgis.core"] = qgis_core
    sys.modules["qgis.gui"] = qgis_gui
    sys.modules["qgis.PyQt"] = pyqt
    sys.modules["qgis.PyQt.QtCore"] = qtcore
    sys.modules["qgis.PyQt.QtGui"] = qtgui
    sys.modules["qgis.PyQt.QtWidgets"] = qtwidgets

    qgis.core = qgis_core
    qgis.gui = qgis_gui
    qgis.PyQt = pyqt
    pyqt.QtCore = qtcore
    pyqt.QtGui = qtgui
    pyqt.QtWidgets = qtwidgets


class FakeSettings:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)

    def bool(self, key, default=False):
        value = self._data.get(key, default)
        return bool(value)

    def int(self, key, default=0):
        return int(self._data.get(key, default))

    def feature_enabled(self, name):
        return bool(self._data.get("feature.{}".format(name), True))

    def config_version(self):
        return int(self._data.get("config_version", 1))

    def set_config_version(self, version):
        self._data["config_version"] = version
