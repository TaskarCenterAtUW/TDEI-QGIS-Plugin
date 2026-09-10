# -*- coding: utf-8 -*-
"""Helpers for dataset-bbox WGS84 west,south,east,north formatting."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple, Union


BBoxTuple = Tuple[float, float, float, float]


def normalize_wsen(
    west: float, south: float, east: float, north: float
) -> BBoxTuple:
    """Ensure west < east and south < north."""
    if west > east:
        west, east = east, west
    if south > north:
        south, north = north, south
    return (float(west), float(south), float(east), float(north))


def format_bbox_csv(bbox: Sequence[float]) -> str:
    """Comma-separated west,south,east,north for JobField values."""
    if len(bbox) != 4:
        raise ValueError("bbox must have exactly 4 values")
    west, south, east, north = normalize_wsen(*bbox)
    return "{},{},{},{}".format(west, south, east, north)


def parse_bbox_csv(text: str) -> BBoxTuple:
    parts = [part.strip() for part in (text or "").split(",") if part.strip()]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    values = tuple(float(part) for part in parts)
    return normalize_wsen(*values)


def bbox_as_list(bbox: Union[str, Sequence[float]]) -> List[float]:
    if isinstance(bbox, str):
        return list(parse_bbox_csv(bbox))
    if len(bbox) != 4:
        raise ValueError("bbox must have exactly 4 values")
    return list(normalize_wsen(*bbox))
