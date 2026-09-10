# -*- coding: utf-8 -*-
"""Unit tests for OSW GeoJSON naming conventions."""

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

from tdei.features.osw.naming import (  # noqa: E402
    classify_osw_filenames,
    is_osw_convention_filename,
    osw_type_from_filename,
    pick_dataset_area_source,
)


class TestOswNaming(unittest.TestCase):
    def test_accepted_suffixes(self):
        for name in (
            "nodes.geojson",
            "demo.nodes.geojson",
            "x.edges.geojson",
            "a.lines.geojson",
            "b.zones.geojson",
            "c.polygons.geojson",
            "d.points.geojson",
            "Demo.Nodes.GeoJSON",
        ):
            self.assertTrue(is_osw_convention_filename(name), name)

    def test_rejected_names(self):
        for name in (
            "dataset_area.geojson",
            "nodes.json",
            "edges.geojson.bak",
            "foo_nodes.geojson",
            "metadata.json",
            "",
        ):
            self.assertFalse(is_osw_convention_filename(name), name)

    def test_classify(self):
        accepted, rejected = classify_osw_filenames(
            ["nodes.geojson", "dataset_area.geojson", "city.edges.geojson"]
        )
        self.assertEqual(accepted, ["nodes.geojson", "city.edges.geojson"])
        self.assertEqual(rejected, ["dataset_area.geojson"])

    def test_osw_type_from_filename(self):
        self.assertEqual(osw_type_from_filename("edges.geojson"), "edges")
        self.assertEqual(osw_type_from_filename("demo.nodes.geojson"), "nodes")
        self.assertIsNone(osw_type_from_filename("dataset_area.geojson"))

    def test_pick_dataset_area_source_priority(self):
        paths = [
            "/tmp/points.geojson",
            "/tmp/zones.geojson",
            "/tmp/edges.geojson",
            "/tmp/nodes.geojson",
            "/tmp/dataset_area.geojson",
        ]
        self.assertEqual(
            pick_dataset_area_source(paths), "/tmp/edges.geojson"
        )
        self.assertEqual(
            pick_dataset_area_source(
                ["/tmp/points.geojson", "/tmp/zones.geojson"]
            ),
            "/tmp/zones.geojson",
        )
        self.assertIsNone(
            pick_dataset_area_source(["/tmp/dataset_area.geojson"])
        )


if __name__ == "__main__":
    unittest.main()
