# -*- coding: utf-8 -*-
"""QGIS layer group management for TDEI datasets."""

from __future__ import annotations

import os
import json
import shutil
import tempfile
from typing import TYPE_CHECKING, List, Optional

from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsLayerTreeGroup,
    QgsLayerTreeNode,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from ..features.mapped_tags.logic import parse_tags_payload, serialize_tags
from ..features.osw.package import zip_geojson_paths
from ..logging.logger import get_logger
from ..core.models import JOB_MAP_PREFIX, MappedItem

if TYPE_CHECKING:
    from qgis.gui import QgsInterface

LOG = get_logger(__name__)
PARENT_GROUP_NAME = "TDEI"
ROOT_PROPERTY = "tdei_root"
TAGS_SIDECAR = "tdei_tags.json"
META_SIDECAR = "tdei_meta.json"
MAP_SEARCH_GROUP_NAME = "TDEI Map Search"
MAP_SEARCH_GROUP_PROPERTY = "tdei_map_search_group"
MAP_SEARCH_LAYER_PROPERTY = "tdei_map_search"


class LayerManager:
    def __init__(
        self,
        iface: Optional["QgsInterface"] = None,
        env_key_provider=None,
    ) -> None:
        self._iface = iface
        self._env_key_provider = env_key_provider
        # Outline-only map-search focus (avoid QGIS default yellow selection fill).
        self._map_search_highlights: List = []

    def cache_environment_key(self) -> str:
        """Active environment key used to isolate on-disk downloads."""
        key = "development"
        if callable(self._env_key_provider):
            try:
                provided = self._env_key_provider()
                if provided:
                    key = str(provided)
            except Exception:  # noqa: BLE001
                pass
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_" for char in key
        )
        return safe or "development"

    def cache_root(self) -> str:
        """Profile-scoped OSW/job package cache root (per environment)."""
        return os.path.join(
            QgsApplication.qgisSettingsDirPath(),
            "tdei_osw_cache",
            self.cache_environment_key(),
        )

    def ensure_cache_root(self) -> str:
        path = self.cache_root()
        os.makedirs(path, exist_ok=True)
        return path

    def cache_path_for(self, dataset_id: str) -> str:
        """Return the cache folder path without creating it."""
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_"
            for char in str(dataset_id)
        )
        return os.path.join(self.cache_root(), safe)

    def cache_dir_for(self, dataset_id: str) -> str:
        """Return the cache folder, creating it only when needed for I/O."""
        path = self.cache_path_for(dataset_id)
        os.makedirs(path, exist_ok=True)
        return path

    def is_dataset_loaded(self, dataset_id: str) -> bool:
        return self.find_dataset_group(dataset_id) is not None

    def find_parent_group(self):
        """Find the stamped TDEI root, or a group named TDEI."""
        root = QgsProject.instance().layerTreeRoot()
        stamped = None
        named = None
        for child in root.children():
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if str(child.customProperty(ROOT_PROPERTY) or "") == "1":
                stamped = child
                break
            if child.name() == PARENT_GROUP_NAME and named is None:
                named = child
        if stamped is not None:
            return stamped
        if named is not None:
            # Adopt a legacy unstamped TDEI group.
            named.setCustomProperty(ROOT_PROPERTY, "1")
            return named
        return None

    def ensure_parent_group(self):
        parent = self.find_parent_group()
        if parent is not None:
            if str(parent.customProperty(ROOT_PROPERTY) or "") != "1":
                parent.setCustomProperty(ROOT_PROPERTY, "1")
            return parent
        parent = QgsProject.instance().layerTreeRoot().addGroup(PARENT_GROUP_NAME)
        parent.setExpanded(True)
        parent.setCustomProperty(ROOT_PROPERTY, "1")
        return parent

    def find_dataset_group(self, dataset_id: str):
        parent = self.find_parent_group()
        name = str(dataset_id)
        if parent is not None:
            group = parent.findGroup(name)
            if group is not None:
                return group
        return QgsProject.instance().layerTreeRoot().findGroup(name)

    def tags_sidecar_path(self, dataset_id: str) -> str:
        return os.path.join(self.cache_path_for(dataset_id), TAGS_SIDECAR)

    def read_cache_tags(self, dataset_id: str) -> List[str]:
        path = self.tags_sidecar_path(dataset_id)
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
            return parse_tags_payload(raw)
        except Exception:  # noqa: BLE001
            LOG.warning("Could not read tags sidecar for %s", dataset_id)
            return []

    def write_cache_tags(self, dataset_id: str, tags: List[str]) -> None:
        folder = self.cache_dir_for(dataset_id)
        path = os.path.join(folder, TAGS_SIDECAR)
        payload = serialize_tags(tags)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload if payload else "[]")

    def collect_cache_tags(self) -> List[str]:
        """All tags stored in cache sidecars (durable across project loss)."""
        tags: List[str] = []
        root = self.cache_root()
        if not os.path.isdir(root):
            return tags
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isdir(path):
                continue
            tags.extend(self.read_cache_tags(name))
        return tags

    def apply_cache_tags_to_group(self, dataset_id: str) -> None:
        tags = self.read_cache_tags(dataset_id)
        if not tags:
            return
        self.set_item_tags(dataset_id, tags)

    def read_cache_display_name(self, dataset_id: str) -> str:
        path = os.path.join(self.cache_path_for(dataset_id), META_SIDECAR)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return str(data.get("display_name") or "").strip()
        except Exception:  # noqa: BLE001
            pass
        return ""

    def write_cache_display_name(self, dataset_id: str, display_name: str) -> None:
        title = (display_name or "").strip()
        if not title:
            return
        folder = self.cache_dir_for(dataset_id)
        path = os.path.join(folder, META_SIDECAR)
        payload = {"display_name": title}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def has_usable_package(self, dataset_id: str) -> bool:
        return bool(self.resolve_cached_map_files(dataset_id, unpack=False)) or (
            os.path.isfile(
                os.path.join(self.cache_path_for(dataset_id), "package.zip")
            )
            and os.path.getsize(
                os.path.join(self.cache_path_for(dataset_id), "package.zip")
            )
            > 0
        )

    def list_cached_package_keys(self) -> List[str]:
        """Folder names under the cache that look like loadable packages."""
        root = self.cache_root()
        if not os.path.isdir(root):
            return []
        keys: List[str] = []
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isdir(path) and self.has_usable_package(name):
                keys.append(name)
        return keys

    def list_cached_display_names(self) -> List[str]:
        """Dataset display names from local package ``tdei_meta.json`` sidecars."""
        names: List[str] = []
        seen = set()
        for key in self.list_cached_package_keys():
            title = self.read_cache_display_name(key)
            if not title:
                continue
            folded = title.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            names.append(title)
        names.sort(key=lambda value: value.casefold())
        return names

    def resolve_cached_map_files(
        self, dataset_id: str, *, unpack: bool = True
    ) -> List[str]:
        """Return loadable map file paths from cache (optionally unpack zip)."""
        from ..core.models import JOB_MAP_PREFIX
        from ..features.osw.package import unpack_map_package

        cache_dir = self.cache_path_for(dataset_id)
        if not os.path.isdir(cache_dir):
            return []

        def _maybe_with_area(paths: List[str]) -> List[str]:
            # dataset_area.geojson is dataset-package only (one file per dataset id).
            if str(dataset_id).startswith(JOB_MAP_PREFIX):
                return paths
            from ..features.osw.metadata import with_dataset_area_path

            return with_dataset_area_path(cache_dir, paths)

        found = self._walk_map_files(cache_dir)
        if found:
            return _maybe_with_area(found)

        zip_path = os.path.join(cache_dir, "package.zip")
        if (
            unpack
            and os.path.isfile(zip_path)
            and os.path.getsize(zip_path) > 0
        ):
            extract_dir = os.path.join(cache_dir, "extracted")
            try:
                unpacked = unpack_map_package(
                    zip_path,
                    extract_dir,
                    extensions=(".geojson", ".osm", ".osm.xml", ".pbf"),
                )
                return _maybe_with_area(unpacked)
            except Exception:  # noqa: BLE001
                LOG.exception("Failed to unpack cached package for %s", dataset_id)
                return []
        return []

    @staticmethod
    def _walk_map_files(cache_dir: str) -> List[str]:
        from ..features.osw.package import is_map_filename

        found: List[str] = []
        for dirpath, _dirnames, filenames in os.walk(cache_dir):
            # Skip nested zip extract noise only if needed; include all map files.
            for name in filenames:
                if name in (TAGS_SIDECAR, META_SIDECAR, "metadata.json"):
                    continue
                if is_map_filename(name):
                    found.append(os.path.join(dirpath, name))
        return found

    def load_geojsons(
        self,
        dataset_id: str,
        geojson_paths: List[str],
        *,
        display_name: str = "",
        zoom: bool = True,
    ):
        return self.load_vector_files(
            dataset_id,
            geojson_paths,
            display_name=display_name,
            zoom=zoom,
        )

    def load_vector_files(
        self,
        dataset_id: str,
        file_paths: List[str],
        *,
        display_name: str = "",
        zoom: bool = True,
    ):
        """Load GeoJSON / OSM (and similar OGR) files into a TDEI layer group."""
        from ..features.osw.metadata import DATASET_AREA_FILENAME

        project = QgsProject.instance()
        parent = self.ensure_parent_group()
        group = parent.addGroup(str(dataset_id))
        group.setExpanded(True)
        # Keep unchecked until Zoom / View to map — checking large GeoJSON
        # forces an expensive canvas redraw.
        try:
            group.setItemVisibilityChecked(False)
        except Exception:  # noqa: BLE001
            pass
        group.setCustomProperty("tdei_dataset_id", str(dataset_id))
        title = (display_name or "").strip()
        if title:
            group.setCustomProperty("tdei_display_name", title)
        loaded = []
        area_paths = []
        other_paths = []
        for path in file_paths:
            if os.path.basename(path).lower() == DATASET_AREA_FILENAME:
                area_paths.append(path)
            else:
                other_paths.append(path)
        try:
            for path in other_paths:
                basename = os.path.basename(path)
                lower = basename.lower()
                stem = os.path.splitext(basename)[0]
                if lower.endswith(".osm.xml"):
                    stem = os.path.splitext(stem)[0]
                if self._is_osm_file(lower):
                    for sub in (
                        "points",
                        "lines",
                        "multilinestrings",
                        "multipolygons",
                        "other_relations",
                    ):
                        source = "{}|layername={}".format(path, sub)
                        layer = QgsVectorLayer(
                            source, "{} ({})".format(stem, sub), "ogr"
                        )
                        if not layer.isValid():
                            continue
                        # Skip empty OSM geometry groups
                        try:
                            if layer.featureCount() == 0:
                                continue
                        except Exception:  # noqa: BLE001
                            pass
                        layer.setCustomProperty(
                            "tdei_dataset_id", str(dataset_id)
                        )
                        project.addMapLayer(layer, False)
                        group.addLayer(layer)
                        loaded.append(layer)
                    continue

                layer = QgsVectorLayer(path, stem, "ogr")
                if not layer.isValid():
                    continue
                layer.setCustomProperty("tdei_dataset_id", str(dataset_id))
                project.addMapLayer(layer, False)
                group.addLayer(layer)
                loaded.append(layer)

            # Always nest dataset_area under this dataset-id group (not at TDEI root).
            for path in area_paths:
                area_layer = self._add_dataset_area_to_group(
                    group, dataset_id, path
                )
                if area_layer is not None:
                    loaded.append(area_layer)

            # File may exist on disk even when not listed in file_paths (e.g. Sync).
            try:
                if self.ensure_dataset_area_layer(dataset_id):
                    # Count newly attached area if not already in loaded.
                    for child in group.findLayers():
                        layer = child.layer()
                        if (
                            layer is not None
                            and str(layer.customProperty("tdei_dataset_area") or "")
                            == "1"
                            and layer not in loaded
                        ):
                            loaded.append(layer)
            except Exception:  # noqa: BLE001
                LOG.exception(
                    "Could not ensure dataset_area under group %s", dataset_id
                )

            if not loaded:
                raise ValueError(
                    "No valid GeoJSON/OSM layers were found in the package."
                )
            # Child nodes default to checked; force them off with the group.
            self._set_group_layers_checked(group, False)
        except Exception:
            for layer in loaded:
                project.removeMapLayer(layer.id())
            parent_node = group.parent()
            if parent_node is not None:
                parent_node.removeChildNode(group)
            raise
        if zoom:
            self.zoom_to_dataset(dataset_id)
        else:
            self._set_group_layers_checked(group, False)
        if title:
            try:
                self.write_cache_display_name(dataset_id, title)
            except Exception:  # noqa: BLE001
                LOG.warning("Could not write display name sidecar for %s", dataset_id)
        try:
            self.apply_cache_tags_to_group(dataset_id)
        except Exception:  # noqa: BLE001
            LOG.warning("Could not apply cache tags for %s", dataset_id)
        LOG.info("Loaded %s layers for dataset %s", len(loaded), dataset_id)
        return loaded

    def ensure_dataset_area_layer(self, dataset_id: str) -> bool:
        """Ensure ``dataset_area`` exists as a child of the dataset-id group."""
        from ..core.models import JOB_MAP_PREFIX
        from ..features.osw.metadata import ensure_dataset_area_file

        if str(dataset_id).startswith(JOB_MAP_PREFIX):
            return False
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return False
        if self._group_has_dataset_area(group):
            return True
        path = ensure_dataset_area_file(self.cache_path_for(dataset_id))
        if not path:
            return False
        layer = self._add_dataset_area_to_group(group, dataset_id, path)
        if layer is None:
            return False
        try:
            # Keep consistent with download: do not force-render until Zoom.
            for child in group.findLayers():
                if child is not None and child.layer() is layer:
                    child.setItemVisibilityChecked(False)
                    break
        except Exception:  # noqa: BLE001
            pass
        return True

    def set_dataset_area_visible(self, dataset_id: str, visible: bool = True) -> bool:
        """Check/uncheck the dataset_area child under the dataset group."""
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return False
        for child in group.findLayers():
            layer = child.layer() if child is not None else None
            if layer is None:
                continue
            is_area = (
                str(layer.customProperty("tdei_dataset_area") or "") == "1"
                or layer.name().lower().startswith("dataset_area")
            )
            if not is_area:
                continue
            try:
                child.setItemVisibilityChecked(bool(visible))
                # Parent group must be checked for the layer to render.
                if visible:
                    group.setItemVisibilityChecked(True)
            except Exception:  # noqa: BLE001
                return False
            return True
        return False

    @staticmethod
    def _group_has_dataset_area(group) -> bool:
        for child in group.findLayers():
            layer = child.layer()
            if layer is None:
                continue
            if str(layer.customProperty("tdei_dataset_area") or "") == "1":
                return True
            if layer.name().lower().startswith("dataset_area"):
                return True
        return False

    def _add_dataset_area_to_group(
        self, group, dataset_id: str, path: str
    ):
        """Add dataset_area.geojson as a child layer under *group* (dataset id)."""
        if not path or not os.path.isfile(path):
            LOG.warning(
                "dataset_area file missing for %s: %s", dataset_id, path
            )
            return None
        if self._group_has_dataset_area(group):
            return None
        abs_path = os.path.abspath(path)
        project = QgsProject.instance()
        layer = QgsVectorLayer(abs_path, "dataset_area", "ogr")
        if not layer.isValid():
            # Some builds prefer an explicit file URI.
            layer = QgsVectorLayer(
                "file://{}".format(abs_path), "dataset_area", "ogr"
            )
        if not layer.isValid():
            err = ""
            try:
                err = layer.error().message() if layer.error() else ""
            except Exception:  # noqa: BLE001
                err = ""
            LOG.warning(
                "Invalid dataset_area layer for %s (%s): %s",
                dataset_id,
                abs_path,
                err or "unknown OGR error",
            )
            return None
        layer.setName("dataset_area")
        layer.setCustomProperty("tdei_dataset_id", str(dataset_id))
        layer.setCustomProperty("tdei_dataset_area", "1")
        project.addMapLayer(layer, False)
        # Insert at top of the dataset-id group so it sits directly under the id.
        try:
            group.insertLayer(0, layer)
        except Exception:  # noqa: BLE001
            group.addLayer(layer)
        LOG.info(
            "Added dataset_area under group %s from %s", dataset_id, abs_path
        )
        return layer

    def show_map_search_areas(self, datasets: List) -> List:
        """Replace map-search result layers with areas from *datasets*.

        Draws each dataset's ``metadata.dataset_detail.dataset_area`` as a
        visible overlay on the map. Returns the datasets that were painted.
        """
        from qgis.core import QgsCoordinateReferenceSystem

        from ..features.osw.metadata import normalize_dataset_area_geojson

        self.clear_map_search_layers()
        if not datasets:
            return []

        group = self._ensure_map_search_group()
        project = QgsProject.instance()
        temp_root = os.path.join(self.ensure_cache_root(), "_map_search")
        os.makedirs(temp_root, exist_ok=True)
        crs = QgsCoordinateReferenceSystem("EPSG:4326")
        painted = []
        for dataset in datasets:
            dataset_id = str(getattr(dataset, "id", "") or "").strip()
            if not dataset_id:
                continue
            area = normalize_dataset_area_geojson(
                self._dataset_area_from_raw(getattr(dataset, "raw", None))
            )
            if area is None:
                LOG.info(
                    "Map search skip %s — no valid dataset_area in response",
                    dataset_id,
                )
                continue
            path = os.path.join(
                temp_root, "{}.geojson".format(dataset_id.replace("/", "_"))
            )
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(area, handle)
            except OSError:
                LOG.warning("Could not write map-search area for %s", dataset_id)
                continue
            display = (
                str(getattr(dataset, "name", "") or "").strip() or dataset_id
            )
            layer_name = display[:80]
            abs_path = os.path.abspath(path)
            layer = QgsVectorLayer(abs_path, layer_name, "ogr")
            if not layer.isValid():
                layer = QgsVectorLayer(
                    "file://{}".format(abs_path), layer_name, "ogr"
                )
            if not layer.isValid():
                LOG.warning("Invalid map-search area layer for %s", dataset_id)
                continue
            try:
                if layer.featureCount() == 0:
                    LOG.warning(
                        "Map-search area layer empty for %s", dataset_id
                    )
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                layer.setCrs(crs)
            except Exception:  # noqa: BLE001
                pass
            layer.setName(layer_name)
            layer.setCustomProperty(MAP_SEARCH_LAYER_PROPERTY, "1")
            layer.setCustomProperty("tdei_dataset_id", dataset_id)
            layer.setCustomProperty("tdei_display_name", display)
            status = str(getattr(dataset, "status", "") or "").strip()
            if status:
                layer.setCustomProperty("tdei_status", status)
            group_allowed, dataset_allowed = self._viewer_flags_for_dataset(
                dataset
            )
            layer.setCustomProperty(
                "tdei_group_data_viewer_allowed",
                "1" if group_allowed else "0",
            )
            layer.setCustomProperty(
                "tdei_data_viewer_allowed",
                "1" if dataset_allowed else "0",
            )
            viewer_mode = self._map_search_viewer_mode(
                group_allowed, dataset_allowed
            )
            layer.setCustomProperty("tdei_viewer_mode", viewer_mode)
            self._style_map_search_layer(layer, display, viewer_mode=viewer_mode)
            project.addMapLayer(layer, False)
            try:
                group.insertLayer(0, layer)
            except Exception:  # noqa: BLE001
                group.addLayer(layer)
            painted.append(dataset)

        try:
            group.setItemVisibilityChecked(True)
            group.setExpanded(True)
            for child in group.findLayers():
                if child is not None:
                    child.setItemVisibilityChecked(True)
        except Exception:  # noqa: BLE001
            pass

        if self._iface is not None:
            try:
                canvas = self._iface.mapCanvas()
                if canvas is not None:
                    canvas.refreshAllLayers()
                    canvas.refresh()
            except Exception:  # noqa: BLE001
                try:
                    self._iface.mapCanvas().refresh()
                except Exception:  # noqa: BLE001
                    pass

        LOG.info("Map search painted %s dataset area(s)", len(painted))
        return painted

    def zoom_to_map_search_dataset(self, dataset_id: str) -> bool:
        """Zoom the canvas to a map-search area layer for *dataset_id*."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id or self._iface is None:
            return False
        group = self.find_map_search_group()
        if group is None:
            return False
        target = None
        for child in group.findLayers():
            layer = child.layer() if child is not None else None
            if layer is None or not layer.isValid():
                continue
            if str(layer.customProperty(MAP_SEARCH_LAYER_PROPERTY) or "") != "1":
                continue
            if str(layer.customProperty("tdei_dataset_id") or "") != dataset_id:
                continue
            target = layer
            try:
                child.setItemVisibilityChecked(True)
                group.setItemVisibilityChecked(True)
            except Exception:  # noqa: BLE001
                pass
            break
        if target is None:
            LOG.warning("Map search zoom — no area layer for %s", dataset_id)
            return False
        self._zoom_to_layers([target])
        return True

    @staticmethod
    def _dataset_area_from_raw(raw) -> object:
        """Pull dataset_area from a datasets API item (several shapes)."""
        from ..features.osw.metadata import dataset_area_value

        if not isinstance(raw, dict):
            return None
        # Canonical: metadata.dataset_detail.dataset_area
        area = dataset_area_value(raw.get("metadata"))
        if area is not None:
            return area
        area = dataset_area_value(raw)
        if area is not None:
            return area
        # Occasional API variants
        for key in ("dataset_area", "datasetArea"):
            if key in raw:
                return raw.get(key)
        metadata = raw.get("metadata")
        if isinstance(metadata, dict):
            for key in ("dataset_area", "datasetArea"):
                if key in metadata:
                    return metadata.get(key)
        return None

    def clear_map_search_layers(self) -> None:
        """Remove the temporary map-search group and its layers."""
        self._clear_map_search_highlights()
        project = QgsProject.instance()
        group = self.find_map_search_group()
        if group is None:
            self._cleanup_map_search_files()
            return
        layer_ids = []
        for child in list(group.findLayers()):
            layer = child.layer()
            if layer is not None:
                layer_ids.append(layer.id())
        if layer_ids:
            project.removeMapLayers(layer_ids)
        parent = group.parent()
        if parent is not None:
            parent.removeChildNode(group)
        self._cleanup_map_search_files()

    def find_map_search_group(self):
        """Find the map-search group at project root (preferred) or under TDEI."""
        root = QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if str(child.customProperty(MAP_SEARCH_GROUP_PROPERTY) or "") == "1":
                return child
            if child.name() == MAP_SEARCH_GROUP_NAME:
                return child
        parent = self.find_parent_group()
        if parent is None:
            return None
        for child in parent.children():
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if str(child.customProperty(MAP_SEARCH_GROUP_PROPERTY) or "") == "1":
                return child
            if child.name() == MAP_SEARCH_GROUP_NAME:
                return child
        return None

    def _ensure_map_search_group(self):
        """Create map-search group at project root (index 0) for top draw order.

        Do not use takeChild/reorder after layers are attached — that can
        orphan the group so overlays never appear in the Layers panel.
        """
        existing = self.find_map_search_group()
        if existing is not None:
            return existing
        root = QgsProject.instance().layerTreeRoot()
        try:
            group = root.insertGroup(0, MAP_SEARCH_GROUP_NAME)
        except Exception:  # noqa: BLE001
            group = root.addGroup(MAP_SEARCH_GROUP_NAME)
        group.setCustomProperty(MAP_SEARCH_GROUP_PROPERTY, "1")
        return group

    @staticmethod
    def _viewer_flags_for_dataset(dataset) -> tuple:
        """Return ``(group_allowed, dataset_allowed)`` for map-search styling."""
        from ..api.v1.datasets import coerce_bool, viewer_flags_from_item

        group_allowed = getattr(
            dataset, "project_group_data_viewer_allowed", None
        )
        dataset_allowed = getattr(dataset, "data_viewer_allowed", None)
        if isinstance(group_allowed, bool) and isinstance(dataset_allowed, bool):
            return group_allowed, dataset_allowed
        raw = getattr(dataset, "raw", None)
        if isinstance(raw, dict):
            return viewer_flags_from_item(raw)
        return (
            coerce_bool(group_allowed, default=False),
            coerce_bool(dataset_allowed, default=False),
        )

    @staticmethod
    def _map_search_viewer_mode(group_allowed: bool, dataset_allowed: bool) -> str:
        """Color mode: group_blocked | dataset_blocked | allowed."""
        if not group_allowed:
            return "group_blocked"
        if not dataset_allowed:
            return "dataset_blocked"
        return "allowed"

    @staticmethod
    def _style_map_search_layer(
        layer, label: str = "", *, viewer_mode: str = "allowed"
    ) -> None:
        try:
            from qgis.core import (
                QgsFillSymbol,
                QgsPalLayerSettings,
                QgsSingleSymbolRenderer,
                QgsTextFormat,
                QgsVectorLayerSimpleLabeling,
            )
            from qgis.PyQt.QtGui import QColor, QFont

            # Yellow = project group viewer off; green = dataset viewer off;
            # TDEI purple = PMTiles viewing allowed at both levels.
            if viewer_mode == "group_blocked":
                fill, outline, text = (
                    "255,193,7,90",
                    "184,134,11,220",
                    QColor(146, 104, 0),
                )
            elif viewer_mode == "dataset_blocked":
                fill, outline, text = (
                    "21,115,71,90",
                    "15,90,55,220",
                    QColor(15, 90, 55),
                )
            else:
                fill, outline, text = (
                    "50,0,110,90",
                    "50,0,110,255",
                    QColor(50, 0, 110),
                )

            symbol = QgsFillSymbol.createSimple(
                {
                    "color": fill,
                    "outline_color": outline,
                    "outline_width": "1.4",
                    "outline_style": "solid",
                    "style": "solid",
                }
            )
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))

            # Selection: outline only — never the default solid yellow fill.
            # Also set project-level selection color on this layer; some QGIS
            # builds ignore setSelectionSymbol and still paint yellow.
            selection = QgsFillSymbol.createSimple(
                {
                    "color": "0,0,0,0",
                    "outline_color": outline,
                    "outline_width": "2.6",
                    "outline_style": "solid",
                    "style": "no",
                }
            )
            try:
                layer.setSelectionSymbol(selection.clone())
            except Exception:  # noqa: BLE001
                pass
            try:
                layer.setSelectionColor(QColor(50, 0, 110, 0))
            except Exception:  # noqa: BLE001
                pass
            try:
                # QGIS 3.34+ per-layer opacity for selection fill.
                if hasattr(layer, "setSelectionColor"):
                    layer.setSelectionColor(QColor(0, 0, 0, 0))
            except Exception:  # noqa: BLE001
                pass

            settings = QgsPalLayerSettings()
            settings.isExpression = True
            safe = (label or layer.name() or "dataset").replace("'", "''")
            settings.fieldName = "'{}'".format(safe)
            settings.enabled = True
            try:
                settings.placement = QgsPalLayerSettings.OverPoint
            except Exception:  # noqa: BLE001
                pass
            text_format = QgsTextFormat()
            text_format.setSize(9)
            text_format.setColor(text)
            try:
                text_format.setFont(QFont("Open Sans", 9))
            except Exception:  # noqa: BLE001
                pass
            settings.setFormat(text_format)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
            layer.setLabelsEnabled(True)
        except Exception:  # noqa: BLE001
            LOG.debug("Could not style map-search layer", exc_info=True)

    def _cleanup_map_search_files(self) -> None:
        temp_root = os.path.join(self.cache_root(), "_map_search")
        if not os.path.isdir(temp_root):
            return
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    def list_mapped_items(self, *, jobs: Optional[bool] = None) -> List[MappedItem]:
        """Return TDEI layer groups currently in the project.

        :param jobs: True = only job-* groups, False = only datasets, None = all
        """
        parent = self.find_parent_group()
        if parent is None:
            return []
        items: List[MappedItem] = []
        for child in parent.children():
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if str(child.customProperty(MAP_SEARCH_GROUP_PROPERTY) or "") == "1":
                continue
            if child.name() == MAP_SEARCH_GROUP_NAME:
                continue
            key = str(child.name())
            is_job = key.startswith(JOB_MAP_PREFIX)
            if jobs is True and not is_job:
                continue
            if jobs is False and is_job:
                continue
            display = str(child.customProperty("tdei_display_name") or "")
            items.append(
                MappedItem(
                    key=key,
                    display_name=display or key,
                    kind="job" if is_job else "dataset",
                    tags=parse_tags_payload(
                        child.customProperty("tdei_tags")
                    ),
                )
            )
        return items

    def get_item_tags(self, dataset_id: str) -> List[str]:
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return []
        return parse_tags_payload(group.customProperty("tdei_tags"))

    def set_item_tags(self, dataset_id: str, tags: List[str]) -> None:
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return
        payload = serialize_tags(tags)
        group.setCustomProperty("tdei_tags", payload)

    def collect_item_tags(self) -> List[str]:
        tags: List[str] = []
        for item in self.list_mapped_items():
            tags.extend(item.tags or [])
        return tags

    def remove_dataset_group(self, dataset_id: str) -> bool:
        """Remove the layer group and its map layers. Returns True if removed."""
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return False
        project = QgsProject.instance()
        layer_ids = []
        for child in group.findLayers():
            layer = child.layer()
            if layer is not None:
                layer_ids.append(layer.id())
        if layer_ids:
            project.removeMapLayers(layer_ids)
        parent = group.parent()
        if parent is not None:
            parent.removeChildNode(group)
        # Drop empty TDEI parent
        root_parent = self.find_parent_group()
        if root_parent is not None and len(root_parent.children()) == 0:
            root = QgsProject.instance().layerTreeRoot()
            root.removeChildNode(root_parent)
        LOG.info("Removed TDEI layers for %s", dataset_id)
        return True

    def clear_cache(self, dataset_id: str) -> bool:
        """Delete on-disk package cache for this dataset/job key."""
        path = self.cache_path_for(dataset_id)
        if not os.path.isdir(path):
            return False
        shutil.rmtree(path, ignore_errors=True)
        LOG.info("Cleared local cache for %s", dataset_id)
        return True

    @staticmethod
    def _is_osm_file(lower_name: str) -> bool:
        return (
            lower_name.endswith(".osm")
            or lower_name.endswith(".osm.xml")
            or lower_name.endswith(".pbf")
        )

    def zoom_to_dataset(self, dataset_id: str) -> None:
        if self._iface is None:
            return
        group = self.find_dataset_group(dataset_id)
        if group is None:
            LOG.warning("Zoom skipped — no layer group for %s", dataset_id)
            return
        # Make the group (and parents) visible before zooming, then select it.
        self.ensure_dataset_group_visible(dataset_id)
        try:
            self.select_dataset_group(dataset_id)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not select group before zoom for %s", dataset_id)
        layers = []
        for child in group.findLayers():
            layer = child.layer()
            if layer is not None and layer.isValid():
                layers.append(layer)
        if not layers:
            LOG.warning("Zoom skipped — no layers in group %s", dataset_id)
            return
        self._zoom_to_layers(layers)

    def ensure_dataset_group_visible(self, dataset_id: str) -> None:
        """Force-check the dataset group, ancestors, and all child layers."""
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return
        try:
            # Always re-apply checked state (mixed/partial checks can look "on"
            # while some child layers are still off).
            node = group  # type: Optional[QgsLayerTreeNode]
            for _ in range(32):
                if node is None or not isinstance(node, QgsLayerTreeNode):
                    break
                node.setItemVisibilityChecked(True)
                parent = node.parent()
                if parent is None or parent is node:
                    break
                if not isinstance(parent, QgsLayerTreeNode):
                    break
                node = parent
            self._set_group_layers_checked(group, True)
        except Exception:  # noqa: BLE001
            LOG.exception(
                "Could not ensure visibility for dataset group %s", dataset_id
            )

    @staticmethod
    def _set_group_layers_checked(group, checked: bool) -> None:
        """Check or uncheck a dataset group and every child layer node."""
        try:
            group.setItemVisibilityChecked(checked)
        except Exception:  # noqa: BLE001
            pass
        try:
            for child in group.findLayers():
                if child is not None:
                    child.setItemVisibilityChecked(checked)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not set layer visibility checked=%s", checked)

    def select_dataset_group(self, dataset_id: str) -> None:
        """Select only this dataset group in the Layers panel (clear multi-select)."""
        if self._iface is None:
            return
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return
        view = self._iface.layerTreeView()
        if view is None:
            return
        try:
            # Expand only layer-tree ancestors (not QObject parents — that can hang).
            node = group  # type: Optional[QgsLayerTreeNode]
            for _ in range(32):
                if node is None or not isinstance(node, QgsLayerTreeNode):
                    break
                if isinstance(node, QgsLayerTreeGroup):
                    node.setExpanded(True)
                parent = node.parent()
                if parent is None or parent is node:
                    break
                if not isinstance(parent, QgsLayerTreeNode):
                    break
                node = parent

            # Drop any multi-selected child layers so the group is the focus.
            try:
                view.selectionModel().clearSelection()
            except Exception:  # noqa: BLE001
                pass
            try:
                view.setSelectedLayers([])
            except Exception:  # noqa: BLE001
                pass

            view.setCurrentNode(group)
            try:
                from qgis.PyQt.QtCore import QItemSelectionModel

                index = view.node2index(group)
                if index is not None and index.isValid():
                    view.selectionModel().select(
                        index,
                        QItemSelectionModel.ClearAndSelect
                        | QItemSelectionModel.Rows,
                    )
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            LOG.exception("Could not select dataset group %s", dataset_id)

    def dataset_id_from_node(self, node) -> Optional[str]:
        if node is None:
            return None
        layer = node.layer() if hasattr(node, "layer") else None
        if layer is not None:
            value = layer.customProperty("tdei_dataset_id")
            if value:
                return str(value)
        if hasattr(node, "customProperty"):
            value = node.customProperty("tdei_dataset_id")
            if value:
                return str(value)
        parent = node.parent() if hasattr(node, "parent") else None
        if parent is not None:
            return self.dataset_id_from_node(parent)
        return None

    @staticmethod
    def is_map_search_layer(layer) -> bool:
        if layer is None:
            return False
        try:
            return str(layer.customProperty(MAP_SEARCH_LAYER_PROPERTY) or "") == "1"
        except Exception:  # noqa: BLE001
            return False

    def map_search_layers(self) -> List:
        """Temporary map-search area overlays currently in the project."""
        found = []
        try:
            for layer in QgsProject.instance().mapLayers().values():
                if self.is_map_search_layer(layer) and layer.isValid():
                    found.append(layer)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not list map-search layers")
        return found

    def map_search_hit_at_canvas_pos(self, canvas, pos, *, select: bool = False):
        """Return (dataset_id, display_name, layer) for a map-search area under *pos*.

        *pos* is a QPoint in canvas (or viewport) widget coordinates.
        When *select* is True, the hit feature is selected for visual highlight.
        """
        if canvas is None or pos is None:
            return None
        try:
            transform = canvas.getCoordinateTransform()
            map_point = transform.toMapCoordinates(int(pos.x()), int(pos.y()))
        except Exception:  # noqa: BLE001
            return None
        canvas_crs = None
        try:
            canvas_crs = canvas.mapSettings().destinationCrs()
        except Exception:  # noqa: BLE001
            canvas_crs = None

        try:
            p1 = transform.toMapCoordinates(int(pos.x()) - 4, int(pos.y()) - 4)
            p2 = transform.toMapCoordinates(int(pos.x()) + 4, int(pos.y()) + 4)
            search = QgsRectangle(p1.x(), p1.y(), p2.x(), p2.y())
            search.normalize()
        except Exception:  # noqa: BLE001
            search = None

        from qgis.core import QgsFeatureRequest, QgsGeometry, QgsPointXY

        for layer in self.map_search_layers():
            try:
                if not layer.isValid() or not layer.isSpatial():
                    continue
                point = map_point
                if not isinstance(point, QgsPointXY):
                    try:
                        point = QgsPointXY(point)
                    except Exception:  # noqa: BLE001
                        continue
                rect = search
                layer_crs = layer.crs()
                if (
                    canvas_crs is not None
                    and layer_crs is not None
                    and canvas_crs != layer_crs
                ):
                    xform = QgsCoordinateTransform(
                        canvas_crs, layer_crs, QgsProject.instance()
                    )
                    point = xform.transform(point)
                    if rect is not None:
                        rect = xform.transformBoundingBox(rect)
                geom_point = QgsGeometry.fromPointXY(point)
                req = QgsFeatureRequest()
                if rect is not None:
                    req.setFilterRect(rect)
                for feature in layer.getFeatures(req):
                    geom = feature.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    if not (
                        geom.contains(point) or geom.intersects(geom_point)
                    ):
                        continue
                    dataset_id = str(
                        layer.customProperty("tdei_dataset_id") or ""
                    ).strip()
                    if not dataset_id:
                        continue
                    display = str(
                        layer.customProperty("tdei_display_name") or ""
                    ).strip() or dataset_id
                    if select:
                        try:
                            # Clear other map-search selections / highlights.
                            for other in self.map_search_layers():
                                if other is not layer:
                                    other.removeSelection()
                            layer.removeSelection()
                            self._highlight_map_search_layer(layer)
                            self._select_layer_in_tree(layer)
                        except Exception:  # noqa: BLE001
                            pass
                    return dataset_id, display, layer
            except Exception:  # noqa: BLE001
                LOG.exception("Map-search hit test failed for a layer")
                continue
        return None

    def _select_layer_in_tree(self, layer) -> None:
        if layer is None or self._iface is None:
            return
        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(True)
        except Exception:  # noqa: BLE001
            pass
        try:
            view = self._iface.layerTreeView()
            if view is not None:
                view.setSelectedLayers([layer])
        except Exception:  # noqa: BLE001
            pass

    def select_map_search_dataset(self, dataset_id: str) -> bool:
        """Highlight the map-search area layer for *dataset_id* (if present)."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            return False
        target = None
        for layer in self.map_search_layers():
            if str(layer.customProperty("tdei_dataset_id") or "").strip() != dataset_id:
                try:
                    layer.removeSelection()
                except Exception:  # noqa: BLE001
                    pass
                continue
            target = layer
        if target is None:
            self._clear_map_search_highlights()
            return False
        try:
            target.removeSelection()
        except Exception:  # noqa: BLE001
            pass
        self._highlight_map_search_layer(target)
        self._select_layer_in_tree(target)
        return True

    def _clear_map_search_highlights(self) -> None:
        highlights = list(getattr(self, "_map_search_highlights", []) or [])
        self._map_search_highlights = []
        for highlight in highlights:
            try:
                highlight.hide()
            except Exception:  # noqa: BLE001
                pass
            try:
                highlight.deleteLater()
            except Exception:  # noqa: BLE001
                pass

    def _highlight_map_search_layer(self, layer) -> None:
        """Outline-only focus ring — never QGIS yellow selection fill."""
        self._clear_map_search_highlights()
        if layer is None or self._iface is None:
            return
        try:
            canvas = self._iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is None:
            return
        try:
            from qgis.gui import QgsHighlight
            from qgis.PyQt.QtGui import QColor
        except Exception:  # noqa: BLE001
            return

        mode = str(layer.customProperty("tdei_viewer_mode") or "allowed")
        if mode == "group_blocked":
            outline = QColor(184, 134, 11, 255)
        elif mode == "dataset_blocked":
            outline = QColor(15, 90, 55, 255)
        else:
            outline = QColor(50, 0, 110, 255)
        fill = QColor(outline)
        fill.setAlpha(35)

        highlights = []
        try:
            features = list(layer.getFeatures())
        except Exception:  # noqa: BLE001
            features = []
        for feature in features:
            try:
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                highlight = QgsHighlight(canvas, feature, layer)
                highlight.setColor(outline)
                try:
                    highlight.setFillColor(fill)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    highlight.setWidth(3)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    highlight.setBuffer(0.8)
                except Exception:  # noqa: BLE001
                    pass
                highlight.show()
                highlights.append(highlight)
            except Exception:  # noqa: BLE001
                LOG.debug("Map-search highlight failed", exc_info=True)
        self._map_search_highlights = highlights
        try:
            canvas.refresh()
        except Exception:  # noqa: BLE001
            pass

    def layers_in_dataset(self, dataset_id: str):
        group = self.find_dataset_group(dataset_id)
        if group is None:
            return []
        layers = []
        for child in group.findLayers():
            layer = child.layer()
            if layer is not None and layer.isValid():
                layers.append(layer)
        return layers

    @staticmethod
    def is_geojson_layer(layer) -> bool:
        """True when the layer is backed by a .geojson / .json file (not OSM/PBF)."""
        if layer is None:
            return False
        try:
            if not layer.isValid():
                return False
        except Exception:  # noqa: BLE001
            return False
        source = (layer.source() or "").split("|")[0].strip().lower()
        if not source:
            return False
        return source.endswith(".geojson") or source.endswith(".json")

    def selected_layers_in_dataset(self, dataset_id: str):
        """Map layers currently selected that belong to this dataset group."""
        group_layers = self.layers_in_dataset(dataset_id)
        if not group_layers:
            return []
        view = self._iface.layerTreeView() if self._iface else None
        if view is None:
            return []
        group_ids = {layer.id() for layer in group_layers}
        selected = []
        for layer in view.selectedLayers() or []:
            if layer is not None and layer.id() in group_ids:
                selected.append(layer)
        return selected

    def layers_for_osw_upload(self, dataset_id: str):
        """GeoJSON layers to zip for OSW jobs.

        Uses the current selection in the group when present, otherwise all
        GeoJSON layers in the group. Only layers whose file names match OSW
        naming (``*.nodes.geojson``, ``*.edges.geojson``, …) are included.
        """
        accepted, _rejected = self.classify_osw_upload_layers(dataset_id)
        return list(accepted)

    def osw_geojson_basename(self, layer) -> str:
        """Best-effort GeoJSON file name for an upload layer."""
        source = (layer.source() or "").split("|")[0].strip()
        if source:
            base = os.path.basename(source)
            if base:
                return base
        name = (layer.name() or "layer").strip() or "layer"
        lower = name.lower()
        if lower.endswith((".geojson", ".json")):
            return name
        return "{}.geojson".format(name)

    def classify_osw_upload_layers(self, dataset_id: str):
        """Split candidate GeoJSON layers into (accepted, rejected) by OSW names."""
        from ..features.osw.naming import is_osw_convention_filename

        selected = self.selected_layers_in_dataset(dataset_id)
        candidates = selected if selected else self.layers_in_dataset(dataset_id)
        geojson_layers = [
            layer for layer in candidates if self.is_geojson_layer(layer)
        ]
        accepted = []
        rejected = []
        for layer in geojson_layers:
            name = self.osw_geojson_basename(layer)
            if is_osw_convention_filename(name):
                accepted.append(layer)
            else:
                rejected.append(layer)
        return accepted, rejected

    def osw_package_selection_ok(self, dataset_id: str) -> bool:
        """Whether Validate/Sanitize/Convert may run for the current selection.

        Requires at least one GeoJSON layer with a valid OSW file name.
        Mixed selections are allowed at menu time; upload prompts for consent
        and only zips naming-compliant layers.
        """
        accepted, _rejected = self.classify_osw_upload_layers(dataset_id)
        return bool(accepted)

    def prepare_osw_package_zip(self, dataset_id: str) -> str:
        layers = self.layers_for_osw_upload(dataset_id)
        if not layers:
            from ..features.osw.naming import supported_osw_geojson_types_text

            selected = self.selected_layers_in_dataset(dataset_id)
            if selected:
                raise ValueError(
                    "No GeoJSON layers with a valid OSW file name in the "
                    "selection. Supported names: {}.".format(
                        supported_osw_geojson_types_text()
                    )
                )
            raise ValueError(
                "GeoJSON files are not in a valid OSW naming convention. "
                "Supported names: {}.".format(supported_osw_geojson_types_text())
            )
        dest_zip = os.path.join(self.cache_dir_for(dataset_id), "osw_upload.zip")
        temp_dir = tempfile.mkdtemp(prefix="tdei_osw_export_")
        try:
            paths = []
            for layer in layers:
                path = self._geojson_path_for_layer(layer, temp_dir)
                if path:
                    paths.append(path)
            if not paths:
                raise ValueError("Could not build GeoJSON files for upload.")
            return zip_geojson_paths(paths, dest_zip)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _geojson_path_for_layer(self, layer, temp_dir: str) -> Optional[str]:
        if not self.is_geojson_layer(layer):
            return None
        source = (layer.source() or "").split("|")[0]
        if (
            source.lower().endswith((".geojson", ".json"))
            and os.path.isfile(source)
            and not layer.isModified()
        ):
            return source
        filename = (
            os.path.basename(source)
            if source
            else "{}.geojson".format(layer.name())
        )
        if not filename.lower().endswith((".geojson", ".json")):
            filename = "{}.geojson".format(layer.name())
        dest = os.path.join(temp_dir, filename)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(filename)
            dest = os.path.join(
                temp_dir, "{}-{}{}".format(stem, layer.id(), ext)
            )
        self._export_layer_geojson(layer, dest)
        return dest

    @staticmethod
    def _export_layer_geojson(layer, dest_path: str) -> None:
        result = QgsVectorFileWriter.writeAsVectorFormat(
            layer, dest_path, "utf-8", layer.crs(), "GeoJSON"
        )
        error = result[0] if isinstance(result, tuple) else result
        if error != QgsVectorFileWriter.NoError:
            raise ValueError(
                'Could not export layer "{}".'.format(layer.name())
            )

    def _zoom_to_layers(self, layers) -> None:
        canvas = self._iface.mapCanvas()
        if canvas is None:
            return
        dest_crs = canvas.mapSettings().destinationCrs()
        extent = QgsRectangle()
        extent.setNull()
        project = QgsProject.instance()
        for layer in layers:
            if layer is None or not layer.isValid():
                continue
            try:
                layer.updateExtents()
            except Exception:  # noqa: BLE001
                pass
            layer_extent = layer.extent()
            if layer_extent is None or layer_extent.isEmpty() or layer_extent.isNull():
                continue
            src_crs = layer.crs()
            if src_crs is not None and src_crs.isValid() and dest_crs.isValid():
                try:
                    transform = QgsCoordinateTransform(src_crs, dest_crs, project)
                    layer_extent = transform.transformBoundingBox(layer_extent)
                except Exception:  # noqa: BLE001
                    # Do not mix untransformed extents into the canvas CRS.
                    LOG.debug(
                        "Could not transform extent for layer %s",
                        layer.name(),
                        exc_info=True,
                    )
                    continue
            if extent.isNull():
                extent = QgsRectangle(layer_extent)
            else:
                extent.combineExtentWith(layer_extent)
        if extent.isNull() or extent.isEmpty():
            LOG.warning("Zoom skipped — could not compute a valid extent")
            return
        extent.scale(1.1)
        # Always re-apply (even if the canvas is already near this extent).
        canvas.setExtent(extent)
        canvas.refresh()
        try:
            canvas.redrawAllLayers()
        except Exception:  # noqa: BLE001
            pass
        try:
            main = self._iface.mainWindow()
            if main is not None:
                main.raise_()
        except Exception:  # noqa: BLE001
            pass
