# -*- coding: utf-8 -*-
"""Read and validate OSW package ``metadata.json`` (dataset area)."""

from __future__ import annotations

import json
import os
import zipfile
from typing import Any, List, Optional

DATASET_AREA_FILENAME = "dataset_area.geojson"

_GEOJSON_TYPES = frozenset(
    (
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
        "Feature",
        "FeatureCollection",
    )
)


def find_metadata_path(root: str) -> Optional[str]:
    """Return the first ``metadata.json`` under *root*, if any."""
    if not root or not os.path.isdir(root):
        return None
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower() == "metadata.json":
                return os.path.join(dirpath, name)
    return None


def load_metadata_dict(cache_dir: str) -> Optional[dict]:
    """Load package metadata from extracted files or ``package.zip``."""
    if not cache_dir:
        return None
    path = find_metadata_path(cache_dir)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, TypeError, UnicodeDecodeError):
            return None

    zip_path = os.path.join(cache_dir, "package.zip")
    if not (os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0):
        return None
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = info.filename.replace("\\", "/")
                if os.path.basename(member).lower() != "metadata.json":
                    continue
                raw = archive.read(info)
                payload = json.loads(raw.decode("utf-8"))
                return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, UnicodeDecodeError, zipfile.BadZipFile):
        return None
    return None


def dataset_area_value(metadata: Optional[dict]) -> Any:
    """Return ``dataset_detail.dataset_area`` from metadata (or nested)."""
    if not isinstance(metadata, dict):
        return None
    detail = metadata.get("dataset_detail")
    if not isinstance(detail, dict):
        nested = metadata.get("metadata")
        if isinstance(nested, dict):
            detail = nested.get("dataset_detail")
    if not isinstance(detail, dict):
        return None
    return detail.get("dataset_area")


def raw_has_valid_dataset_area(raw: Any) -> bool:
    """True when a datasets API item embeds a valid ``dataset_area``."""
    if not isinstance(raw, dict):
        return False
    area = dataset_area_value(raw.get("metadata"))
    if area is None:
        area = dataset_area_value(raw)
    if area is None:
        for key in ("dataset_area", "datasetArea"):
            if key in raw:
                area = raw.get(key)
                break
        if area is None:
            metadata = raw.get("metadata")
            if isinstance(metadata, dict):
                for key in ("dataset_area", "datasetArea"):
                    if key in metadata:
                        area = metadata.get(key)
                        break
    if normalize_dataset_area_geojson(area) is not None:
        return True
    return bool(is_valid_dataset_area(area))


def is_valid_dataset_area(value: Any) -> bool:
    """True when *value* is non-null GeoJSON (object or JSON string)."""
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("null", "none", "{}"):
            return False
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return False
    if not isinstance(value, dict):
        return False
    geo_type = value.get("type")
    if not isinstance(geo_type, str) or geo_type not in _GEOJSON_TYPES:
        return False
    if geo_type == "Feature":
        geometry = value.get("geometry")
        return is_valid_dataset_area(geometry) if geometry is not None else False
    if geo_type == "FeatureCollection":
        features = value.get("features")
        if not isinstance(features, list) or not features:
            return False
        return any(is_valid_dataset_area(feature) for feature in features)
    if geo_type == "GeometryCollection":
        geometries = value.get("geometries")
        if not isinstance(geometries, list) or not geometries:
            return False
        return any(is_valid_dataset_area(geom) for geom in geometries)
    coords = value.get("coordinates")
    return _coordinates_nonempty(coords)


def normalize_dataset_area_geojson(value: Any) -> Optional[dict]:
    """Return a FeatureCollection/Feature dict suitable for a .geojson file."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return None
    if not is_valid_dataset_area(value):
        return None
    assert isinstance(value, dict)
    geo_type = value.get("type")
    if geo_type in ("Feature", "FeatureCollection"):
        return value
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "dataset_area"},
                "geometry": value,
            }
        ],
    }


def dataset_area_file_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, DATASET_AREA_FILENAME)


def ensure_dataset_area_file(cache_dir: str) -> Optional[str]:
    """Write ``dataset_area.geojson`` into this dataset's cache folder.

    Path layout: ``tdei_osw_cache/<env>/<dataset_id>/dataset_area.geojson``
    — one file per dataset (never shared across datasets).

    Returns the file path, or ``None`` when area is missing/invalid.
    """
    if not cache_dir:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    dest = dataset_area_file_path(cache_dir)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    metadata = load_metadata_dict(cache_dir)
    payload = normalize_dataset_area_geojson(dataset_area_value(metadata))
    if payload is None:
        return None
    try:
        with open(dest, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        return None
    return dest if os.path.isfile(dest) else None


def with_dataset_area_path(
    cache_dir: str, map_paths: List[str]
) -> List[str]:
    """Ensure area file exists and is included once at the front of *map_paths*."""
    area_path = ensure_dataset_area_file(cache_dir)
    paths = list(map_paths or [])
    if not area_path:
        return paths
    filtered = [
        path
        for path in paths
        if os.path.basename(path).lower() != DATASET_AREA_FILENAME
    ]
    return [area_path] + filtered


def load_geojson_file(path: str) -> Optional[dict]:
    """Load a GeoJSON object from *path*."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return None


