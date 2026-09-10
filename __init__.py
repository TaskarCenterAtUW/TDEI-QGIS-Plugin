# -*- coding: utf-8 -*-
"""TDEI QGIS plugin package.

QGIS loads this module via ``classFactory(iface)``.
"""

from __future__ import annotations


def classFactory(iface):  # pylint: disable=invalid-name
    """Load and return the plugin instance.

    :param iface: QGIS interface
    :type iface: qgis.gui.QgsInterface
    """
    from .plugin import TdeiPlugin

    return TdeiPlugin(iface)
