# -*- coding: utf-8 -*-
"""Unit tests for datasets list bbox query encoding (map search)."""

from __future__ import annotations

import os
import sys
import unittest
from urllib.parse import parse_qs

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.tests.fixtures.qgis_stubs import install_qgis_stubs

install_qgis_stubs()

from tdei.api.client import _query_string  # noqa: E402
from tdei.features.jobs.bbox import bbox_as_list  # noqa: E402


class DatasetListBBoxTests(unittest.TestCase):
    def test_query_string_repeats_bbox_keys(self):
        qs = _query_string(
            {
                "page_no": 1,
                "bbox": [-122.1, 47.6, -122.0, 47.7],
                "include_my_groups": True,
            }
        )
        self.assertTrue(qs.startswith("?"))
        parsed = parse_qs(qs[1:])
        self.assertEqual(
            parsed.get("bbox"),
            ["-122.1", "47.6", "-122.0", "47.7"],
        )
        self.assertEqual(parsed.get("include_my_groups"), ["true"])
        # Ensure not a single comma-joined value.
        self.assertNotIn("bbox=-122.1%2C47.6", qs)
        self.assertNotIn("bbox=-122.1,47.6", qs)

    def test_bbox_as_list_feeds_query_string(self):
        values = bbox_as_list((-122.1, 47.6, -122.0, 47.7))
        qs = _query_string({"bbox": values, "page_size": 50})
        self.assertIn("bbox=-122.1", qs)
        self.assertIn("bbox=47.6", qs)
        self.assertIn("bbox=-122.0", qs)
        self.assertIn("bbox=47.7", qs)
        self.assertIn("page_size=50", qs)


if __name__ == "__main__":
    unittest.main()