def apply_dataset_area_to_metadata(cache_dir: str, area_geojson: Any) -> str:
    """Set ``dataset_detail.dataset_area`` in local ``metadata.json``.

    Returns the path of the written metadata file.
    """
    if not cache_dir:
        raise ValueError("Dataset cache folder is missing.")
    metadata = load_metadata_dict(cache_dir)
    if metadata is None:
        raise ValueError(
            "Local metadata.json not found — cannot update dataset area."
        )
    return write_metadata_with_dataset_area(cache_dir, metadata, area_geojson)


def metadata_from_dataset_raw(raw: Any) -> dict:
    """Return a deep copy of the full metadata object from a datasets API item."""
    if not isinstance(raw, dict):
        raise ValueError("Dataset response is missing.")
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError(
            "Dataset response has no metadata — cannot edit dataset area."
        )
    return json.loads(json.dumps(metadata))


def set_dataset_area_on_metadata(metadata: dict, area_geojson: Any) -> dict:
    """Mutate *metadata* so ``dataset_detail.dataset_area`` is *area_geojson*."""
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be an object.")
    area = normalize_dataset_area_geojson(area_geojson)
    if area is None:
        raise ValueError("Generated dataset area is not valid GeoJSON.")

    detail = metadata.get("dataset_detail")
    if isinstance(detail, dict):
        detail["dataset_area"] = area
        metadata["dataset_detail"] = detail
        return metadata

    nested = metadata.get("metadata")
    if isinstance(nested, dict) and isinstance(nested.get("dataset_detail"), dict):
        nested["dataset_detail"]["dataset_area"] = area
        return metadata

    metadata["dataset_detail"] = {"dataset_area": area}
    return metadata


def write_metadata_with_dataset_area(
    cache_dir: str, metadata: dict, area_geojson: Any
) -> str:
    """Patch *metadata* with area, write ``metadata.json`` under *cache_dir*."""
    if not cache_dir:
        raise ValueError("Dataset cache folder is missing.")
    set_dataset_area_on_metadata(metadata, area_geojson)

    path = find_metadata_path(cache_dir)
    if not path:
        path = os.path.join(cache_dir, "metadata.json")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise ValueError("Could not write metadata.json.") from exc
    return path


def has_valid_dataset_area(cache_dir: str) -> Optional[bool]:
    """Validate local package metadata.

    :returns:
        ``None`` if there is no local package to inspect,
        ``True`` if ``dataset_area`` is valid GeoJSON,
        ``False`` if the package exists but area is missing/invalid.
    """
    if not cache_dir or not os.path.isdir(cache_dir):
        return None
    area_file = dataset_area_file_path(cache_dir)
    if os.path.isfile(area_file) and os.path.getsize(area_file) > 0:
        return True
    has_zip = os.path.isfile(os.path.join(cache_dir, "package.zip"))
    has_extract = find_metadata_path(cache_dir) is not None or any(
        name.lower().endswith(".geojson")
        for _dp, _dn, filenames in os.walk(cache_dir)
        for name in filenames
        if name.lower() != DATASET_AREA_FILENAME
    )
    if not has_zip and not has_extract:
        return None
    metadata = load_metadata_dict(cache_dir)
    if metadata is None:
        return False
    return is_valid_dataset_area(dataset_area_value(metadata))


def _coordinates_nonempty(coords: Any) -> bool:
    if coords is None:
        return False
    if isinstance(coords, (int, float)):
        return True
    if isinstance(coords, (list, tuple)):
        if not coords:
            return False
        return any(_coordinates_nonempty(item) for item in coords)
    return False
