# -*- coding: utf-8 -*-
"""Generate ``dataset_area.geojson`` via Concave Hull (fallback: Convex Hull)."""

from __future__ import annotations

import os
from typing import Tuple

from qgis.core import QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes

from ...logging.logger import get_logger
from .metadata import DATASET_AREA_FILENAME, dataset_area_file_path
from .naming import osw_type_from_filename, pick_dataset_area_source

LOG = get_logger(__name__)

# qgis:minimumboundinggeometry TYPE enum: 3 = Convex Hull (fallback)
_MBG_CONVEX_HULL = 3
# native:concavehull threshold — 0 = max concave, 1 ≈ convex
_CONCAVE_ALPHA = 0.3


def generate_dataset_area_geojson(
    cache_dir: str, source_paths: list
) -> Tuple[str, str]:
    """Build dataset area from the best OSW layer under *cache_dir*.

    Prefers QGIS ``native:concavehull`` (vertices extracted when needed).
    Falls back to ``qgis:minimumboundinggeometry`` Convex Hull.
    Writes ``dataset_area.geojson`` and returns ``(dest_path, source_kind)``.
    """
    if not cache_dir:
        raise ValueError("Dataset cache folder is missing.")
    source = pick_dataset_area_source(source_paths)
    if not source or not os.path.isfile(source):
        raise ValueError(
            "No OSW layer found to generate dataset area "
            "(need edges, nodes, zones, polygons, lines, or points)."
        )
    kind = osw_type_from_filename(source) or "layer"
    os.makedirs(cache_dir, exist_ok=True)
    dest = dataset_area_file_path(cache_dir)
    _run_concave_hull(source, dest)
    if not (os.path.isfile(dest) and os.path.getsize(dest) > 0):
        raise ValueError("Concave hull did not produce a dataset_area file.")
    LOG.info(
        "Generated %s from %s (%s)", DATASET_AREA_FILENAME, kind, source
    )
    return dest, kind


def _run_concave_hull(source_path: str, dest_path: str) -> None:
    layer = QgsVectorLayer(source_path, "tdei_area_source", "ogr")
    if not layer.isValid():
        raise ValueError(
            'Could not open layer "{}".'.format(os.path.basename(source_path))
        )
    if layer.featureCount() == 0:
        raise ValueError(
            'Layer "{}" has no features.'.format(os.path.basename(source_path))
        )

    try:
        import processing  # noqa: WPS433 — QGIS Processing API
    except ImportError as exc:
        raise ValueError(
            "QGIS Processing is required to generate dataset area."
        ) from exc

    points = _as_point_layer(processing, layer)
    hull = None
    if points is not None and points.featureCount() >= 3:
        for alg_id in ("native:concavehull", "qgis:concavehull"):
            try:
                hull = processing.run(
                    alg_id,
                    {
                        "INPUT": points,
                        "ALPHA": _CONCAVE_ALPHA,
                        "HOLES": False,
                        "NO_MULTIGEOMETRY": False,
                        "OUTPUT": "memory:",
                    },
                ).get("OUTPUT")
            except Exception:  # noqa: BLE001
                LOG.debug("Concave hull via %s failed", alg_id, exc_info=True)
                hull = None
            if hull is not None:
                break

    if hull is None:
        LOG.info("Falling back to convex hull for %s", source_path)
        hull = processing.run(
            "qgis:minimumboundinggeometry",
            {
                "INPUT": layer,
                "FIELD": "",
                "TYPE": _MBG_CONVEX_HULL,
                "OUTPUT": "memory:",
            },
        ).get("OUTPUT")

    if hull is None:
        raise ValueError("Hull algorithm produced no output.")

    if os.path.isfile(dest_path):
        try:
            os.remove(dest_path)
        except OSError:
            pass

    result = QgsVectorFileWriter.writeAsVectorFormat(
        hull, dest_path, "utf-8", hull.crs(), "GeoJSON"
    )
    error = result[0] if isinstance(result, tuple) else result
    if error != QgsVectorFileWriter.NoError:
        raise ValueError("Could not export dataset_area.geojson.")


def _as_point_layer(processing, layer: QgsVectorLayer):
    """Return a point layer suitable for concave hull (extract vertices if needed)."""
    try:
        geom_type = layer.geometryType()
    except Exception:  # noqa: BLE001
        geom_type = None
    if geom_type == QgsWkbTypes.PointGeometry:
        return layer
    try:
        return processing.run(
            "native:extractvertices",
            {"INPUT": layer, "OUTPUT": "memory:"},
        ).get("OUTPUT")
    except Exception:  # noqa: BLE001
        LOG.debug("extractvertices failed for concave hull", exc_info=True)
        return None
