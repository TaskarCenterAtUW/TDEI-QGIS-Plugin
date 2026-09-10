# -*- coding: utf-8 -*-
"""Unit tests for dataset-bbox helpers and request building."""

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

from tdei.tests.fixtures.qgis_stubs import FakeSettings, install_qgis_stubs

install_qgis_stubs()

from tdei.features.jobs.bbox import (  # noqa: E402
    format_bbox_csv,
    normalize_wsen,
    parse_bbox_csv,
)
from tdei.features.jobs.service import (  # noqa: E402
    DATASET_BBOX_PATH,
    JobService,
)


class DatasetBBoxTests(unittest.TestCase):
    def test_normalize_swaps_inverted_corners(self):
        self.assertEqual(
            normalize_wsen(-122.0, 47.7, -122.1, 47.6),
            (-122.1, 47.6, -122.0, 47.7),
        )

    def test_format_and_parse_roundtrip(self):
        csv = format_bbox_csv((-122.1, 47.6, -122.0, 47.7))
        self.assertEqual(csv, "-122.1,47.6,-122.0,47.7")
        self.assertEqual(parse_bbox_csv(csv), (-122.1, 47.6, -122.0, 47.7))

    def test_dataset_bbox_build_request_query(self):
        settings = FakeSettings({"environment": "development"})
        service = JobService(
            api_client=None, layer_manager=None, settings=settings
        )
        job = service.job_by_path(DATASET_BBOX_PATH)
        self.assertIsNotNone(job)
        fields = service.form_fields(job, dataset_id="ds-1")
        by_name = {field.name: field for field in fields}
        self.assertEqual(by_name["file_type"].enum, ["osw", "osm"])
        self.assertEqual(by_name["bbox"].type, "array")
        request = service.build_request(
            job,
            fields,
            {
                "tdei_dataset_id": "ds-1",
                "file_type": "osw",
                "bbox": "-122.1,47.6,-122.0,47.7",
            },
            dataset_id="ds-1",
        )
        url = request["url"]
        self.assertIn("/api/v1/osw/dataset-bbox?", url)
        self.assertIn("tdei_dataset_id=ds-1", url)
        self.assertIn("file_type=osw", url)
        self.assertIn("bbox=-122.1", url)
        self.assertIn("bbox=47.6", url)
        self.assertIn("bbox=-122.0", url)
        self.assertIn("bbox=47.7", url)
        self.assertIsNone(request["json_body"])
        self.assertIsNone(request["files"])


if __name__ == "__main__":
    unittest.main()
