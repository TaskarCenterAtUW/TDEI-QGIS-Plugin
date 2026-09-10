# -*- coding: utf-8 -*-
"""OSW GeoJSON layer filename conventions for job uploads."""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

# Filenames must be (or end with) one of these OSW layer types.
OSW_GEOJSON_TYPES: Tuple[str, ...] = (
    "edges",
    "nodes",
    "lines",
    "zones",
    "polygons",
    "points",
)

# Preferred source for generating dataset_area (highest first).
DATASET_AREA_SOURCE_PRIORITY: Tuple[str, ...] = (
    "edges",
    "nodes",
    "zones",
    "polygons",
    "lines",
    "points",
)

OSW_GEOJSON_SUFFIXES: Tuple[str, ...] = tuple(
    ".{}.geojson".format(kind) for kind in OSW_GEOJSON_TYPES
)

SUPPORTED_OSW_GEOJSON_LABELS = tuple(
    "*.{}.geojson".format(kind) for kind in OSW_GEOJSON_TYPES
)


def supported_osw_geojson_types_text() -> str:
    return ", ".join(SUPPORTED_OSW_GEOJSON_LABELS)


def is_osw_convention_filename(filename: str) -> bool:
    """True when *filename* matches OSW upload naming (case-insensitive).

    Accepts ``nodes.geojson`` and ``demo.nodes.geojson`` (same for edges,
    lines, zones, polygons, points).
    """
    return osw_type_from_filename(filename) is not None


def osw_type_from_filename(filename: str) -> Optional[str]:
    """Return OSW layer kind (``edges``, ``nodes``, …) or ``None``."""
    name = os.path.basename(filename or "").strip().lower()
    if not name:
        return None
    for kind in OSW_GEOJSON_TYPES:
        exact = "{}.geojson".format(kind)
        if name == exact or name.endswith("." + exact):
            return kind
    return None


def pick_dataset_area_source(paths: Sequence[str]) -> Optional[str]:
    """Pick one GeoJSON path for area generation by priority order.

    Priority: edges → nodes → zones → polygons → lines → points.
    """
    by_kind = {}
    for path in paths or ():
        kind = osw_type_from_filename(path)
        if kind is None:
            continue
        # Keep the first path seen for each kind.
        by_kind.setdefault(kind, path)
    for kind in DATASET_AREA_SOURCE_PRIORITY:
        if kind in by_kind:
            return by_kind[kind]
    return None


def classify_osw_filenames(
    filenames: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Split filenames into (accepted, rejected) by OSW naming convention."""
    accepted: List[str] = []
    rejected: List[str] = []
    for name in filenames:
        label = (name or "").strip() or "(unnamed)"
        if is_osw_convention_filename(label):
            accepted.append(label)
        else:
            rejected.append(label)
    return accepted, rejected
