# -*- coding: utf-8 -*-
"""API v1 dataset helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from urllib.parse import quote

from ...core.models import Dataset


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Parse API boolean-ish values (bool / 0-1 / true|false strings)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().casefold()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off", ""):
        return False
    return default


def viewer_flags_from_item(item: Any) -> Tuple[bool, bool]:
    """Return ``(project_group_allowed, dataset_allowed)`` from a list item."""
    if not isinstance(item, dict):
        return False, False
    group = (
        item.get("project_group")
        or item.get("projectGroup")
        or item.get("project_group_details")
        or {}
    )
    if not isinstance(group, dict):
        group = {}
    group_allowed = coerce_bool(
        group.get("data_viewer_allowed", group.get("dataViewerAllowed")),
        default=False,
    )
    dataset_allowed = coerce_bool(
        item.get("data_viewer_allowed", item.get("dataViewerAllowed")),
        default=False,
    )
    return group_allowed, dataset_allowed


def parse_datasets(payload: Any) -> List[Dataset]:
    items = _as_list(payload)
    datasets: List[Dataset] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("tdei_dataset_id") or "")
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        detail = (
            metadata.get("dataset_detail")
            or metadata.get("datasetdetails")
            or metadata.get("datasetDetails")
            or {}
        )
        if not isinstance(detail, dict):
            detail = {}
        name = str(detail.get("name") or "")
        version = str(detail.get("version") or "").strip()
        uploaded = str(item.get("uploaded_timestamp") or "").strip()
        status = str(item.get("status") or "").strip()
        group_allowed, dataset_allowed = viewer_flags_from_item(item)
        datasets.append(
            Dataset(
                id=dataset_id,
                name=name,
                version=version,
                uploaded_timestamp=uploaded,
                status=status,
                data_viewer_allowed=dataset_allowed,
                project_group_data_viewer_allowed=group_allowed,
                raw=item,
            )
        )
    return datasets


def osw_download_path(dataset_id: str) -> str:
    return "osw/{}?format=osw&file_version=latest".format(
        quote(str(dataset_id), safe="")
    )


def osw_pmtiles_path(dataset_id: str) -> str:
    """Relative path for GET dataset-viewer PMTiles SAS URL."""
    return "osw/dataset-viewer/pm-tiles/{}".format(
        quote(str(dataset_id), safe="")
    )


def edit_metadata_path(dataset_id: str) -> str:
    """Relative path for PUT editMetadata (base already includes /api/v1)."""
    return "metadata/{}".format(quote(str(dataset_id), safe=""))


def _as_list(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("datasets", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
