# -*- coding: utf-8 -*-
"""Unit tests for OSW package extraction."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT))

from tdei.features.osw.package import (  # noqa: E402
    is_map_filename,
    unpack_map_package,
    unpack_osw_package,
)


class TestUnpackOswPackage(unittest.TestCase):
    def test_extracts_geojson_from_inner_zip(self):
        geojson = '{"type":"FeatureCollection","features":[]}'
        with tempfile.TemporaryDirectory() as tmp:
            inner_path = os.path.join(tmp, "inner.zip")
            with zipfile.ZipFile(inner_path, "w") as inner:
                inner.writestr("sample.nodes.geojson", geojson)
                inner.writestr("sample.edges.geojson", geojson)
            outer_path = os.path.join(tmp, "outer.zip")
            with zipfile.ZipFile(outer_path, "w") as outer:
                outer.writestr("metadata.json", "{}")
                with open(inner_path, "rb") as handle:
                    outer.writestr("dataset.zip", handle.read())
            paths = unpack_osw_package(outer_path, os.path.join(tmp, "out"))
            names = [os.path.basename(path) for path in paths]
            self.assertEqual(
                names, ["sample.nodes.geojson", "sample.edges.geojson"]
            )

    def test_accepts_top_level_geojson(self):
        geojson = '{"type":"FeatureCollection","features":[]}'
        with tempfile.TemporaryDirectory() as tmp:
            outer_path = os.path.join(tmp, "outer.zip")
            with zipfile.ZipFile(outer_path, "w") as outer:
                outer.writestr("metadata.json", "{}")
                outer.writestr("nodes.geojson", geojson)
            paths = unpack_osw_package(outer_path, os.path.join(tmp, "out"))
            self.assertEqual(
                [os.path.basename(path) for path in paths], ["nodes.geojson"]
            )

    def test_finds_osm_xml_at_any_depth(self):
        osm = '<?xml version="1.0"?><osm version="0.6"></osm>'
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "job.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("a/b/c/21139.graph.osm.xml", osm)
            paths = unpack_map_package(
                zip_path,
                os.path.join(tmp, "out"),
                extensions=(".geojson", ".osm", ".osm.xml", ".pbf"),
            )
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith("21139.graph.osm.xml"))
            self.assertTrue(is_map_filename("21139.graph.osm.xml"))
            self.assertTrue(is_map_filename("network.osm"))
            self.assertFalse(is_map_filename("metadata.json"))


if __name__ == "__main__":
    unittest.main()
