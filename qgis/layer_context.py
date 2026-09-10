# -*- coding: utf-8 -*-
"""Layer-tree jobs menu + map-canvas TDEI actions on map-search areas."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Set

from qgis.PyQt.QtCore import QCoreApplication, QObject
from qgis.PyQt.QtWidgets import QMenu

from ..core.exceptions import AuthenticationError, SessionExpiredError, TdeiError
from ..core.models import DatasetLocalState, DatasetLoadResult
from ..logging.logger import get_logger
from ..ui.busy import busy_action
from ..ui.jobs.runner import run_dataset_job

if TYPE_CHECKING:
    from ..core.services.container import ServiceContainer

LOG = get_logger(__name__)

_GEOJSON_ONLY_TIP = (
    "Select GeoJSON layers named like *.nodes.geojson, *.edges.geojson, "
    "*.lines.geojson, *.points.geojson, *.polygons.geojson, or *.zones.geojson."
)


def _is_publish_status(status: str) -> bool:
    return str(status or "").strip().casefold() == "publish"


def _prop_bool(layer, key: str, default: bool = False) -> bool:
    if layer is None:
        return default
    try:
        raw = layer.customProperty(key)
    except Exception:  # noqa: BLE001
        return default
    if raw is None or raw == "":
        return default
    text = str(raw).strip().casefold()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def _view_osw_block_reason(
    status: str,
    *,
    group_allowed: bool,
    dataset_allowed: bool,
) -> str:
    """Return empty if View OSW is allowed, else a short reason key."""
    if not _is_publish_status(status):
        return "not_published"
    if not group_allowed:
        return "group"
    if not dataset_allowed:
        return "dataset"
    return ""


class LayerContextMenuController(QObject):
    """TDEI parent menu on map-search areas; Jobs on loaded dataset layers."""

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._attached = False
        self._canvas = None
        self._loading_ids: Set[str] = set()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("TDEI", message)

    def attach(self) -> None:
        if self._attached:
            return
        # Jobs submenu (layer tree) — only when the jobs feature is on.
        if self._container.settings.feature_enabled("jobs"):
            view = self._container.iface.layerTreeView()
            if view is not None:
                view.contextMenuAboutToShow.connect(self._on_layer_tree_menu)
        # Inject TDEI menu into the native QGIS map canvas context menu.
        self._attach_canvas()
        self._attached = True

    def detach(self) -> None:
        if not self._attached:
            return
        view = self._container.iface.layerTreeView()
        if view is not None:
            try:
                view.contextMenuAboutToShow.disconnect(self._on_layer_tree_menu)
            except TypeError:
                pass
        self._detach_canvas()
        self._attached = False

    def _attach_canvas(self) -> None:
        canvas = None
        try:
            canvas = self._container.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is None:
            return
        if self._canvas is not None and self._canvas is not canvas:
            self._detach_canvas()
        self._canvas = canvas
        try:
            canvas.contextMenuAboutToShow.connect(self._on_canvas_menu)
        except Exception:  # noqa: BLE001
            LOG.exception(
                "Could not connect map canvas contextMenuAboutToShow "
                "(needs QGIS 3.16+)"
            )
            self._canvas = None

    def _detach_canvas(self) -> None:
        canvas = self._canvas
        self._canvas = None
        if canvas is None:
            return
        try:
            canvas.contextMenuAboutToShow.disconnect(self._on_canvas_menu)
        except Exception:  # noqa: BLE001
            pass

    def _on_canvas_menu(self, menu, event) -> None:
        """Extend the native canvas menu when over a map-search area."""
        if menu is None or event is None:
            return
        canvas = self._canvas
        if canvas is None:
            try:
                canvas = self._container.iface.mapCanvas()
            except Exception:  # noqa: BLE001
                return
        try:
            pos = event.pos()
        except Exception:  # noqa: BLE001
            return
        hit = self._container.layers.map_search_hit_at_canvas_pos(
            canvas, pos, select=True
        )
        if not hit:
            return
        dataset_id, display_name, layer = hit
        status = ""
        try:
            status = str(layer.customProperty("tdei_status") or "").strip()
        except Exception:  # noqa: BLE001
            status = ""
        first = menu.actions()[0] if menu.actions() else None
        tdei = QMenu(self.tr("TDEI"), menu)
        self._populate_tdei_actions(
            tdei,
            dataset_id,
            display_name,
            status=status,
            boundary_layer=layer,
            group_allowed=_prop_bool(
                layer, "tdei_group_data_viewer_allowed", False
            ),
            dataset_allowed=_prop_bool(
                layer, "tdei_data_viewer_allowed", False
            ),
        )
        if first is not None:
            menu.insertMenu(first, tdei)
            menu.insertSeparator(first)
        else:
            menu.addMenu(tdei)

    def _on_layer_tree_menu(self, menu) -> None:
        view = self._container.iface.layerTreeView()
        if view is None:
            return
        node = view.currentNode()
        dataset_id = self._container.layers.dataset_id_from_node(node)
        if not dataset_id:
            return

        layer = node.layer() if hasattr(node, "layer") else None
        is_map_search = False
        if layer is not None:
            is_map_search = self._container.layers.is_map_search_layer(layer)
        elif hasattr(node, "customProperty"):
            is_map_search = (
                str(node.customProperty("tdei_map_search") or "") == "1"
                or str(node.customProperty("tdei_map_search_group") or "") == "1"
            )

        # Map-search overlays: TDEI → Download / View OSW (no jobs).
        if is_map_search:
            display = dataset_id
            status = ""
            group_allowed = False
            dataset_allowed = False
            if layer is not None:
                display = (
                    str(layer.customProperty("tdei_display_name") or "").strip()
                    or dataset_id
                )
                status = str(layer.customProperty("tdei_status") or "").strip()
                group_allowed = _prop_bool(
                    layer, "tdei_group_data_viewer_allowed", False
                )
                dataset_allowed = _prop_bool(
                    layer, "tdei_data_viewer_allowed", False
                )
            menu.addSeparator()
            tdei = menu.addMenu(self.tr("TDEI"))
            self._populate_tdei_actions(
                tdei,
                dataset_id,
                display,
                status=status,
                boundary_layer=layer,
                group_allowed=group_allowed,
                dataset_allowed=dataset_allowed,
            )
            return

        if not self._container.settings.feature_enabled("jobs"):
            return
        self._add_jobs_submenu(menu, dataset_id)

    def _populate_tdei_actions(
        self,
        menu: QMenu,
        dataset_id: str,
        display_name: str,
        *,
        status: str = "",
        boundary_layer=None,
        group_allowed: bool = False,
        dataset_allowed: bool = False,
    ) -> None:
        """Fill a TDEI submenu: Download (or Zoom) + View OSW."""
        self._populate_download_actions(menu, dataset_id, display_name)
        menu.addSeparator()
        self._populate_view_osw_action(
            menu,
            dataset_id,
            display_name,
            status=status,
            boundary_layer=boundary_layer,
            group_allowed=group_allowed,
            dataset_allowed=dataset_allowed,
        )

    def _populate_download_actions(
        self, menu: QMenu, dataset_id: str, display_name: str
    ) -> None:
        state = self._container.datasets.local_state(dataset_id)
        downloading = dataset_id in self._loading_ids

        if state == DatasetLocalState.LOADED:
            zoom = menu.addAction(self.tr("Zoom to dataset"))
            zoom.setToolTip(
                self.tr("Already in the project — zoom to this dataset")
            )
            zoom.triggered.connect(partial(self._zoom_dataset, dataset_id))
            return

        if downloading:
            action = menu.addAction(self.tr("Downloading…"))
            action.setEnabled(False)
            return

        label = (
            self.tr("Add to map (cached)")
            if state == DatasetLocalState.CACHED
            else self.tr("Download")
        )
        action = menu.addAction(label)
        action.setToolTip(
            self.tr("Download OSW layers into the TDEI project group.")
        )
        action.triggered.connect(
            partial(self._download_dataset, dataset_id, display_name)
        )

    def _populate_view_osw_action(
        self,
        menu: QMenu,
        dataset_id: str,
        display_name: str,
        *,
        status: str = "",
        boundary_layer=None,
        group_allowed: bool = False,
        dataset_allowed: bool = False,
    ) -> None:
        preview = getattr(self._container, "osw_preview", None)
        viewing = bool(
            preview is not None and preview.is_viewing(dataset_id)
        )
        if viewing:
            action = menu.addAction(self.tr("Stop viewing OSW"))
            action.setToolTip(self.tr("Remove the streamed OSW preview layers."))
            action.triggered.connect(self._stop_view_osw)
            return

        reason = _view_osw_block_reason(
            status,
            group_allowed=group_allowed,
            dataset_allowed=dataset_allowed,
        )
        if reason == "not_published":
            label = self.tr("View OSW (not published)")
            tip = self.tr("View OSW is available for Publish datasets only.")
        elif reason == "group":
            label = self.tr("View OSW (not enabled at project group)")
            tip = self.tr(
                "Data viewer is not enabled for this project group."
            )
        elif reason == "dataset":
            label = self.tr("View OSW (not enabled at dataset)")
            tip = self.tr(
                "PMTiles viewing is not enabled for this dataset."
            )
        else:
            label = self.tr("View OSW")
            tip = self.tr(
                "Stream OSW vector tiles for this Publish dataset. "
                "Closes when you pan outside the area."
            )

        action = menu.addAction(label)
        action.setToolTip(tip)
        if reason:
            action.setEnabled(False)
            return
        action.triggered.connect(
            partial(
                self._view_osw,
                dataset_id,
                display_name,
                boundary_layer,
            )
        )

    def _view_osw(self, dataset_id: str, display_name: str, boundary_layer) -> None:
        preview = getattr(self._container, "osw_preview", None)
        if preview is None:
            self._container.notifications.error(
                self.tr("OSW preview is not available.")
            )
            return
        preview.start(
            dataset_id,
            display_name,
            boundary_layer=boundary_layer,
        )

    def _stop_view_osw(self) -> None:
        preview = getattr(self._container, "osw_preview", None)
        if preview is not None:
            preview.stop()

    def _add_jobs_submenu(self, menu, dataset_id: str) -> None:
        jobs = self._container.jobs.list_layer_menu_jobs()
        if not jobs:
            return
        can_package = self._container.layers.osw_package_selection_ok(
            dataset_id
        )
        submenu = menu.addMenu(self.tr("TDEI Jobs"))
        for job in jobs:
            action = submenu.addAction(job.title)
            action.setEnabled(can_package)
            if not can_package:
                action.setToolTip(_GEOJSON_ONLY_TIP)
                action.setStatusTip(_GEOJSON_ONLY_TIP)
            else:
                selected = self._container.layers.selected_layers_in_dataset(
                    dataset_id
                )
                if selected:
                    action.setToolTip(
                        self.tr(
                            "Zip OSW-named GeoJSON layer(s) "
                            "({n} matching) and run {title}."
                        ).format(
                            n=len(
                                self._container.layers.classify_osw_upload_layers(
                                    dataset_id
                                )[0]
                            ),
                            title=job.title,
                        )
                    )
                else:
                    action.setToolTip(
                        self.tr(
                            "Zip OSW-named GeoJSON layers in this group "
                            "and run {title}."
                        ).format(title=job.title)
                    )
            action.triggered.connect(
                lambda checked=False, current=job, did=dataset_id: self._run_job(
                    current, did
                )
            )

    def _run_job(self, job, dataset_id: str) -> None:
        if not self._container.layers.osw_package_selection_ok(dataset_id):
            self._container.notifications.warning(_GEOJSON_ONLY_TIP)
            return
        run_dataset_job(
            self._container,
            job,
            dataset_id,
            parent=self._container.iface.mainWindow(),
        )

    def _zoom_dataset(self, dataset_id: str) -> None:
        try:
            with busy_action(
                self._container, self.tr("Zooming to dataset…")
            ):
                self._container.datasets.ensure_basemap()
                self._container.layers.zoom_to_dataset(dataset_id)
            self._container.notifications.success(
                self.tr("Checked layers and zoomed to the dataset group.")
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Zoom from map-search context failed: %s", exc)
            self._container.notifications.error(
                self.tr("Could not zoom to that dataset.")
            )

    def _download_dataset(self, dataset_id: str, display_name: str) -> None:
        if not dataset_id or dataset_id in self._loading_ids:
            return
        if not self._container.auth.is_authenticated():
            self._container.notifications.warning(
                self.tr("Sign in first, then download the dataset.")
            )
            open_fn = getattr(self._container, "open_main_window", None)
            if callable(open_fn):
                open_fn()
            return

        self._loading_ids.add(dataset_id)
        self._container.status.show(
            self.tr("Downloading {name}…").format(
                name=display_name or dataset_id
            ),
            0,
        )
        project_gen = self._container.project.generation
        worker = self._container.workers.submit(
            self._container.datasets.prepare_package, dataset_id
        )
        worker.signals.result.connect(
            partial(
                self._on_package_ready,
                dataset_id,
                display_name,
                project_gen,
            )
        )
        worker.signals.error.connect(
            partial(self._on_download_error, dataset_id)
        )

    def _on_package_ready(
        self,
        dataset_id: str,
        display_name: str,
        project_gen: int,
        prepared,
    ) -> None:
        if project_gen != self._container.project.generation:
            self._loading_ids.discard(dataset_id)
            self._container.status.ready(
                self.tr(
                    "Download kept in cache — QGIS project changed before "
                    "layers were added."
                )
            )
            return
        try:
            geojsons, source = prepared
        except Exception:  # noqa: BLE001
            self._on_download_error(dataset_id, prepared)
            return
        self._container.status.show(self.tr("Adding layers to QGIS…"), 0)
        try:
            self._container.datasets.ensure_basemap()
            result = self._container.datasets.add_to_map(
                dataset_id,
                geojsons,
                source,
                display_name=display_name or "",
                zoom=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._on_download_error(dataset_id, exc)
            return
        self._loading_ids.discard(dataset_id)
        self._on_download_success(result)

    def _on_download_success(self, result: DatasetLoadResult) -> None:
        hook = getattr(self._container, "on_dataset_loaded", None)
        if callable(hook):
            try:
                hook(result)
                return
            except Exception:  # noqa: BLE001
                LOG.exception("on_dataset_loaded hook failed")
        if result.source == "already_loaded":
            msg = self.tr(
                "Dataset is already loaded. Use Zoom to map when ready."
            )
        elif result.source == "cache":
            msg = self.tr(
                "Added {n} layer(s) from cache. Available under Mapped."
            ).format(n=result.layer_count)
        else:
            msg = self.tr(
                "Loaded {n} layer(s) into QGIS. Available under Mapped."
            ).format(n=result.layer_count)
        self._container.status.ready(msg)
        self._container.notifications.success(msg)

    def _on_download_error(self, dataset_id: str, exc) -> None:
        self._loading_ids.discard(dataset_id)
        if isinstance(exc, (AuthenticationError, SessionExpiredError)):
            self._container.status.ready(
                self.tr("Session expired. Please sign in again.")
            )
            self._container.notifications.warning(
                self.tr("Your session has expired. Please sign in again.")
            )
            return
        message = (
            str(exc)
            if isinstance(exc, TdeiError)
            else self.tr("Could not load dataset: {}").format(exc)
        )
        self._container.status.ready(message)
        self._container.notifications.error(message)
