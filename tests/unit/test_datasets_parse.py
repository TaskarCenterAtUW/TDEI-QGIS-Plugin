# -*- coding: utf-8 -*-
"""Unit tests for dataset payload parsing."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT))

from tdei.api.v1.datasets import parse_datasets  # noqa: E402
from tdei.core.utils.timefmt import format_timestamp  # noqa: E402


class TestParseDatasets(unittest.TestCase):
    def test_reads_id_and_nested_name(self):
        payload = [
            {
                "tdei_dataset_id": "ds-1",
                "status": "Publish",
                "uploaded_timestamp": "2024-03-12T14:05:00Z",
                "metadata": {
                    "dataset_detail": {
                        "name": "Downtown sidewalks",
                        "version": "1.2",
                    }
                },
            }
        ]
        datasets = parse_datasets(payload)
        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0].id, "ds-1")
        self.assertEqual(datasets[0].name, "Downtown sidewalks")
        self.assertEqual(datasets[0].version, "1.2")
        self.assertEqual(datasets[0].status, "Publish")
        self.assertEqual(
            datasets[0].uploaded_timestamp, "2024-03-12T14:05:00Z"
        )

    def test_reads_datasetdetails_alias(self):
        payload = [
            {
                "tdei_dataset_id": "ds-alias",
                "metadata": {
                    "datasetdetails": {
                        "name": "Alias name",
                        "version": "9",
                    }
                },
            }
        ]
        datasets = parse_datasets(payload)
        self.assertEqual(datasets[0].name, "Alias name")
        self.assertEqual(datasets[0].version, "9")

    def test_missing_name_is_empty_string(self):
        datasets = parse_datasets([{"tdei_dataset_id": "ds-2"}])
        self.assertEqual(datasets[0].name, "")
        self.assertEqual(datasets[0].version, "")
        self.assertEqual(datasets[0].status, "")

    def test_wrapped_list_payload(self):
        payload = {
            "datasets": [
                {
                    "tdei_dataset_id": "ds-3",
                    "metadata": {"dataset_detail": {"name": "Bus stops"}},
                }
            ]
        }
        datasets = parse_datasets(payload)
        self.assertEqual(datasets[0].id, "ds-3")
        self.assertEqual(datasets[0].name, "Bus stops")

    def test_reads_data_viewer_flags(self):
        payload = [
            {
                "tdei_dataset_id": "ds-view",
                "status": "Publish",
                "data_viewer_allowed": True,
                "project_group": {"data_viewer_allowed": False},
                "metadata": {"dataset_detail": {"name": "View me"}},
            }
        ]
        datasets = parse_datasets(payload)
        self.assertTrue(datasets[0].data_viewer_allowed)
        self.assertFalse(datasets[0].project_group_data_viewer_allowed)

    def test_viewer_flags_default_false(self):
        datasets = parse_datasets([{"tdei_dataset_id": "ds-noview"}])
        self.assertFalse(datasets[0].data_viewer_allowed)
        self.assertFalse(datasets[0].project_group_data_viewer_allowed)


if __name__ == "__main__":
    unittest.main()
