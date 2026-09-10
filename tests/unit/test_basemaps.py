# -*- coding: utf-8 -*-
"""Unit tests for basemap provider catalog."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.qgis.basemaps import (  # noqa: E402
    BASEMAP_PROVIDERS,
    DEFAULT_BASEMAP,
)


class TestBasemapCatalog(unittest.TestCase):
    def test_default_is_osm(self):
        self.assertEqual(DEFAULT_BASEMAP, "openstreetmap")
        self.assertIn("openstreetmap", BASEMAP_PROVIDERS)

    def test_providers_have_urls_except_none(self):
        for key, meta in BASEMAP_PROVIDERS.items():
            self.assertIn("label", meta)
            if key == "none":
                self.assertEqual(meta.get("url"), "")
            else:
                self.assertIn("{z}", meta["url"])
                self.assertIn("{x}", meta["url"])
                self.assertIn("{y}", meta["url"])


if __name__ == "__main__":
    unittest.main()
