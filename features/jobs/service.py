# -*- coding: utf-8 -*-
"""OpenAPI-driven TDEI job definitions and request building."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

from ...api.v1.jobs import parse_jobs
from ...config.environment import resolve_environment
from ...core.exceptions import UnexpectedApiError
from ...core.models import (
    DatasetLocalState,
    JobDefinition,
    JobField,
    JobLoadResult,
    JobRecord,
    JobSubmissionResult,
    MappedItem,
)
from ...features.osw.package import is_map_filename, unpack_map_package
from ...logging.logger import get_logger

if False:  # TYPE_CHECKING without circular import at runtime
    pass

LOG = get_logger(__name__)

SPEC_FILENAME = "tdei_jobs_spec.json"
SELF_MERGE_PATH = "/api/v1/osw/self-merge"
DATASET_BBOX_PATH = "/api/v1/osw/dataset-bbox"
# Layer-tree menu: OSW operations that need local layer packages.
LAYER_MENU_JOBS = (
    ("/api/v1/osw/validate", "Validate"),
    ("/api/v1/osw/sanitize", "Sanitize"),
    ("/api/v1/osw/convert", "Convert"),
)
# Datasets list ⋮ menu — dataset-id jobs (extend with more paths later).
DATASET_ROW_JOBS = (
    (SELF_MERGE_PATH, "Self Merge"),
)
# Placeholder until the user submits; zip is built then (or they browse to override).
PENDING_OSW_ZIP = "__tdei_pending_osw_zip__"
_DATASET_FIELD_NAMES = (
    "tdei_dataset_id",
    "tdei_dataset_id_one",
    "tdei_dataset_id_two",
    "source_dataset_id",
    "target_dataset_id",
)
# Synthetic OpenAPI-like operation — not in the bundled union schema.
SELF_MERGE_OPERATION = {
    "summary": "Self Merge",
    "description": (
        "Merges overlapping nodes, edges, and polygons within a single OSW "
        "dataset using a proximity threshold."
    ),
    "operationId": "oswSelfMerge",
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["tdei_dataset_id"],
                    "properties": {
                        "tdei_dataset_id": {
                            "type": "string",
                            "description": "Dataset id to self-merge",
                        },
                        "proximity": {
                            "type": "number",
                            "description": (
                                "Proximity in meters to identify equivalent "
                                "nodes. Default is 0.5."
                            ),
                            "example": 0.5,
                        },
                    },
                }
            }
        },
    },
}


class JobService:
    def __init__(self, api_client, layer_manager, settings) -> None:
        self._api = api_client
        self._layers = layer_manager
        self._settings = settings
        self._spec: Optional[Dict[str, Any]] = None

    def list_jobs(self) -> List[JobDefinition]:
        spec = self._load_spec()
        jobs: List[JobDefinition] = []
        for path, methods in (spec.get("paths") or {}).items():
            operation = (methods or {}).get("post")
            if not operation:
                continue
            jobs.append(
                JobDefinition(
                    title=operation.get("summary")
                    or operation.get("operationId")
                    or path,
                    path=path,
                    method="POST",
                    operation=operation,
                )
            )
        jobs.sort(key=lambda item: item.title.lower())
        return jobs

    def list_layer_menu_jobs(self) -> List[JobDefinition]:
        """Jobs offered on the QGIS layer-tree context menu."""
        return self._jobs_for_menu(LAYER_MENU_JOBS)

    def list_dataset_row_jobs(self) -> List[JobDefinition]:
        """Jobs offered on the Datasets list ⋮ overflow menu."""
        return self._jobs_for_menu(DATASET_ROW_JOBS)

    def _jobs_for_menu(self, menu_jobs) -> List[JobDefinition]:
        by_path = {job.path: job for job in self.list_jobs()}
        ordered: List[JobDefinition] = []
        for path, label in menu_jobs:
            if path == SELF_MERGE_PATH:
                ordered.append(
                    JobDefinition(
                        title=label,
                        path=SELF_MERGE_PATH,
                        method="POST",
                        operation=dict(SELF_MERGE_OPERATION),
                    )
                )
                continue
            job = by_path.get(path)
            if job is None:
                continue
            ordered.append(
                JobDefinition(
                    title=label,
                    path=job.path,
                    method=job.method,
                    operation=job.operation,
                )
            )
        return ordered

    def form_fields(
        self, job: JobDefinition, dataset_id: Optional[str] = None
    ) -> List[JobField]:
        spec = self._load_spec()
        operation = job.operation
        fields: List[JobField] = []
        for param in operation.get("parameters") or []:
            param = resolve_ref(param, spec)
            if param.get("in") == "path":
                continue
            schema = resolve_ref(param.get("schema") or {}, spec)
            fields.append(
                _field_from_schema(
                    name=param.get("name"),
                    location=param.get("in") or "query",
                    schema=schema,
                    required=bool(param.get("required")),
                    description=param.get("description")
                    or schema.get("description")
                    or "",
                    spec=spec,
                )
            )
        body = operation.get("requestBody")
        if body:
            body = resolve_ref(body, spec)
            content = body.get("content") or {}
            if "application/json" in content:
                schema = resolve_ref(
                    content["application/json"].get("schema") or {}, spec
                )
                required = set(schema.get("required") or [])
                for name, prop in (schema.get("properties") or {}).items():
                    prop = resolve_ref(prop, spec)
                    fields.append(
                        _field_from_schema(
                            name=name,
                            location="json",
                            schema=prop,
                            required=name in required,
                            description=prop.get("description") or "",
                            spec=spec,
                        )
                    )
            elif "multipart/form-data" in content:
                schema = resolve_ref(
                    content["multipart/form-data"].get("schema") or {}, spec
                )
                required = set(schema.get("required") or [])
                for name, prop in (schema.get("properties") or {}).items():
                    prop = resolve_ref(prop, spec)
                    fields.append(
                        _field_from_schema(
                            name=name,
                            location="form",
                            schema=prop,
                            required=name in required,
                            description=prop.get("description") or "",
                            spec=spec,
                        )
                    )
        if dataset_id:
            for field in fields:
                if field.name in _DATASET_FIELD_NAMES:
                    field.value = dataset_id
                elif field.name == "proximity" and field.value in (None, ""):
                    field.value = 1
        return fields

    def build_request(
        self,
        job: JobDefinition,
        fields: List[JobField],
        values: Dict[str, Any],
        dataset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        env = resolve_environment(self._settings)
        path = job.path
        path_params = re.findall(r"\{([^}]+)\}", path)
        for name in path_params:
            path = path.replace(
                "{" + name + "}",
                quote(str(values.get(name) or dataset_id or ""), safe=""),
            )
        # Host without /api/v1 suffix for OpenAPI paths that include /api/v1
        host = env.api_base_url
        if host.endswith("/api/v1"):
            host = host[: -len("/api/v1")]
        url = host + path
        query = []
        json_body: Dict[str, Any] = {}
        form_fields_out: Dict[str, Any] = {}
        files: Dict[str, str] = {}
        has_json = False
        has_form = False
        for field in fields:
            name = field.name
            value = values.get(name)
            location = field.location
            if location == "query":
                if value in (None, ""):
                    if field.required:
                        raise ValueError("{} is required".format(name))
                    continue
                if field.type == "array" and isinstance(value, str):
                    value = [
                        part.strip()
                        for part in value.split(",")
                        if part.strip()
                    ]
                if isinstance(value, list):
                    for item in value:
                        query.append((name, item))
                else:
                    query.append((name, value))
            elif location == "json":
                has_json = True
                if value in (None, ""):
                    if field.required:
                        raise ValueError("{} is required".format(name))
                    continue
                json_body[name] = _coerce(field, value)
            elif location == "form":
                has_form = True
                if field.format == "binary":
                    if not value and field.required:
                        raise ValueError("{} is required".format(name))
                    if value:
                        files[name] = value
                else:
                    if value in (None, "") and field.required:
                        raise ValueError("{} is required".format(name))
                    if value not in (None, ""):
                        form_fields_out[name] = value
        if query:
            url = "{}?{}".format(url, urlencode(query, doseq=True))
        return {
            "url": url,
            "json_body": json_body if has_json else None,
            "fields": form_fields_out if has_form else None,
            "files": files if has_form else None,
        }

    def submit(
        self,
        job: JobDefinition,
        fields: List[JobField],
        values: Dict[str, Any],
        dataset_id: Optional[str] = None,
    ) -> JobSubmissionResult:
        request = self.build_request(job, fields, values, dataset_id=dataset_id)
        if request["files"] or request["fields"]:
            raw = self._api.post_multipart(
                request["url"],
                fields=request["fields"],
                files=request["files"],
            )
        else:
            raw = self._api.post_json_url(
                request["url"], request["json_body"]
            )
        job_id = str(
            raw.get("job_id") or raw.get("jobId") or raw.get("id") or ""
        )
        return JobSubmissionResult(
            job_id=job_id,
            location=str(raw.get("location") or ""),
            raw=raw,
        )

    def job_by_path(self, path: str) -> Optional[JobDefinition]:
        for job in self.list_jobs():
            if job.path == path:
                return job
        return None

    def submit_dataset_bbox(
        self,
        dataset_id: str,
        bbox,
        file_type: str = "osw",
    ) -> JobSubmissionResult:
        """Submit POST /api/v1/osw/dataset-bbox for a WGS84 W,S,E,N clip."""
        from .bbox import format_bbox_csv, bbox_as_list

        job = self.job_by_path(DATASET_BBOX_PATH)
        if job is None:
            raise UnexpectedApiError(
                "dataset-bbox job is not available in the OpenAPI spec."
            )
        fields = self.form_fields(job, dataset_id=dataset_id)
        if isinstance(bbox, str):
            bbox_value = format_bbox_csv(bbox_as_list(bbox))
        else:
            bbox_value = format_bbox_csv(bbox)
        values = {
            "tdei_dataset_id": dataset_id,
            "file_type": file_type or "osw",
            "bbox": bbox_value,
        }
        return self.submit(job, fields, values, dataset_id=dataset_id)

    def is_osw_package_field(self, field: JobField) -> bool:
        if field.format != "binary":
            return False
        if field.name in ("dataset", "file"):
            return True
        description = (field.description or "").lower()
        return "zip" in description and (
            "geojson" in description
            or "osw dataset" in description
            or "osw" in description
        )

    def needs_osw_package(self, fields: List[JobField]) -> bool:
        return any(self.is_osw_package_field(field) for field in fields)

    def resolve_pending_uploads(
        self,
        fields: List[JobField],
        values: Dict[str, Any],
        dataset_id: str,
        *,
        progress=None,
    ) -> Dict[str, Any]:
        """Build the OSW zip when the form still has the pending placeholder."""
        resolved = dict(values)
        for field in fields:
            if not self.is_osw_package_field(field):
                continue
            current = resolved.get(field.name)
            if current and current != PENDING_OSW_ZIP and os.path.isfile(
                str(current)
            ):
                continue
            if progress is not None:
                progress(35, "Preparing OSW package…")
            resolved[field.name] = self.prepare_osw_upload(dataset_id)
        return resolved

    def prepare_osw_upload(self, dataset_id: str) -> str:
        return self._layers.prepare_osw_package_zip(dataset_id)

    def submit_from_layer(
        self,
        job: JobDefinition,
        fields: List[JobField],
        values: Dict[str, Any],
        dataset_id: str,
        *,
        progress=None,
    ) -> JobSubmissionResult:
        """Zip (if needed) then upload — safe to run on a worker thread."""
        if progress is not None:
            progress(10, "Preparing job…")
        resolved = self.resolve_pending_uploads(
            fields, values, dataset_id, progress=progress
        )
        if progress is not None:
            progress(55, "Uploading job…")
        result = self.submit(
            job, fields, resolved, dataset_id=dataset_id
        )
        if progress is not None:
            progress(100, "Job submitted")
        return result

    def fetch_jobs(
        self,
        project_group_id: str,
        *,
        page_no: int = 1,
        page_size: int = 10,
        show_group_jobs: bool = True,
        job_id: str = "",
        status: str = "",
    ) -> List[JobRecord]:
        """List jobs for a project group from the gateway jobs API."""
        group_id = str(project_group_id or "").strip()
        if not group_id:
            return []
        params = {
            "page_no": max(1, int(page_no)),
            "page_size": max(1, min(int(page_size), 50)),
            "tdei_project_group_id": group_id,
            "show_group_jobs": bool(show_group_jobs),
        }
        job_id = str(job_id or "").strip()
        if job_id:
            params["job_id"] = job_id
        status = str(status or "").strip()
        if status and status.lower() != "all":
            params["status"] = status
        payload = self._api.get("jobs", params=params)
        jobs = parse_jobs(payload)
        LOG.info("Loaded %s jobs for project group", len(jobs))
        return jobs

    def local_state(self, job: JobRecord) -> DatasetLocalState:
        if self._layers.is_dataset_loaded(job.map_key):
            return DatasetLocalState.LOADED
        if self._has_local_package(job.map_key):
            return DatasetLocalState.CACHED
        return DatasetLocalState.REMOTE

    def prepare_package(self, job: JobRecord):
        """Download/extract job output (background-safe). Returns (paths, source)."""
        if not job.has_download:
            raise ValueError("This job has no download URL.")
        cache_dir = self._layers.cache_dir_for(job.map_key)
        zip_path = os.path.join(cache_dir, "package.zip")
        extract_dir = os.path.join(cache_dir, "extracted")
        map_files = self._existing_map_files(cache_dir)
        if map_files:
            return map_files, "cache"
        if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0:
            map_files = self._unpack_job_archive(zip_path, extract_dir)
            return map_files, "cache"
        LOG.info("Downloading job output for %s", job.id)
        data = self._api.download_bytes(job.download_url)
        if data[:2] == b"PK":
            parent = os.path.dirname(zip_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(zip_path, "wb") as handle:
                handle.write(data)
            map_files = self._unpack_job_archive(zip_path, extract_dir)
            return map_files, "download"
        # Raw .osm / geojson payload (not zipped)
        dest = self._write_raw_map_file(cache_dir, data)
        return [dest], "download"

    def add_to_map(
        self,
        job: JobRecord,
        file_paths: List[str],
        source: str,
        *,
        display_name: str = "",
        zoom: bool = True,
    ) -> JobLoadResult:
        if self._layers.is_dataset_loaded(job.map_key):
            if zoom:
                self._layers.zoom_to_dataset(job.map_key)
            return JobLoadResult(
                job_id=job.id, layer_count=0, source="already_loaded"
            )
        layers = self._layers.load_vector_files(
            job.map_key,
            file_paths,
            display_name=display_name or job.display_type,
            zoom=zoom,
        )
        return JobLoadResult(
            job_id=job.id, layer_count=len(layers), source=source
        )

    def remove_from_map(
        self, map_key: str, *, clear_cache: bool = True
    ) -> bool:
        """Remove job layers from QGIS and optionally wipe local cache."""
        removed = self._layers.remove_dataset_group(map_key)
        if clear_cache:
            self._layers.clear_cache(map_key)
        return removed

    def list_mapped(self) -> List[MappedItem]:
        return self._layers.list_mapped_items(jobs=True)

    def _has_local_package(self, map_key: str) -> bool:
        cache_dir = self._layers.cache_path_for(map_key)
        zip_path = os.path.join(cache_dir, "package.zip")
        if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0:
            return True
        return bool(self._existing_map_files(cache_dir))

    @classmethod
    def _existing_map_files(cls, cache_dir: str) -> List[str]:
        found: List[str] = []
        if not os.path.isdir(cache_dir):
            return found
        for dirpath, _dirnames, filenames in os.walk(cache_dir):
            for name in filenames:
                if is_map_filename(name):
                    found.append(os.path.join(dirpath, name))
        return found

    @classmethod
    def _unpack_job_archive(cls, zip_path: str, dest_dir: str) -> List[str]:
        """Extract zip; accept GeoJSON and OSM files at any depth."""
        files = unpack_map_package(
            zip_path,
            dest_dir,
            extensions=(".geojson", ".osm", ".osm.xml", ".pbf"),
        )
        if not files:
            raise UnexpectedApiError(
                "Job package has no GeoJSON or OSM files to load."
            )
        return files

    @staticmethod
    def _write_raw_map_file(cache_dir: str, data: bytes) -> str:
        os.makedirs(cache_dir, exist_ok=True)
        text_head = data[:200].lstrip().lower()
        if text_head.startswith(b"{") or b'"type"' in text_head[:80]:
            path = os.path.join(cache_dir, "output.geojson")
        else:
            path = os.path.join(cache_dir, "output.osm")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _load_spec(self) -> Dict[str, Any]:
        if self._spec is not None:
            return self._spec
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        path = os.path.join(root, SPEC_FILENAME)
        with open(path) as handle:
            self._spec = json.load(handle)
        return self._spec


def resolve_ref(node: Any, spec: Dict[str, Any]) -> Any:
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    pointer = node["$ref"].lstrip("#/").split("/")
    resolved: Any = spec
    for part in pointer:
        resolved = resolved[part]
    return resolved


def _field_from_schema(
    name, location, schema, required, description, spec
) -> JobField:
    schema = resolve_ref(schema, spec)
    default = schema.get("default")
    return JobField(
        name=name,
        location=location,
        required=required,
        type=schema.get("type") or "string",
        format=schema.get("format"),
        enum=schema.get("enum"),
        description=description or schema.get("description") or "",
        value="" if default is None else default,
    )


def _coerce(field: JobField, value: Any) -> Any:
    if field.type == "number":
        return float(value)
    if field.type == "integer":
        return int(value)
    if field.type == "boolean":
        return bool(value)
    if field.type == "array" and isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]
    return value
