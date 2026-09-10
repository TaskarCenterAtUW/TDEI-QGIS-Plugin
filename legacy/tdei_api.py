# -*- coding: utf-8 -*-
"""TDEI gateway HTTP helpers for authentication, listing, and OSW download."""

import json
import os
import shutil
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE_URL = 'https://api-dev.tdei.us/api/v1'
AUTH_URL = '{}/authenticate'.format(BASE_URL)
DATASETS_URL = '{}/datasets'.format(BASE_URL)
OSW_DOWNLOAD_TIMEOUT = 180
_GEOJSON_ORDER = (
    'nodes', 'edges', 'lines', 'points', 'polygons', 'zones')


class TdeiApiError(Exception):
    """Raised when a TDEI API call fails."""

    def __init__(self, message, status_code=None):
        super(TdeiApiError, self).__init__(message)
        self.status_code = status_code


def authenticate(username, password):
    """Return a JWT access token for the given credentials.

    :raises TdeiApiError: if login fails or no token is returned
    """
    payload = json.dumps({
        'username': username,
        'password': password,
    }).encode('utf-8')
    try:
        data = _json_request(
            AUTH_URL,
            method='POST',
            body=payload,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            })
    except TdeiApiError as exc:
        if exc.status_code == 401:
            raise TdeiApiError(
                'Invalid username or password.', status_code=401) from exc
        raise
    token = (
        data.get('access_token')
        or data.get('accessToken')
        or data.get('token'))
    if not token:
        raise TdeiApiError(
            'Sign in succeeded but no access token was returned.')
    return token


def download_osw_zip(token, dataset_id, dest_path):
    """Download the OSW zip for ``dataset_id`` to ``dest_path``."""
    url = '{}/osw/{}?format=osw&file_version=latest'.format(
        BASE_URL, quote(str(dataset_id), safe=''))
    data = _binary_request(
        url,
        headers={
            'Accept': 'application/octet-stream',
            'Authorization': 'Bearer {}'.format(token),
        },
        timeout=OSW_DOWNLOAD_TIMEOUT)
    if not data:
        raise TdeiApiError('Download returned an empty file.')
    if data[:2] != b'PK':
        raise TdeiApiError(_non_zip_message(data))
    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest_path, 'wb') as handle:
        handle.write(data)
    return dest_path


def unpack_osw_package(zip_path, dest_dir):
    """Extract a TDEI OSW zip and return GeoJSON file paths.

    The outer zip contains ``metadata.json`` plus an inner zip of GeoJSON
    files. Top-level GeoJSON files are also accepted.
    """
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    outer_dir = os.path.join(dest_dir, 'outer')
    os.makedirs(outer_dir, exist_ok=True)
    _safe_extract(zip_path, outer_dir)

    geojsons = _find_geojsons(outer_dir)
    if geojsons:
        return _sort_geojsons(geojsons)

    inner_zips = _find_zips(outer_dir)
    if not inner_zips:
        raise TdeiApiError(
            'The OSW package has no GeoJSON files or inner zip.')

    inner_dir = os.path.join(dest_dir, 'geojson')
    os.makedirs(inner_dir, exist_ok=True)
    for inner_zip in inner_zips:
        _safe_extract(inner_zip, inner_dir)

    geojsons = _find_geojsons(inner_dir)
    if not geojsons:
        raise TdeiApiError('No GeoJSON files found in the OSW package.')
    return _sort_geojsons(geojsons)


def list_datasets(token):
    """Return dataset rows as (tdei_dataset_id, name) tuples."""
    data = _json_request(
        DATASETS_URL,
        method='GET',
        headers={
            'Accept': 'application/json',
            'Authorization': 'Bearer {}'.format(token),
        })
    return parse_dataset_rows(data)


def parse_dataset_rows(payload):
    """Map a datasets JSON payload to (tdei_dataset_id, name) rows.

    ``name`` is read from ``metadata.dataset_detail.name``.
    """
    items = _as_dataset_list(payload)
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dataset_id = item.get('tdei_dataset_id') or ''
        metadata = item.get('metadata') or {}
        if not isinstance(metadata, dict):
            metadata = {}
        detail = metadata.get('dataset_detail') or {}
        if not isinstance(detail, dict):
            detail = {}
        name = detail.get('name') or ''
        rows.append((str(dataset_id), str(name)))
    return rows


