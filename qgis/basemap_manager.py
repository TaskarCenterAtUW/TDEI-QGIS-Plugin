# -*- coding: utf-8 -*-
"""Ensure a streamed XYZ basemap is present under TDEI layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qgis.core import QgsProject, QgsRasterLayer

from ..logging.logger import get_logger
from .basemaps import (
    BASEMAP_LAYER_PROPERTY,
    BASEMAP_PROVIDER_PROPERTY,
    BASEMAP_PROVIDERS,
    DEFAULT_BASEMAP,
)

if TYPE_CHECKING:
    from ..config.settings import SettingsManager

LOG = get_logger(__name__)


class BasemapManager:
    """Adds/replaces an XYZ tile basemap from plugin settings.

    No map package download is required — QGIS requests tiles while panning/zooming.
    """

    def __init__(self, settings: "SettingsManager") -> None:
        self._settings = settings

    def configured_provider(self) -> str:
        key = str(
            self._settings.get("basemap.provider", DEFAULT_BASEMAP)
            or DEFAULT_BASEMAP
        )
        if key not in BASEMAP_PROVIDERS:
            return DEFAULT_BASEMAP
        return key

    def ensure_basemap(
        self, provider: Optional[str] = None
    ) -> Optional[QgsRasterLayer]:
        """Ensure the selected basemap exists at the bottom of the layer tree."""
        key = provider or self.configured_provider()
        if key == "none":
            self._remove_tdei_basemap()
            return None

        meta = BASEMAP_PROVIDERS.get(key) or BASEMAP_PROVIDERS[DEFAULT_BASEMAP]
        existing = self._find_tdei_basemap()
        if existing is not None:
            current = str(existing.customProperty(BASEMAP_PROVIDER_PROPERTY) or "")
            if current == key and existing.isValid():
                self._move_to_bottom(existing)
                return existing
            self._remove_layer(existing)

        layer = self._create_xyz_layer(key, meta)
        if layer is None or not layer.isValid():
            LOG.warning("Failed to create basemap layer for %s", key)
            return None

        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        root = project.layerTreeRoot()
        root.insertLayer(-1, layer)
        LOG.info("Basemap added: %s", meta["label"])
        return layer

    def _create_xyz_layer(self, key: str, meta: dict) -> Optional[QgsRasterLayer]:
        url = meta.get("url") or ""
        if not url:
            return None
        encoded_url = url.replace("{", "%7B").replace("}", "%7D")
        zmax = int(meta.get("zmax") or 19)
        uri = "type=xyz&url={url}&zmax={zmax}&zmin=0".format(
            url=encoded_url, zmax=zmax
        )
        layer = QgsRasterLayer(uri, meta["label"], "wms")
        if not layer.isValid():
            return None
        layer.setCustomProperty(BASEMAP_LAYER_PROPERTY, "1")
        layer.setCustomProperty(BASEMAP_PROVIDER_PROPERTY, key)
        attribution = meta.get("attribution") or ""
        if attribution:
            layer.setTitle(meta["label"])
            layer.setAbstract(attribution)
        return layer

    def _find_tdei_basemap(self) -> Optional[QgsRasterLayer]:
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsRasterLayer):
                continue
            if layer.customProperty(BASEMAP_LAYER_PROPERTY):
                return layer
        return None

    def _remove_tdei_basemap(self) -> None:
        layer = self._find_tdei_basemap()
        if layer is not None:
            self._remove_layer(layer)

    @staticmethod
    def _remove_layer(layer: QgsRasterLayer) -> None:
        QgsProject.instance().removeMapLayer(layer.id())

    @staticmethod
    def _move_to_bottom(layer: QgsRasterLayer) -> None:
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        if node is None:
            return
        clone = node.clone()
        parent = node.parent()
        if parent is None:
            return
        parent.insertChildNode(-1, clone)
        parent.removeChildNode(node)
