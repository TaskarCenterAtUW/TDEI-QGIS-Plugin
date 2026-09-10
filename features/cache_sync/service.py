# -*- coding: utf-8 -*-
"""Rebuild TDEI project layers from the durable OSW disk cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from ...logging.logger import get_logger

if TYPE_CHECKING:
    from ...qgis.basemap_manager import BasemapManager
    from ...qgis.layer_manager import LayerManager

LOG = get_logger(__name__)

# (key, map_file_paths, display_name)
RestoreJob = Tuple[str, List[str], str]


@dataclass
class CacheSyncResult:
    restored: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[Tuple[str, str]] = field(default_factory=list)


class CacheSyncService:
    """Ensure TDEI root exists and map all usable cache packages into the project."""

    def __init__(
        self,
        layer_manager: "LayerManager",
        basemap_manager: Optional["BasemapManager"] = None,
    ) -> None:
        self._layers = layer_manager
        self._basemaps = basemap_manager

    def inventory_for_sync(self) -> Tuple[List[str], List[str]]:
        """UI-thread safe split: (already_loaded_keys, pending_keys)."""
        self._layers.ensure_cache_root()
        loaded: List[str] = []
        pending: List[str] = []
        for key in self._layers.list_cached_package_keys():
            if self._layers.is_dataset_loaded(key):
                loaded.append(key)
            else:
                pending.append(key)
        return loaded, pending

    def prepare_pending_keys(
        self, pending_keys: Sequence[str]
    ) -> Tuple[List[RestoreJob], List[Tuple[str, str]]]:
        """Background-safe: resolve/unpack map files for keys not yet in the project."""
        jobs: List[RestoreJob] = []
        errors: List[Tuple[str, str]] = []
        for key in pending_keys:
            try:
                files = self._layers.resolve_cached_map_files(key, unpack=True)
                if not files:
                    errors.append((key, "No map files in cache"))
                    continue
                display = self._layers.read_cache_display_name(key)
                jobs.append((key, files, display))
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Prepare sync failed for %s", key)
                errors.append((key, str(exc) or type(exc).__name__))
        return jobs, errors

    def apply_restore_jobs(
        self,
        loaded_keys: List[str],
        jobs: List[RestoreJob],
        prepare_errors: Optional[List[Tuple[str, str]]] = None,
    ) -> CacheSyncResult:
        """UI-thread: ensure root, add layers, apply tags. Must not run in a worker."""
        result = CacheSyncResult()
        result.errors.extend(prepare_errors or [])
        result.failed += len(prepare_errors or [])

        self._layers.ensure_parent_group()
        self._ensure_basemap()

        for key in loaded_keys:
            try:
                self._layers.apply_cache_tags_to_group(key)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._layers.ensure_dataset_area_layer(key)
            except Exception:  # noqa: BLE001
                LOG.exception("Could not add dataset_area for loaded key %s", key)
            result.skipped += 1

        for key, files, display in jobs:
            if self._layers.is_dataset_loaded(key):
                try:
                    self._layers.apply_cache_tags_to_group(key)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._layers.ensure_dataset_area_layer(key)
                except Exception:  # noqa: BLE001
                    LOG.exception(
                        "Could not add dataset_area for existing key %s", key
                    )
                result.skipped += 1
                continue
            try:
                self._layers.load_vector_files(
                    key,
                    files,
                    display_name=display,
                    zoom=False,
                )
                result.restored += 1
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Sync add failed for cache key %s", key)
                result.failed += 1
                result.errors.append((key, str(exc) or type(exc).__name__))
        return result

    def sync_cache_to_project(self) -> CacheSyncResult:
        """Full sync on the calling (UI) thread."""
        loaded, pending = self.inventory_for_sync()
        jobs, errors = self.prepare_pending_keys(pending)
        return self.apply_restore_jobs(loaded, jobs, errors)

    def _ensure_basemap(self) -> None:
        if self._basemaps is None:
            return
        try:
            self._basemaps.ensure_basemap()
        except Exception as exc:  # noqa: BLE001
            LOG.warning(
                "Basemap setup during sync failed: %s", type(exc).__name__
            )
