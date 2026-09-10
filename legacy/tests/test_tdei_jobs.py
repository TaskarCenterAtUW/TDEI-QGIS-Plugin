# coding=utf-8
"""Tests for OpenAPI-driven TDEI job forms."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdei_jobs import (
    build_request,
    form_fields,
    is_osw_package_field,
    list_jobs,
    load_job_spec,
    zip_geojson_paths,
)


class TestTdeiJobs(unittest.TestCase):
    """Job field lists come from the bundled OpenAPI spec."""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_job_spec()
        cls.jobs = {job['path']: job for job in list_jobs(cls.spec)}

    def test_lists_union_and_spatial_join(self):
        self.assertIn('/api/v1/osw/union', self.jobs)
        self.assertIn('/api/v1/osw/spatial-join', self.jobs)

    def test_union_fields_prefill_ids_and_include_proximity(self):
        job = self.jobs['/api/v1/osw/union']
        fields = form_fields(job, self.spec, dataset_id='ds-1')
        by_name = {field['name']: field for field in fields}
        self.assertEqual(
            list(by_name),
            ['tdei_dataset_id_one', 'tdei_dataset_id_two', 'proximity'])
        self.assertEqual(by_name['tdei_dataset_id_one']['value'], 'ds-1')
        self.assertEqual(by_name['tdei_dataset_id_two']['value'], 'ds-1')
        self.assertTrue(by_name['tdei_dataset_id_one']['required'])
        self.assertFalse(by_name['proximity']['required'])
        self.assertEqual(by_name['proximity']['type'], 'number')

    def test_union_request_includes_proximity(self):
        job = self.jobs['/api/v1/osw/union']
        fields = form_fields(job, self.spec, dataset_id='ds-1')
        request = build_request(
            job,
            fields,
            {
                'tdei_dataset_id_one': 'ds-1',
                'tdei_dataset_id_two': 'ds-1',
                'proximity': '0.5',
            },
            dataset_id='ds-1')
        self.assertEqual(request['url'], 'https://api-dev.tdei.us/api/v1/osw/union')
        self.assertEqual(request['json_body'], {
            'tdei_dataset_id_one': 'ds-1',
            'tdei_dataset_id_two': 'ds-1',
            'proximity': 0.5,
        })

    def test_spatial_join_uses_enum_fields(self):
        job = self.jobs['/api/v1/osw/spatial-join']
        fields = form_fields(job, self.spec, dataset_id='ds-1')
        by_name = {field['name']: field for field in fields}
        self.assertEqual(by_name['target_dataset_id']['value'], 'ds-1')
        self.assertEqual(by_name['source_dataset_id']['value'], 'ds-1')
        self.assertEqual(
            by_name['target_dimension']['enum'], ['edge', 'node', 'zone'])
        self.assertEqual(by_name['source_dimension']['value'], 'point')
        self.assertIn('join_condition', by_name)

    def test_confidence_injects_path_id(self):
        job = self.jobs['/api/v1/osw/confidence/{tdei_dataset_id}']
        fields = form_fields(job, self.spec, dataset_id='ds-1')
        self.assertEqual([field['name'] for field in fields], ['file'])
        self.assertFalse(fields[0]['required'])
        request = build_request(job, fields, {}, dataset_id='ds-1')
        self.assertEqual(
            request['url'],
            'https://api-dev.tdei.us/api/v1/osw/confidence/ds-1')

    def test_bbox_query_fields(self):
        job = self.jobs['/api/v1/osw/dataset-bbox']
        fields = form_fields(job, self.spec, dataset_id='ds-1')
        by_name = {field['name']: field for field in fields}
        self.assertEqual(by_name['tdei_dataset_id']['value'], 'ds-1')
        self.assertEqual(by_name['file_type']['enum'], ['osw', 'osm'])
        self.assertEqual(by_name['bbox']['type'], 'array')
        request = build_request(
            job,
            fields,
            {
                'tdei_dataset_id': 'ds-1',
                'file_type': 'osw',
                'bbox': '-122.1,47.6,-122.0,47.7',
            },
            dataset_id='ds-1')
        self.assertIn('tdei_dataset_id=ds-1', request['url'])
        self.assertIn('file_type=osw', request['url'])
        self.assertIn('bbox=-122.1', request['url'])

    def test_validate_dataset_field_is_osw_package(self):
        job = self.jobs['/api/v1/osw/validate']
        fields = form_fields(job, self.spec)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]['name'], 'dataset')
        self.assertTrue(is_osw_package_field(fields[0]))

    def test_confidence_file_is_not_osw_package(self):
        job = self.jobs['/api/v1/osw/confidence/{tdei_dataset_id}']
        fields = form_fields(job, self.spec)
        self.assertFalse(is_osw_package_field(fields[0]))

    def test_zips_geojsons_at_archive_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            nodes = os.path.join(tmp, 'nodes.geojson')
            edges = os.path.join(tmp, 'edges.geojson')
            with open(nodes, 'w') as handle:
                handle.write('{"type":"FeatureCollection","features":[]}')
            with open(edges, 'w') as handle:
                handle.write('{"type":"FeatureCollection","features":[]}')
            dest = os.path.join(tmp, 'osw.zip')
            zip_geojson_paths([nodes, edges], dest)
            with zipfile.ZipFile(dest) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ['edges.geojson', 'nodes.geojson'])


if __name__ == '__main__':
    unittest.main()
