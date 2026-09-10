# -*- coding: utf-8 -*-
"""Unit tests for OSW metadata dataset_area validation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.features.osw.metadata import (  # noqa: E402
    has_valid_dataset_area,
    is_valid_dataset_area,
    load_metadata_dict,
)


class TestDatasetArea(unittest.TestCase):
    def test_null_and_empty_invalid(self):
        self.assertFalse(is_valid_dataset_area(None))
        self.assertFalse(is_valid_dataset_area(""))
        self.assertFalse(is_valid_dataset_area("null"))
        self.assertFalse(is_valid_dataset_area({}))
        self.assertFalse(is_valid_dataset_area({"type": "Feature", "geometry": None}))

    def test_polygon_valid(self):
        poly = {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
            ],
        }
        self.assertTrue(is_valid_dataset_area(poly))
        self.assertTrue(is_valid_dataset_area(json.dumps(poly)))

    def test_feature_collection_valid(self):
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-122.3, 47.6],
                    },
                }
            ],
        }
        self.assertTrue(is_valid_dataset_area(fc))

    def test_has_valid_from_extracted_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = {
                "dataset_detail": {
                    "name": "Demo",
                    "dataset_area": {
                        "type": "Point",
                        "coordinates": [1, 2],
                    },
                }
            }
            path = os.path.join(tmp, "extracted", "metadata.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)
            self.assertTrue(has_valid_dataset_area(tmp))

    def test_missing_area_from_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "package.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "metadata.json",
                    json.dumps({"dataset_detail": {"name": "No area"}}),
                )
            self.assertFalse(has_valid_dataset_area(tmp))
            loaded = load_metadata_dict(tmp)
            self.assertEqual(loaded["dataset_detail"]["name"], "No area")

    def test_no_package_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(has_valid_dataset_area(tmp))

    def test_ensure_dataset_area_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = {
                "dataset_detail": {
                    "dataset_area": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                        ],
                    }
                }
            }
            path = os.path.join(tmp, "metadata.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)
            from tdei.features.osw.metadata import (
                DATASET_AREA_FILENAME,
                ensure_dataset_area_file,
                with_dataset_area_path,
            )

            area = ensure_dataset_area_file(tmp)
            self.assertIsNotNone(area)
            self.assertTrue(area.endswith(DATASET_AREA_FILENAME))
            with open(area, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["type"], "FeatureCollection")
            paths = with_dataset_area_path(
                tmp, [os.path.join(tmp, "nodes.geojson")]
            )
            self.assertEqual(paths[0], area)
            self.assertEqual(len(paths), 2)

    def test_apply_dataset_area_to_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = {
                "dataset_detail": {
                    "name": "Demo",
                    "version": "1.0",
                }
            }
            path = os.path.join(tmp, "metadata.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)
            area = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "dataset_area"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                            ],
                        },
                    }
                ],
            }
            from tdei.features.osw.metadata import (
                apply_dataset_area_to_metadata,
                dataset_area_value,
                load_metadata_dict,
            )

            written = apply_dataset_area_to_metadata(tmp, area)
            self.assertEqual(written, path)
            loaded = load_metadata_dict(tmp)
            self.assertEqual(dataset_area_value(loaded)["type"], "FeatureCollection")
            self.assertEqual(loaded["dataset_detail"]["name"], "Demo")

    def test_metadata_from_dataset_raw_and_set_area(self):
        from tdei.features.osw.metadata import (
            dataset_area_value,
            metadata_from_dataset_raw,
            raw_has_valid_dataset_area,
            set_dataset_area_on_metadata,
        )

        raw = {
            "tdei_dataset_id": "abc",
            "metadata": {
                "dataset_detail": {
                    "name": "From API",
                    "version": "2.0",
                    "collected_by": "tester",
                }
            },
        }
        self.assertFalse(raw_has_valid_dataset_area(raw))
        meta = metadata_from_dataset_raw(raw)
        self.assertEqual(meta["dataset_detail"]["name"], "From API")
        area = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        }
        set_dataset_area_on_metadata(meta, area)
        self.assertEqual(dataset_area_value(meta)["type"], "FeatureCollection")
        self.assertEqual(meta["dataset_detail"]["name"], "From API")
        raw["metadata"] = meta
        self.assertTrue(raw_has_valid_dataset_area(raw))


if __name__ == "__main__":
    unittest.main()
