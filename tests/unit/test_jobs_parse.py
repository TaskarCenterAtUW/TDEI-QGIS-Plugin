# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.api.v1.jobs import parse_jobs


class JobParseTests(unittest.TestCase):
    def test_parses_job_fields(self):
        jobs = parse_jobs(
            [
                {
                    "job_id": 42,
                    "job_type": "Dataset-Union",
                    "status": "COMPLETED",
                    "download_url": "https://example.test/out.zip",
                    "tdei_project_group_id": "pg-1",
                    "created_at": "2018-02-10T09:30:00Z",
                    "updated_at": "2018-02-10T11:34:00Z",
                },
                {
                    "job_id": 43,
                    "job_type": "Dataset-Validate",
                    "status": "FAILED",
                    "download_url": None,
                },
            ]
        )
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].id, "42")
        self.assertEqual(jobs[0].display_type, "Dataset-Union")
        self.assertTrue(jobs[0].has_download)
        self.assertEqual(jobs[0].map_key, "job-42")
        self.assertEqual(jobs[0].created_at, "2018-02-10T09:30:00Z")
        self.assertEqual(jobs[0].updated_at, "2018-02-10T11:34:00Z")
        self.assertFalse(jobs[1].has_download)

    def test_skips_missing_id(self):
        self.assertEqual(parse_jobs([{"job_type": "x"}]), [])

    def test_layer_menu_jobs_are_restricted(self):
        from tdei.features.jobs.service import LAYER_MENU_JOBS, SELF_MERGE_PATH

        paths = [path for path, _label in LAYER_MENU_JOBS]
        self.assertEqual(
            paths,
            [
                "/api/v1/osw/validate",
                "/api/v1/osw/sanitize",
                "/api/v1/osw/convert",
            ],
        )
        labels = [label for _path, label in LAYER_MENU_JOBS]
        self.assertEqual(labels, ["Validate", "Sanitize", "Convert"])
        self.assertNotIn(SELF_MERGE_PATH, paths)

    def test_is_geojson_layer_helper(self):
        from tdei.qgis.layer_manager import LayerManager

        class _Layer:
            def __init__(self, source, valid=True):
                self._source = source
                self._valid = valid

            def isValid(self):
                return self._valid

            def source(self):
                return self._source

        self.assertTrue(
            LayerManager.is_geojson_layer(_Layer("/tmp/nodes.geojson"))
        )
        self.assertTrue(LayerManager.is_geojson_layer(_Layer("/tmp/x.json")))
        self.assertFalse(
            LayerManager.is_geojson_layer(
                _Layer("/tmp/file.osm|layername=lines")
            )
        )
        self.assertFalse(LayerManager.is_geojson_layer(_Layer("/tmp/file.pbf")))
        self.assertFalse(LayerManager.is_geojson_layer(_Layer("", valid=False)))

    def test_dataset_row_jobs_include_self_merge(self):
        from tdei.features.jobs.service import (
            DATASET_ROW_JOBS,
            SELF_MERGE_PATH,
            JobService,
        )

        paths = [path for path, _label in DATASET_ROW_JOBS]
        self.assertEqual(paths, [SELF_MERGE_PATH])
        service = JobService(api_client=None, layer_manager=None, settings=None)
        service._spec = {"paths": {}, "components": {}}
        jobs = service.list_dataset_row_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].path, SELF_MERGE_PATH)
        self.assertEqual(jobs[0].title, "Self Merge")

    def test_self_merge_form_fields(self):
        from tdei.core.models import JobDefinition
        from tdei.features.jobs.service import (
            SELF_MERGE_OPERATION,
            SELF_MERGE_PATH,
            JobService,
        )

        job = JobDefinition(
            title="Self Merge",
            path=SELF_MERGE_PATH,
            method="POST",
            operation=dict(SELF_MERGE_OPERATION),
        )
        service = JobService(api_client=None, layer_manager=None, settings=None)
        # Avoid loading bundled spec for this synthetic operation
        service._spec = {"paths": {}, "components": {}}
        fields = service.form_fields(
            job, dataset_id="b688519d-ea00-4daa-a23f-0aff2ca138d2"
        )
        names = [field.name for field in fields]
        self.assertEqual(names, ["tdei_dataset_id", "proximity"])
        by_name = {field.name: field for field in fields}
        self.assertEqual(
            by_name["tdei_dataset_id"].value,
            "b688519d-ea00-4daa-a23f-0aff2ca138d2",
        )
        self.assertEqual(by_name["proximity"].value, 1)

    def test_formats_duration(self):
        from tdei.core.utils.timefmt import format_duration

        self.assertEqual(
            format_duration(
                "2018-02-10T09:30:00Z", "2018-02-10T11:34:00Z"
            ),
            "2 hrs 4 mins",
        )
        self.assertEqual(format_duration("", ""), "")


if __name__ == "__main__":
    unittest.main()
