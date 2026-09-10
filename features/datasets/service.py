# -*- coding: utf-8 -*-
"""Dataset use cases."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from ...api.v1.datasets import edit_metadata_path, osw_pmtiles_path, parse_datasets
from ...core.models import (
    Dataset,
    DatasetLoadResult,
    DatasetLocalState,
    DatasetScope,
    MappedItem,
)
from ...features.jobs.bbox import bbox_as_list
from ...features.osw.generate_dataset_area import generate_dataset_area_geojson
from ...features.osw.metadata import (
    DATASET_AREA_FILENAME,
    has_valid_dataset_area,
    load_geojson_file,
    metadata_from_dataset_raw,
    write_metadata_with_dataset_area,
    with_dataset_area_path,
)
from ...features.osw.package import assert_zip_bytes, unpack_osw_package
from ...logging.logger import get_logger

if TYPE_CHECKING:
    from ...api.client import ApiClient
    from ...config.settings import SettingsManager
    from ...features.project_groups.service import ProjectGroupService
    from ...qgis.layer_manager import LayerManager

LOG = get_logger(__name__)

BBoxInput = Union[str, Sequence[float]]


class DatasetService:
    def __init__(
        self,
        api_client: "ApiClient",
        layer_manager: "LayerManager",
        settings: "SettingsManager",
        basemap_manager=None,
        project_groups: Optional["ProjectGroupService"] = None,
    ) -> None:
        self._api = api_client
        self._layers = layer_manager
        self._settings = settings
        self._basemaps = basemap_manager
        self._project_groups = project_groups
        self._cache: List[Dataset] = []

    def list_datasets(
        self,
        *,
        use_cache: bool = False,
        name: str = "",
        dataset_id: str = "",
        scope: Optional[DatasetScope] = None,
        project_group_id: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10,
        bbox: Optional[BBoxInput] = None,
        data_type: Optional[str] = None,
        status: str = "All",
    ) -> List[Dataset]:
        if (
            use_cache
            and self._cache
            and not any((name, dataset_id, scope, bbox, data_type))
            and page_no == 1
            and (status or "All").strip() in ("", "All")
        ):
            return list(self._cache)

        params = self._build_list_params(
            name=name,
            dataset_id=dataset_id,
            scope=scope,
            project_group_id=project_group_id,
            page_no=page_no,
            page_size=page_size,
            bbox=bbox,
            data_type=data_type,
            status=status,
        )
        payload = self._api.get("datasets", params=params)
        datasets = parse_datasets(payload)
        if not any((name, dataset_id, bbox)) and page_no == 1:
            self._cache = datasets
        LOG.info("Loaded %s datasets (page %s)", len(datasets), page_no)
        return list(datasets)

    def list_datasets_in_bbox(
        self,
        bbox: Optional[BBoxInput] = None,
        *,
        page_size: int = 50,
        scope: Optional[DatasetScope] = None,
        project_group_id: Optional[str] = None,
        name: str = "",
        status: str = "All",
    ) -> List[Dataset]:
        """GET OSW datasets, optionally filtered by *bbox* (W,S,E,N).

        Default scope is my groups (``include_my_groups=true``). Pass
        ``DatasetScope.ALL`` to apply no project-group filter (admin). When
        *project_group_id* is set, filters by ``tdei_project_group_id``.
        Optional *name* filters by dataset name. Pass ``bbox=None`` to
        search without a map-extent filter (name search).
        *status* is the API release status (``All``, ``Publish``, ``Pre-Release``).
        """
        selected = (project_group_id or "").strip()
        return self.list_datasets(
            use_cache=False,
            name=(name or "").strip(),
            scope=scope or DatasetScope.MY_PROJECT_GROUPS,
            project_group_id=selected or None,
            page_no=1,
            page_size=max(1, min(int(page_size), 50)),
            bbox=bbox,
            data_type="osw",
            status=status,
        )

    def _build_list_params(
        self,
        *,
        name: str,
        dataset_id: str,
        scope: Optional[DatasetScope],
        project_group_id: Optional[str],
        page_no: int,
        page_size: int,
        bbox: Optional[BBoxInput] = None,
        data_type: Optional[str] = None,
        status: str = "All",
    ) -> dict:
        status_value = (status or "All").strip() or "All"
        params = {
            "page_no": max(1, int(page_no)),
            "page_size": max(1, min(int(page_size), 100)),
            "sort_field": "uploaded_timestamp",
            "sort_order": "DESC",
            "status": status_value,
        }
        if name.strip():
            params["name"] = name.strip()
        if dataset_id.strip():
            params["tdei_dataset_id"] = dataset_id.strip()
        if bbox is not None:
            params["bbox"] = bbox_as_list(bbox)
        dtype = (data_type or "").strip()
        if dtype:
            params["data_type"] = dtype

        active_scope = scope or DatasetScope.MY_PROJECT_GROUPS
        selected_id = (project_group_id or "").strip()

        if selected_id:
            params["tdei_project_group_id"] = selected_id
        elif active_scope == DatasetScope.ALL:
            # No project-group filter (e.g. tdei-admin map search default).
            pass
        else:
            # Default / My Project Groups
            params["include_my_groups"] = True
        return params

    def invalidate_cache(self) -> None:
        self._cache = []

    def fetch_osw_pmtiles_url(self, dataset_id: str) -> str:
        """Return a time-limited SAS URL for the dataset's OSW PMTiles archive.

        Calls ``GET osw/dataset-viewer/pm-tiles/{tdei_dataset_id}`` (auth required).
        Publish datasets with viewer access and generated PMTiles only.
        """
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            raise ValueError("Dataset id is required.")
        path = osw_pmtiles_path(dataset_id)
        url = (self._api.get_text(path) or "").strip()
        if not url or not url.startswith("http"):
            raise ValueError(
                "PMTiles URL was not returned for this dataset. "
                "It may not be published or viewer access may be disabled."
            )
        return url

    def local_state(self, dataset_id: str) -> DatasetLocalState:
        if self._layers.is_dataset_loaded(dataset_id):
            return DatasetLocalState.LOADED
        if self.has_local_package(dataset_id):
            return DatasetLocalState.CACHED
        return DatasetLocalState.REMOTE

    def has_local_package(self, dataset_id: str) -> bool:
        cache_dir = self._layers.cache_path_for(dataset_id)
        zip_path = os.path.join(cache_dir, "package.zip")
        if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0:
            return True
        return bool(self._existing_geojsons(cache_dir))

    def dataset_area_defined(self, dataset_id: str) -> Optional[bool]:
        """Whether local package ``metadata.json`` has a valid ``dataset_area``.

        Returns ``None`` when the dataset is not downloaded yet.
        """
        if not self.has_local_package(dataset_id):
            return None
        return has_valid_dataset_area(self._layers.cache_path_for(dataset_id))

    def add_dataset_area(
        self,
        dataset_id: str,
        *,
        metadata: Optional[dict] = None,
        raw: Optional[dict] = None,
    ) -> Tuple[str, str, bool]:
        """Build concave-hull area, patch API metadata, PUT editMetadata.

        Metadata is taken from the datasets API response (``raw`` / ``metadata``),
        not from a downloaded package. OSW layers are still required locally to
        compute the hull (download/extract first if needed).

        :returns: ``(area_path, source_kind, added_to_map)``
        """
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            raise ValueError("Dataset id is required.")

        if metadata is None and raw is not None:
            metadata = metadata_from_dataset_raw(raw)
        if metadata is None:
            metadata = self.fetch_dataset_metadata(dataset_id)

        if not self.has_local_package(dataset_id):
            raise ValueError(
                "Local OSW layers are required to build the dataset area. "
                "Download the dataset first."
            )
        cache_dir = self._layers.cache_path_for(dataset_id)
        sources = [
            path
            for path in self._existing_geojsons(cache_dir)
            if os.path.basename(path).lower() != DATASET_AREA_FILENAME
        ]
        area_path, kind = generate_dataset_area_geojson(cache_dir, sources)
        area_geojson = load_geojson_file(area_path)
        if area_geojson is None:
            raise ValueError("Could not read generated dataset_area.geojson.")
        metadata_path = write_metadata_with_dataset_area(
            cache_dir, metadata, area_geojson
        )
        self._upload_metadata(dataset_id, metadata_path)

        added = False
        try:
            added = bool(self._layers.ensure_dataset_area_layer(dataset_id))
            if added:
                self._layers.set_dataset_area_visible(dataset_id, True)
        except Exception:  # noqa: BLE001
            LOG.warning(
                "Added dataset_area for %s but could not add map layer",
                dataset_id,
                exc_info=True,
            )
        return area_path, kind, added

    def fetch_dataset_metadata(self, dataset_id: str) -> dict:
        """GET datasets filtered by id and return the embedded metadata object."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            raise ValueError("Dataset id is required.")
        rows = self.list_datasets(
            use_cache=False,
            dataset_id=dataset_id,
            scope=DatasetScope.ALL,
            page_no=1,
            page_size=1,
            data_type="osw",
            status="All",
        )
        if not rows:
            rows = self.list_datasets(
                use_cache=False,
                dataset_id=dataset_id,
                scope=DatasetScope.MY_PROJECT_GROUPS,
                page_no=1,
                page_size=1,
                data_type="osw",
                status="All",
            )
        if not rows:
            raise ValueError(
                "Could not load dataset metadata from the API."
            )
        return metadata_from_dataset_raw(rows[0].raw)

    def _upload_metadata(self, dataset_id: str, metadata_path: str) -> None:
        """PUT /api/v1/metadata/{tdei_dataset_id} with multipart metadata file."""
        if not metadata_path or not os.path.isfile(metadata_path):
            raise ValueError("Updated metadata.json is missing.")
        url = "{}/{}".format(
            self._api.base_url.rstrip("/"),
            edit_metadata_path(dataset_id).lstrip("/"),
        )
        LOG.info("Uploading metadata for %s via editMetadata", dataset_id)
        self._api.put_multipart(url, files={"file": metadata_path})

    def prepare_package(self, dataset_id: str) -> Tuple[List[str], str]:
        """Download/extract OSW files (background-safe). Does not touch QgsProject.

        :returns: (geojson_paths, source) where source is ``cache`` or ``download``
        """
        cache_dir = self._layers.cache_dir_for(dataset_id)
        zip_path = os.path.join(cache_dir, "package.zip")
        extract_dir = os.path.join(cache_dir, "extracted")
        geojsons = self._existing_geojsons(cache_dir)

        if geojsons:
            LOG.info("Reusing extracted GeoJSON for %s", dataset_id)
            return with_dataset_area_path(cache_dir, geojsons), "cache"

        if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 0:
            LOG.info("Reusing cached OSW zip for %s", dataset_id)
            geojsons = unpack_osw_package(zip_path, extract_dir)
            return with_dataset_area_path(cache_dir, geojsons), "cache"

        LOG.info("Downloading OSW package for %s", dataset_id)
        data = self._api.download_bytes(
            "osw/{}".format(quote(str(dataset_id), safe="")),
            query="?format=osw&file_version=latest",
        )
        assert_zip_bytes(data)
        parent = os.path.dirname(zip_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(zip_path, "wb") as handle:
            handle.write(data)
        geojsons = unpack_osw_package(zip_path, extract_dir)
        return with_dataset_area_path(cache_dir, geojsons), "download"

    def add_to_map(
        self,
        dataset_id: str,
        geojsons: List[str],
        source: str,
        *,
        display_name: str = "",
        zoom: bool = True,
    ) -> DatasetLoadResult:
        """Add layers to QGIS — must run on the main/UI thread."""
        self._ensure_basemap()
        if self._layers.is_dataset_loaded(dataset_id):
            try:
                self._layers.ensure_dataset_area_layer(dataset_id)
            except Exception:  # noqa: BLE001
                LOG.warning(
                    "Could not attach dataset_area under group %s", dataset_id
                )
            if zoom:
                self._layers.zoom_to_dataset(dataset_id)
            return DatasetLoadResult(
                dataset_id=dataset_id,
                layer_count=0,
                source="already_loaded",
            )
        layers = self._layers.load_geojsons(
            dataset_id,
            geojsons,
            display_name=display_name,
            zoom=zoom,
        )
        try:
            self._layers.ensure_dataset_area_layer(dataset_id)
        except Exception:  # noqa: BLE001
            LOG.warning(
                "Could not attach dataset_area under group %s", dataset_id
            )
        return DatasetLoadResult(
            dataset_id=dataset_id,
            layer_count=len(layers),
            source=source,
        )

    def remove_from_map(self, dataset_id: str, *, clear_cache: bool = True) -> bool:
        """Remove dataset layers from QGIS and optionally wipe local cache."""
        removed = self._layers.remove_dataset_group(dataset_id)
        if clear_cache:
            self._layers.clear_cache(dataset_id)
        return removed

    def list_mapped(self) -> List[MappedItem]:
        return self._layers.list_mapped_items(jobs=False)

    def ensure_basemap(self) -> None:
        self._ensure_basemap()

    def _ensure_basemap(self) -> None:
        if self._basemaps is None:
            return
        try:
            self._basemaps.ensure_basemap()
        except Exception as exc:  # noqa: BLE001 — basemap must not block load
            LOG.warning("Basemap setup failed: %s", type(exc).__name__)

    def load_into_qgis(self, dataset_id: str) -> DatasetLoadResult:
        """Convenience for tests — prefer prepare_package + add_to_map in UI."""
        if self._layers.is_dataset_loaded(dataset_id):
            self._layers.zoom_to_dataset(dataset_id)
            return DatasetLoadResult(
                dataset_id=dataset_id,
                layer_count=0,
                source="already_loaded",
            )
        geojsons, source = self.prepare_package(dataset_id)
        return self.add_to_map(dataset_id, geojsons, source)

    @staticmethod
    def _existing_geojsons(cache_dir: str) -> List[str]:
        found: List[str] = []
        if not os.path.isdir(cache_dir):
            return found
        for dirpath, _dirnames, filenames in os.walk(cache_dir):
            for name in filenames:
                lower = name.lower()
                if lower == "metadata.json":
                    continue
                if lower.endswith(".geojson"):
                    found.append(os.path.join(dirpath, name))
        return found
