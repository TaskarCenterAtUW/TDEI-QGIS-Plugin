# -*- coding: utf-8 -*-
"""Build TDEI job field lists from an OpenAPI spec."""

import json
import os
import re
import zipfile
from urllib.parse import quote, urlencode

SPEC_FILENAME = 'tdei_jobs_spec.json'
HOST = 'https://api-dev.tdei.us'
_DATASET_FIELD_NAMES = (
    'tdei_dataset_id',
    'tdei_dataset_id_one',
    'tdei_dataset_id_two',
    'source_dataset_id',
    'target_dataset_id',
)


def load_job_spec():
    path = os.path.join(os.path.dirname(__file__), SPEC_FILENAME)
    with open(path) as handle:
        return json.load(handle)


def list_jobs(spec=None):
    """Return job dicts: title, path, method, summary, operation."""
    spec = spec if spec is not None else load_job_spec()
    jobs = []
    for path, methods in (spec.get('paths') or {}).items():
        operation = (methods or {}).get('post')
        if not operation:
            continue
        jobs.append({
            'title': operation.get('summary') or operation.get('operationId') or path,
            'path': path,
            'method': 'POST',
            'operation': operation,
        })
    jobs.sort(key=lambda item: item['title'].lower())
    return jobs


def is_osw_package_field(field):
    """True when the field wants an OSW zip of GeoJSON files."""
    if field.get('format') != 'binary':
        return False
    if field.get('name') == 'dataset':
        return True
    description = (field.get('description') or '').lower()
    return 'zip' in description and (
        'geojson' in description or 'osw dataset' in description)


def zip_geojson_paths(paths, dest_zip):
    """Write GeoJSON files into a flat zip for validate/sanitize/convert."""
    files = [path for path in paths if path and os.path.isfile(path)]
    if not files:
        raise ValueError('No GeoJSON files to zip.')
    parent = os.path.dirname(dest_zip)
    if parent:
        os.makedirs(parent, exist_ok=True)
    used = set()
    with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = os.path.basename(path)
            stem, ext = os.path.splitext(name)
            candidate = name
            index = 2
            while candidate.lower() in used:
                candidate = '{}{}{}'.format(stem, index, ext)
                index += 1
            used.add(candidate.lower())
            archive.write(path, candidate)
    return dest_zip


def form_fields(job, spec=None, dataset_id=None):
    """Fields to show for this job, with dataset ids prefilled."""
    spec = spec if spec is not None else load_job_spec()
    operation = job['operation']
    fields = []
    for param in operation.get('parameters') or []:
        param = resolve_ref(param, spec)
        if param.get('in') == 'path':
            continue
        schema = resolve_ref(param.get('schema') or {}, spec)
        fields.append(_field_from_schema(
            name=param.get('name'),
            location=param.get('in') or 'query',
            schema=schema,
            required=bool(param.get('required')),
            description=param.get('description') or schema.get('description') or '',
            spec=spec,
        ))
    body = operation.get('requestBody')
    if body:
        body = resolve_ref(body, spec)
        content = body.get('content') or {}
        if 'application/json' in content:
            schema = resolve_ref(content['application/json'].get('schema') or {}, spec)
            required = set(schema.get('required') or [])
            for name, prop in (schema.get('properties') or {}).items():
                prop = resolve_ref(prop, spec)
                fields.append(_field_from_schema(
                    name=name,
                    location='json',
                    schema=prop,
                    required=name in required,
                    description=prop.get('description') or '',
                    spec=spec,
                ))
        elif 'multipart/form-data' in content:
            schema = resolve_ref(
                content['multipart/form-data'].get('schema') or {}, spec)
            required = set(schema.get('required') or [])
            for name, prop in (schema.get('properties') or {}).items():
                prop = resolve_ref(prop, spec)
                fields.append(_field_from_schema(
                    name=name,
                    location='form',
                    schema=prop,
                    required=name in required,
                    description=prop.get('description') or '',
                    spec=spec,
                ))
    if dataset_id:
        for field in fields:
            if field['name'] in _DATASET_FIELD_NAMES:
                field['value'] = dataset_id
    return fields


def build_request(job, fields, values, dataset_id=None):
    """Turn form values into URL, JSON body, form fields, and files."""
    path = job['path']
    path_params = re.findall(r'\{([^}]+)\}', path)
    for name in path_params:
        path = path.replace(
            '{' + name + '}',
            quote(str(values.get(name) or dataset_id or ''), safe=''))
    url = HOST + path
    query = []
    json_body = {}
    form_fields_out = {}
    files = {}
    has_json = False
    has_form = False
    for field in fields:
        name = field['name']
        value = values.get(name)
        location = field['location']
        if location == 'query':
            if value in (None, ''):
                if field['required']:
                    raise ValueError('{} is required'.format(name))
                continue
            if field['type'] == 'array' and isinstance(value, str):
                value = [part.strip() for part in value.split(',') if part.strip()]
            if isinstance(value, list):
                for item in value:
                    query.append((name, item))
            else:
                query.append((name, value))
        elif location == 'json':
            has_json = True
            if value in (None, ''):
                if field['required']:
                    raise ValueError('{} is required'.format(name))
                continue
            json_body[name] = _coerce(field, value)
        elif location == 'form':
            has_form = True
            if field.get('format') == 'binary':
                if not value and field['required']:
                    raise ValueError('{} is required'.format(name))
                if value:
                    files[name] = value
            else:
                if value in (None, '') and field['required']:
                    raise ValueError('{} is required'.format(name))
                if value not in (None, ''):
                    form_fields_out[name] = value
    if query:
        url = '{}?{}'.format(url, urlencode(query, doseq=True))
    return {
        'url': url,
        'json_body': json_body if has_json else None,
        'fields': form_fields_out if has_form else None,
        'files': files if has_form else None,
    }


def resolve_ref(node, spec):
    if not isinstance(node, dict) or '$ref' not in node:
        return node
    pointer = node['$ref'].lstrip('#/').split('/')
    resolved = spec
    for part in pointer:
        resolved = resolved[part]
    return resolved


def _field_from_schema(name, location, schema, required, description, spec):
    schema = resolve_ref(schema, spec)
    default = schema.get('default')
    return {
        'name': name,
        'location': location,
        'required': required,
        'type': schema.get('type') or 'string',
        'format': schema.get('format'),
        'enum': schema.get('enum'),
        'description': description or schema.get('description') or '',
        'value': '' if default is None else default,
    }


def _coerce(field, value):
    if field['type'] == 'number':
        return float(value)
    if field['type'] == 'integer':
        return int(value)
    if field['type'] == 'boolean':
        return bool(value)
    if field['type'] == 'array' and isinstance(value, str):
        text = value.strip()
        if text.startswith('['):
            return json.loads(text)
        return [part.strip() for part in text.split(',') if part.strip()]
    return value
