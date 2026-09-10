# -*- coding: utf-8 -*-
"""Test package bootstrap.

Prefer real QGIS bindings when available; otherwise install lightweight stubs
so pure unit tests can run from a normal Python interpreter.
"""

try:
    import qgis  # noqa: F401
except ImportError:
    from .fixtures.qgis_stubs import install_qgis_stubs

    install_qgis_stubs()
