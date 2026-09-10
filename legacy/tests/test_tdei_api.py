# coding=utf-8
"""Tests for TDEI dataset JSON mapping."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdei_api import parse_dataset_rows, unpack_osw_package


class TestParseDatasetRows(unittest.TestCase):
    """Test mapping of TDEI dataset JSON to table rows."""

    def test_reads_id_and_nested_name(self):
        payload = [{
            'tdei_dataset_id': 'ds-1',
            'metadata': {
                'dataset_detail': {
                    'name': 'Downtown sidewalks'
                }
            }
        }]
        self.assertEqual(
            parse_dataset_rows(payload),
            [('ds-1', 'Downtown sidewalks')])

    def test_missing_name_is_empty_string(self):
        payload = [{'tdei_dataset_id': 'ds-2'}]
        self.assertEqual(parse_dataset_rows(payload), [('ds-2', '')])

    def test_wrapped_list_payload(self):
        payload = {
            'datasets': [{
                'tdei_dataset_id': 'ds-3',
                'metadata': {'dataset_detail': {'name': 'Bus stops'}}
            }]
        }
        self.assertEqual(
            parse_dataset_rows(payload),
            [('ds-3', 'Bus stops')])


class TestUnpackOswPackage(unittest.TestCase):
    """Test nested TDEI OSW zip extraction."""

    def test_extracts_geojson_from_inner_zip(self):
        geojson = '{"type":"FeatureCollection","features":[]}'
        with tempfile.TemporaryDirectory() as tmp:
            inner_path = os.path.join(tmp, 'inner.zip')
            with zipfile.ZipFile(inner_path, 'w') as inner:
                inner.writestr('sample.nodes.geojson', geojson)
                inner.writestr('sample.edges.geojson', geojson)
            outer_path = os.path.join(tmp, 'outer.zip')
            with zipfile.ZipFile(outer_path, 'w') as outer:
                outer.writestr('metadata.json', '{}')
                with open(inner_path, 'rb') as handle:
                    outer.writestr('dataset.zip', handle.read())
            dest = os.path.join(tmp, 'out')
            paths = unpack_osw_package(outer_path, dest)
            names = [os.path.basename(path) for path in paths]
            self.assertEqual(
                names, ['sample.nodes.geojson', 'sample.edges.geojson'])
            self.assertFalse(
                any(os.path.basename(path) == 'metadata.json' for path in paths))

    def test_accepts_top_level_geojson(self):
        geojson = '{"type":"FeatureCollection","features":[]}'
        with tempfile.TemporaryDirectory() as tmp:
            outer_path = os.path.join(tmp, 'outer.zip')
            with zipfile.ZipFile(outer_path, 'w') as outer:
                outer.writestr('metadata.json', '{}')
                outer.writestr('nodes.geojson', geojson)
            paths = unpack_osw_package(outer_path, os.path.join(tmp, 'out'))
            self.assertEqual(
                [os.path.basename(path) for path in paths],
                ['nodes.geojson'])


if __name__ == '__main__':
    unittest.main()
