# -*- coding: utf-8 -*-
"""OSW zip extraction (no QGIS dependency)."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from typing import List

from ...core.exceptions import UnexpectedApiError, ValidationError

_GEOJSON_ORDER = ("nodes", "edges", "lines", "points", "polygons", "zones")


def unpack_osw_package(zip_path: str, dest_dir: str) -> List[str]:
    """Extract a TDEI OSW zip and return GeoJSON file paths."""
    files = unpack_map_package(
        zip_path, dest_dir, extensions=(".geojson",)
    )
    if not files:
        raise UnexpectedApiError("No GeoJSON files found in the OSW package.")
    return _sort_geojsons(files)


def unpack_map_package(
    zip_path: str,
    dest_dir: str,
    *,
    extensions: tuple = (".geojson", ".osm", ".osm.xml", ".pbf"),
) -> List[str]:
    """Extract a zip and return map file paths (GeoJSON and/or OSM).

    Files are discovered at any depth under the extract tree (and nested zips).
    """
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    _safe_extract(zip_path, dest_dir)

    found = _find_map_files(dest_dir, extensions)
    if found:
        return _sort_geojsons(found) if extensions == (".geojson",) else found

    inner_zips = _find_zips(dest_dir)
    if not inner_zips:
        return []

    inner_dir = os.path.join(dest_dir, "_inner")
    os.makedirs(inner_dir, exist_ok=True)
    for inner_zip in inner_zips:
        _safe_extract(inner_zip, inner_dir)

    found = _find_map_files(inner_dir, extensions)
    if extensions == (".geojson",):
        return _sort_geojsons(found)
    return found


def is_map_filename(
    name: str,
    extensions: tuple = (".geojson", ".osm", ".osm.xml", ".pbf"),
) -> bool:
    """True if *name* looks like a loadable map file (any folder depth)."""
    lower = str(name).lower()
    if lower == "metadata.json" or lower.endswith(".zip"):
        return False
    return matches_map_extension(lower, extensions)


def matches_map_extension(lower_name: str, extensions: tuple) -> bool:
    for ext in extensions:
        if lower_name.endswith(ext):
            return True
        # ``foo.osm.xml`` should match when callers ask for ``.osm``
        if ext == ".osm" and lower_name.endswith(".osm.xml"):
            return True
    return False


def zip_geojson_paths(paths: List[str], dest_zip: str) -> str:
    files = [path for path in paths if path and os.path.isfile(path)]
    if not files:
        raise ValidationError("No GeoJSON files to zip.")
    parent = os.path.dirname(dest_zip)
    if parent:
        os.makedirs(parent, exist_ok=True)
    used = set()
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = os.path.basename(path)
            stem, ext = os.path.splitext(name)
            candidate = name
            index = 2
            while candidate.lower() in used:
                candidate = "{}{}{}".format(stem, index, ext)
                index += 1
            used.add(candidate.lower())
            archive.write(path, candidate)
    return dest_zip


def assert_zip_bytes(data: bytes) -> None:
    if data[:2] != b"PK":
        raise UnexpectedApiError(_non_zip_message(data))


def _safe_extract(zip_path: str, dest_dir: str) -> None:
    dest_dir = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = info.filename.replace("\\", "/")
            if member.startswith("/") or any(
                part == ".." for part in member.split("/")
            ):
                continue
            target = os.path.abspath(os.path.join(dest_dir, member))
            if not (
                target == dest_dir or target.startswith(dest_dir + os.sep)
            ):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                out.write(source.read())


def _find_geojsons(root: str) -> List[str]:
    return _find_map_files(root, (".geojson",))


def _find_map_files(root: str, extensions: tuple) -> List[str]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if is_map_filename(name, extensions):
                found.append(os.path.join(dirpath, name))
    return found


def _find_zips(root: str) -> List[str]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".zip"):
                found.append(os.path.join(dirpath, name))
    return found


def _sort_geojsons(paths: List[str]) -> List[str]:
    def key(path: str):
        name = os.path.basename(path).lower()
        for index, token in enumerate(_GEOJSON_ORDER):
            if token in name:
                return (index, name)
        return (len(_GEOJSON_ORDER), name)

    return sorted(paths, key=key)


def _non_zip_message(data: bytes) -> str:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "Download did not return a zip file."
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "title"):
            value = payload.get(key)
            if value:
                return str(value)
    return "Download did not return a zip file."