def _as_dataset_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('datasets', 'data', 'items', 'results'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _binary_request(url, headers, timeout):
    data, _status, _headers = _open_request(
        url, method='GET', headers=headers, timeout=timeout)
    return data


def _open_request(url, method, headers, body=None, timeout=30):
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            status = getattr(response, 'status', 200)
            return data, status, dict(response.headers)
    except HTTPError as exc:
        raise TdeiApiError(
            _error_message(exc), status_code=exc.code) from exc
    except URLError as exc:
        raise TdeiApiError(
            'Could not reach TDEI: {}'.format(exc.reason)) from exc


def _safe_extract(zip_path, dest_dir):
    dest_dir = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path, 'r') as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = info.filename.replace('\\', '/')
            if member.startswith('/') or any(
                    part == '..' for part in member.split('/')):
                continue
            target = os.path.abspath(os.path.join(dest_dir, member))
            if not (target == dest_dir or target.startswith(dest_dir + os.sep)):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, 'wb') as out:
                out.write(source.read())


def _find_geojsons(root):
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            lower = name.lower()
            if lower == 'metadata.json':
                continue
            if lower.endswith('.geojson'):
                found.append(os.path.join(dirpath, name))
    return found


def _find_zips(root):
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith('.zip'):
                found.append(os.path.join(dirpath, name))
    return found


def _sort_geojsons(paths):
    def key(path):
        name = os.path.basename(path).lower()
        for index, token in enumerate(_GEOJSON_ORDER):
            if token in name:
                return (index, name)
        return (len(_GEOJSON_ORDER), name)

    return sorted(paths, key=key)


def _non_zip_message(data):
    try:
        payload = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 'Download did not return a zip file.'
    if isinstance(payload, dict):
        for key in ('message', 'error', 'detail', 'title'):
            value = payload.get(key)
            if value:
                return str(value)
    return 'Download did not return a zip file.'


def _json_request(url, method, headers, body=None):
    raw_bytes, status, _headers = _open_request(
        url, method=method, headers=headers, body=body, timeout=30)
    raw = raw_bytes.decode('utf-8') if raw_bytes else ''
    if not raw:
        if 200 <= status < 300:
            return {}
        raise TdeiApiError('Empty response from TDEI.', status_code=status)

    try:
        return json.loads(raw)
    except ValueError as exc:
        raise TdeiApiError('TDEI returned invalid JSON.') from exc


def _error_message(exc):
    raw = exc.read().decode('utf-8', errors='replace')
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        for key in ('message', 'error', 'detail', 'title'):
            value = payload.get(key)
            if value:
                return str(value)
    if exc.code == 401:
        return 'Not authorized. Please sign in again.'
    if raw:
        return raw
    return 'TDEI request failed (HTTP {}).'.format(exc.code)


def submit_job(token, url, json_body=None, files=None, fields=None):
    """POST a TDEI job. ``files`` is {name: filepath}, ``fields`` is extra form text."""
    headers = {
        'Accept': 'application/json',
        'Authorization': 'Bearer {}'.format(token),
    }
    if files:
        body, content_type = _encode_multipart(fields or {}, files)
        headers['Content-Type'] = content_type
        data, _status, response_headers = _open_request(
            url, method='POST', headers=headers, body=body, timeout=60)
    elif json_body is not None:
        headers['Content-Type'] = 'application/json'
        data, _status, response_headers = _open_request(
            url,
            method='POST',
            headers=headers,
            body=json.dumps(json_body).encode('utf-8'),
            timeout=60)
    else:
        data, _status, response_headers = _open_request(
            url, method='POST', headers=headers, timeout=60)
    result = _parse_job_response(data)
    location = (
        response_headers.get('Location')
        or response_headers.get('location'))
    if location and 'location' not in result:
        result['location'] = location
    return result


def _parse_job_response(data):
    if not data:
        return {}
    raw = data.decode('utf-8', errors='replace').strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {'job_id': raw, '_raw': raw}
    if isinstance(parsed, dict):
        return parsed
    return {'job_id': str(parsed)}


def _encode_multipart(fields, files):
    boundary = '----TdeiBoundary7MA4YWxkTrZu0gW'
    chunks = []

    def add_field(name, value):
        chunks.append('--{}\r\n'.format(boundary).encode('utf-8'))
        chunks.append(
            'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(
                name).encode('utf-8'))
        chunks.append('{}'.format(value).encode('utf-8'))
        chunks.append(b'\r\n')

    for name, value in fields.items():
        if value is None or value == '':
            continue
        add_field(name, value)
    for name, path in files.items():
        if not path:
            continue
        filename = os.path.basename(path)
        with open(path, 'rb') as handle:
            payload = handle.read()
        chunks.append('--{}\r\n'.format(boundary).encode('utf-8'))
        chunks.append(
            'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
                name, filename).encode('utf-8'))
        chunks.append(b'Content-Type: application/octet-stream\r\n\r\n')
        chunks.append(payload)
        chunks.append(b'\r\n')
    chunks.append('--{}--\r\n'.format(boundary).encode('utf-8'))
    return b''.join(chunks), 'multipart/form-data; boundary={}'.format(boundary)
