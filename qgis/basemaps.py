# -*- coding: utf-8 -*-
"""XYZ basemap providers (streamed tiles — no offline map download)."""

from __future__ import annotations

from typing import Any, Dict

# Built into QGIS 3 via XYZ connection — no QuickMapServices / plugin dependency.
# Tiles are fetched on demand over the network while browsing the map.
BASEMAP_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openstreetmap": {
        "label": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "zmax": 19,
        "attribution": "© OpenStreetMap contributors",
    },
    "google_roadmap": {
        "label": "Google Maps",
        "url": "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        "zmax": 20,
        "attribution": "© Google",
    },
    "google_satellite": {
        "label": "Google Satellite",
        "url": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "zmax": 20,
        "attribution": "© Google",
    },
    "none": {
        "label": "None (no basemap)",
        "url": "",
        "zmax": 0,
        "attribution": "",
    },
}

DEFAULT_BASEMAP = "openstreetmap"
BASEMAP_LAYER_PROPERTY = "tdei_basemap"
BASEMAP_PROVIDER_PROPERTY = "tdei_basemap_provider"
