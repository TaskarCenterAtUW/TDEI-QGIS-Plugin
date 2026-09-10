# -*- coding: utf-8 -*-
"""Viewport bbox → GET /datasets map search controller."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QTimer
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

from ..core.exceptions import AuthenticationError, SessionExpiredError, TdeiError
from ..core.models import DatasetScope
from ..features.jobs.bbox import format_bbox_csv
from ..logging.logger import get_logger
from ..ui.dialogs.map_search_bar import MapSearchBar

if TYPE_CHECKING:
    from ..core.services.container import ServiceContainer

LOG = get_logger(__name__)

MAP_SEARCH_MAX_SCALE = 1290462.0
_DEBOUNCE_MS = 400


class MapSearchController(QObject):
    """Active map-search session: scale gate + debounced bbox list."""

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._bar = None  # type: Optional[MapSearchBar]
        self._active = False
        self._zoom_ok = False
        self._watching = False
        self._fetch_gen = 0
        self._project_group_id = ""
        self._name_filter = ""
        self._status_filter = "All"
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._run_search)
        self._on_stopped = None  # type: Optional[Callable]
        self._canvas = None
        # After picking a result we zoom the map — don't refresh the list yet.
        self._suspend_view_search = False
        self._resume_view_timer = QTimer(self)
        self._resume_view_timer.setSingleShot(True)
        self._resume_view_timer.setInterval(2000)
        self._resume_view_timer.timeout.connect(self._end_view_search_suspend)
        self._adding_area_ids = set()  # type: set
        self._last_datasets = []  # type: list
        try:
            self._container.auth.logged_out.connect(self._on_auth_session_changed)
            self._container.auth.login_succeeded.connect(
                self._on_auth_session_changed
            )
            self._container.auth.session_expired.connect(
                self._on_auth_session_changed
            )
        except Exception:  # noqa: BLE001
            LOG.debug("Could not connect map-search auth reload hooks", exc_info=True)

    @property
    def active(self) -> bool:
        return self._active

    def start(self, *, on_stopped: Optional[Callable] = None) -> bool:
        if self._active:
            return True

        iface = self._container.iface
        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is None:
            self._container.notifications.error(
                self.tr("Map canvas is not available.")
            )
            return False

        if not self._container.auth.is_authenticated():
            # Open the TDEI sign-in panel; avoid a scary yellow toast on first use.
            open_fn = getattr(self._container, "open_main_window", None)
            if callable(open_fn):
                open_fn()
            else:
                self._container.notifications.warning(
                    self.tr("Sign in first, then search the map.")
                )
            return False

        # Avoid conflicting exclusive clip mode.
        clip = getattr(self._container, "bbox_capture", None)
        if clip is not None and getattr(clip, "active", False):
            try:
                clip.cancel()
            except Exception:  # noqa: BLE001
                pass

        self._on_stopped = on_stopped
        self._active = True
        self._canvas = canvas
        self._fetch_gen = 0
        self._project_group_id = ""
        self._name_filter = ""
        self._status_filter = "All"

        try:
            self._container.datasets.ensure_basemap()
        except Exception:  # noqa: BLE001
            pass

        try:
            main = iface.mainWindow()
            if main is not None:
                main.raise_()
                main.activateWindow()
        except Exception:  # noqa: BLE001
            pass

        self._show_bar()
        self._load_project_groups()
        self._connect_canvas(canvas)
        self._evaluate_scale(trigger_search=True)
        self._container.status.show(
            self.tr("Map search active."), 3000
        )
        return True

    def stop(self) -> None:
        if not self._active and self._bar is None:
            return
        self._active = False
        self._debounce.stop()
        self._resume_view_timer.stop()
        self._suspend_view_search = False
        self._fetch_gen += 1
        self._disconnect_canvas()
        self._hide_bar()
        try:
            self._container.layers.clear_map_search_layers()
        except Exception:  # noqa: BLE001
            LOG.exception("Could not clear map-search layers")
        try:
            self._container.status.ready(self.tr("Map search stopped."))
        except Exception:  # noqa: BLE001
            pass
        callback = self._on_stopped
        self._on_stopped = None
        self._canvas = None
        self._project_group_id = ""
        self._name_filter = ""
        self._status_filter = "All"
        if callable(callback):
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

    def tr(self, message: str) -> str:
        from qgis.PyQt.QtCore import QCoreApplication

        return QCoreApplication.translate("TDEI", message)

    def _show_bar(self) -> None:
        iface = getattr(self._container, "iface", None)
        if self._bar is None:
            parent = self._canvas
            self._bar = MapSearchBar(parent)
            self._bar.bind_iface(iface)
            self._bar.closed.connect(self.stop)
            self._bar.project_group_changed.connect(self._on_project_group_changed)
            self._bar.status_filter_changed.connect(self._on_status_filter_changed)
            self._bar.name_filter_changed.connect(self._on_name_filter_changed)
            self._bar.ignore_map_extent_changed.connect(
                self._on_ignore_map_extent_changed
            )
            self._bar.dataset_selected.connect(self._on_dataset_selected)
            self._bar.dataset_zoom_requested.connect(self._on_dataset_zoom_requested)
            self._bar.add_dataset_area_requested.connect(
                self._on_add_dataset_area_requested
            )
        else:
            self._bar.bind_iface(iface)
        self._refresh_name_suggestions()
        if self._canvas is not None:
            self._bar.position_on_canvas(self._canvas)
        else:
            self._bar.show()
            self._bar.raise_()

    def _refresh_name_suggestions(self) -> None:
        """Load display names from local OSW cache for name-field autocomplete."""
        if self._bar is None:
            return
        try:
            names = self._container.layers.list_cached_display_names()
        except Exception:  # noqa: BLE001
            LOG.exception("Could not load cached dataset names for map search")
            names = []
        self._bar.set_name_suggestions(names)

    def _hide_bar(self) -> None:
        if self._bar is None:
            return
        try:
            self._bar.closed.disconnect(self.stop)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.project_group_changed.disconnect(
                self._on_project_group_changed
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.status_filter_changed.disconnect(
                self._on_status_filter_changed
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.name_filter_changed.disconnect(
                self._on_name_filter_changed
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.ignore_map_extent_changed.disconnect(
                self._on_ignore_map_extent_changed
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.dataset_selected.disconnect(self._on_dataset_selected)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.dataset_zoom_requested.disconnect(
                self._on_dataset_zoom_requested
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.add_dataset_area_requested.disconnect(
                self._on_add_dataset_area_requested
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self._bar.detach_from_canvas()
        except Exception:  # noqa: BLE001
            pass
        self._bar.hide()
        self._bar.deleteLater()
        self._bar = None
        self._adding_area_ids.clear()
        self._last_datasets = []

    def _load_project_groups(self) -> None:
        """Fill the widget combo; default selection is My Project Groups."""
        if self._bar is None:
            return
        selected = ""
        try:
            current = self._container.project_groups.selected()
            if current is not None and getattr(current, "id", ""):
                selected = str(current.id).strip()
        except Exception:  # noqa: BLE001
            selected = ""
        # Prefer "My Project Groups" / admin "All groups" as the map-search default.
        self._project_group_id = ""
        self._bar.set_project_groups(
            [], selected_id="", admin_mode=self._is_tdei_admin()
        )

        worker = self._container.workers.submit(
            self._container.project_groups.list_project_groups, use_cache=False
        )
        worker.signals.result.connect(self._on_project_groups_loaded)
        worker.signals.error.connect(self._on_project_groups_error)

    def _on_auth_session_changed(self, *_args) -> None:
        """Logout/login: drop cached groups and refresh the map-search combo."""
        try:
            self._container.project_groups.clear_session_state()
        except Exception:  # noqa: BLE001
            LOG.debug("Could not clear project-group session state", exc_info=True)
        try:
            self._container.datasets.invalidate_cache()
        except Exception:  # noqa: BLE001
            pass
        if not self._active or self._bar is None:
            return
        self._project_group_id = ""
        self._load_project_groups()
        # Re-run search under the new user's scope (admin vs my-groups).
        if self._zoom_ok or self._bar.ignore_map_extent():
            self._debounce.start()

    def _is_tdei_admin(self) -> bool:
        try:
            return bool(self._container.auth.is_tdei_admin())
        except Exception:  # noqa: BLE001
            return False

    def _map_search_scope(self, group_id: str):
        """Admin with no group → no filter; otherwise my-groups or selected id."""
        if str(group_id or "").strip():
            return DatasetScope.MY_PROJECT_GROUPS
        if self._is_tdei_admin():
            return DatasetScope.ALL
        return DatasetScope.MY_PROJECT_GROUPS

    def _on_project_groups_loaded(self, groups) -> None:
        if not self._active or self._bar is None:
            return
        is_admin = self._is_tdei_admin()
        self._bar.set_project_groups(
            groups or [],
            selected_id="",
            admin_mode=is_admin,
        )
        self._project_group_id = self._bar.selected_project_group_id()
        if self._canvas is not None:
            self._bar.position_on_canvas(self._canvas)

    def _on_project_groups_error(self, exc) -> None:
        if not self._active:
            return
        LOG.warning("Could not load project groups for map search: %s", exc)
        if self._bar is not None:
            self._bar.set_project_groups(
                [], selected_id="", admin_mode=self._is_tdei_admin()
            )

    def _on_project_group_changed(self, group_id: str) -> None:
        if not self._active:
            return
        self._project_group_id = str(group_id or "").strip()
        if self._zoom_ok or (
            self._bar is not None and self._bar.ignore_map_extent()
        ):
            self._debounce.start()

    def _on_status_filter_changed(self, status: str) -> None:
        if not self._active:
            return
        self._status_filter = str(status or "All").strip() or "All"
        self._evaluate_scale(trigger_search=True)

    def _on_name_filter_changed(self, name: str) -> None:
        if not self._active:
            return
        self._name_filter = str(name or "").strip()
        # Name search ignores bbox — allow search even when zoomed out.
        self._evaluate_scale(trigger_search=True)

    def _on_ignore_map_extent_changed(self, _checked: bool) -> None:
        if not self._active:
            return
        self._evaluate_scale(trigger_search=True)

    def _on_dataset_selected(self, dataset_id: str) -> None:
        """Highlight the chosen area on the map without changing zoom."""
        if not self._active:
            return
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            return
        if self._bar is not None:
            try:
                self._bar.select_result(dataset_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._container.layers.select_map_search_dataset(dataset_id)
        except Exception:  # noqa: BLE001
            LOG.exception("Map search highlight failed: %s", dataset_id)

    def _on_dataset_zoom_requested(self, dataset_id: str) -> None:
        """Zoom the map to a result (double-click / Enter on the list)."""
        if not self._active:
            return
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            return
        # Zooming changes extent/scale and would rebuild the result list —
        # keep the current list + scroll until the user pans again.
        self._begin_view_search_suspend()
        try:
            ok = self._container.layers.zoom_to_map_search_dataset(dataset_id)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Map search zoom failed: %s", exc)
            ok = False
            self._end_view_search_suspend()
        if not ok:
            self._container.notifications.warning(
                self.tr(
                    "Dataset area is not available for this dataset — "
                    "cannot zoom."
                )
            )
            return
        try:
            self._container.status.show(
                self.tr("Zoomed to selected dataset."), 2500
            )
        except Exception:  # noqa: BLE001
            pass
        # Keep selection highlight on the chosen row + map area.
        if self._bar is not None:
            try:
                self._bar.select_result(dataset_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._container.layers.select_map_search_dataset(dataset_id)
        except Exception:  # noqa: BLE001
            pass

    def _on_add_dataset_area_requested(self, dataset_id: str) -> None:
        """Concave-hull from OSW layers; metadata from datasets API response."""
        if not self._active:
            return
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id or dataset_id in self._adding_area_ids:
            return
        self._adding_area_ids.add(dataset_id)
        datasets = self._container.datasets
        # Metadata always comes from the list/API response. OSW download is
        # only to supply edges/nodes for the concave hull.
        if datasets.has_local_package(dataset_id):
            self._finish_add_dataset_area(dataset_id)
            return
        if self._bar is not None:
            self._bar.set_busy(
                True, self.tr("Fetching OSW layers to build area…")
            )
        try:
            self._container.status.busy(
                self.tr("Fetching OSW layers to build area…")
            )
        except Exception:  # noqa: BLE001
            pass
        worker = self._container.workers.submit(
            datasets.prepare_package, dataset_id
        )
        worker.signals.result.connect(
            partial(self._on_package_ready_for_area, dataset_id)
        )
        worker.signals.error.connect(
            partial(self._on_add_dataset_area_error, dataset_id)
        )

    def _on_package_ready_for_area(self, dataset_id: str, _prepared) -> None:
        if not self._active:
            self._adding_area_ids.discard(dataset_id)
            if self._bar is not None:
                self._bar.set_busy(False)
            return
        self._finish_add_dataset_area(dataset_id)

    def _raw_for_dataset(self, dataset_id: str):
        """Return datasets-list ``raw`` for *dataset_id* from the last search."""
        wanted = str(dataset_id or "").strip()
        for dataset in self._last_datasets or []:
            if str(getattr(dataset, "id", "") or "").strip() == wanted:
                raw = getattr(dataset, "raw", None)
                return raw if isinstance(raw, dict) else None
        return None

    def _finish_add_dataset_area(self, dataset_id: str) -> None:
        from ..ui.busy import busy_action

        if self._bar is not None:
            self._bar.set_busy(True, self.tr("Adding dataset area…"))
        raw = self._raw_for_dataset(dataset_id)
        try:
            with busy_action(
                self._container, self.tr("Adding dataset area…")
            ):
                _path, kind, added = (
                    self._container.datasets.add_dataset_area(
                        dataset_id, raw=raw
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._on_add_dataset_area_error(dataset_id, exc)
            return

        self._adding_area_ids.discard(dataset_id)
        if self._bar is not None:
            self._bar.set_busy(False)
        try:
            self._container.datasets.invalidate_cache()
        except Exception:  # noqa: BLE001
            pass

        if added:
            self._container.notifications.success(
                self.tr(
                    "Dataset area added from {kind} and metadata updated."
                ).format(kind=kind)
            )
        else:
            self._container.notifications.success(
                self.tr(
                    "Dataset area added from {kind} and metadata updated. "
                    "It will appear on the map after search refreshes."
                ).format(kind=kind)
            )
        try:
            self._container.status.ready(self.tr("Dataset area added."))
        except Exception:  # noqa: BLE001
            pass
        # Refresh list + overlays so the row shows a green area icon.
        if self._zoom_ok or (
            self._bar is not None and self._bar.ignore_map_extent()
        ):
            self._run_search()

    def _on_add_dataset_area_error(self, dataset_id: str, exc) -> None:
        self._adding_area_ids.discard(dataset_id)
        if self._bar is not None:
            self._bar.set_busy(False)
        if isinstance(exc, (AuthenticationError, SessionExpiredError)):
            message = self.tr("Session expired. Please sign in again.")
            self._container.notifications.warning(message)
            self.stop()
            return
        message = str(exc).strip() if exc is not None else ""
        if not message:
            message = self.tr("Could not add dataset area.")
        elif isinstance(exc, TdeiError):
            message = str(exc)
        self._container.notifications.error(message)
        try:
            self._container.status.ready(self.tr("Add dataset area failed."))
        except Exception:  # noqa: BLE001
            pass
        LOG.warning("Add dataset area failed for %s: %s", dataset_id, exc)

    def _begin_view_search_suspend(self) -> None:
        self._suspend_view_search = True
        self._debounce.stop()
        self._resume_view_timer.start()

    def _end_view_search_suspend(self) -> None:
        self._suspend_view_search = False

    def _connect_canvas(self, canvas) -> None:
        if self._watching:
            return
        canvas.extentsChanged.connect(self._on_view_changed)
        canvas.scaleChanged.connect(self._on_view_changed)
        self._watching = True

    def _disconnect_canvas(self) -> None:
        if not self._watching or self._canvas is None:
            self._watching = False
            return
        try:
            self._canvas.extentsChanged.disconnect(self._on_view_changed)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._canvas.scaleChanged.disconnect(self._on_view_changed)
        except Exception:  # noqa: BLE001
            pass
        self._watching = False

    def _on_view_changed(self, *_args) -> None:
        if not self._active:
            return
        # Programmatic zoom from a result click — update scale chrome only.
        if self._suspend_view_search:
            canvas = self._canvas
            if canvas is not None and self._bar is not None:
                try:
                    scale = float(canvas.scale())
                except Exception:  # noqa: BLE001
                    scale = 0.0
                self._zoom_ok = scale <= MAP_SEARCH_MAX_SCALE
                self._bar.set_zoom_ok(self._zoom_ok)
                self._bar.set_scale_display(scale)
            return
        # Name / ignore-extent search is not tied to the map viewport.
        if self._bar is not None and self._bar.ignore_map_extent():
            canvas = self._canvas
            if canvas is not None and self._bar is not None:
                try:
                    scale = float(canvas.scale())
                except Exception:  # noqa: BLE001
                    scale = 0.0
                self._zoom_ok = scale <= MAP_SEARCH_MAX_SCALE
                self._bar.set_zoom_ok(self._zoom_ok)
                self._bar.set_scale_display(scale)
                self._bar.position_on_canvas(canvas)
            return
        self._evaluate_scale(trigger_search=True)

    def _evaluate_scale(self, *, trigger_search: bool) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        try:
            scale = float(canvas.scale())
        except Exception:  # noqa: BLE001
            scale = MAP_SEARCH_MAX_SCALE + 1
        zoom_ok = scale <= MAP_SEARCH_MAX_SCALE
        self._zoom_ok = zoom_ok
        ignore_extent = False
        if self._bar is not None:
            ignore_extent = self._bar.ignore_map_extent()
            self._bar.set_zoom_ok(zoom_ok)
            self._bar.set_scale_display(scale)
            self._bar.position_on_canvas(canvas)

        # Bbox search requires a close enough zoom; name / ignore-extent does not.
        if not zoom_ok and not ignore_extent:
            self._debounce.stop()
            if self._bar is not None:
                self._bar.set_busy(False)
                self._bar.set_results([])
                self._bar.set_result_count(0)
            try:
                self._container.status.ready(
                    self.tr("Zoom in closer to search the map.")
                )
            except Exception:  # noqa: BLE001
                pass
            return

        if trigger_search:
            self._debounce.start()

    def _run_search(self) -> None:
        if not self._active:
            return
        ignore_extent = False
        group_id = self._project_group_id
        name = self._name_filter
        status = self._status_filter
        if self._bar is not None:
            ignore_extent = self._bar.ignore_map_extent()
            group_id = self._bar.selected_project_group_id()
            self._project_group_id = group_id
            name = self._bar.name_filter()
            self._name_filter = name
            status = self._bar.selected_status()
            self._status_filter = status

        if not ignore_extent and not self._zoom_ok:
            return

        canvas = self._canvas
        wsen = None
        bbox_csv = "none"
        if not ignore_extent:
            if canvas is None:
                return
            try:
                wsen = self._extent_wsen(canvas)
                bbox_csv = format_bbox_csv(wsen)
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Could not read map extent: %s", exc)
                self._container.notifications.error(
                    self.tr("Could not read the map extent.")
                )
                return

        self._fetch_gen += 1
        gen = self._fetch_gen
        if self._bar is not None:
            self._bar.set_busy(True)
        try:
            self._container.status.busy(
                self.tr("Searching by name…")
                if ignore_extent
                else self.tr("Searching datasets in view…")
            )
        except Exception:  # noqa: BLE001
            pass

        worker = self._container.workers.submit(
            self._container.datasets.list_datasets_in_bbox,
            wsen,
            page_size=10,
            scope=self._map_search_scope(group_id),
            project_group_id=group_id or None,
            name=name,
            status=status,
        )
        worker.signals.result.connect(
            partial(self._on_search_result, gen, bbox_csv)
        )
        worker.signals.error.connect(partial(self._on_search_error, gen))

    def _on_search_result(self, gen: int, bbox_csv: str, datasets) -> None:
        if not self._active or gen != self._fetch_gen:
            return
        rows = list(datasets or [])
        self._last_datasets = rows
        try:
            painted = self._container.layers.show_map_search_areas(rows)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Could not paint map-search areas: %s", exc)
            self._on_search_error(gen, exc)
            return
        count = len(painted or [])
        if self._bar is not None:
            self._bar.set_busy(False)
            # List all API hits (area indicator); overlays only for valid areas.
            self._bar.set_results(rows)
            self._bar.set_result_count(len(rows))
            if self._canvas is not None:
                self._bar.position_on_canvas(self._canvas)
        try:
            self._container.status.ready(
                self.tr("Map search: {n} dataset(s), {a} area(s).").format(
                    n=len(rows), a=count
                )
            )
        except Exception:  # noqa: BLE001
            pass
        LOG.info(
            "Map search bbox=%s group=%s status=%s name=%r → %s datasets, %s areas",
            bbox_csv,
            self._project_group_id
            or ("all" if self._is_tdei_admin() else "my_groups"),
            self._status_filter or "All",
            self._name_filter or "",
            len(rows),
            count,
        )

    def _on_search_error(self, gen: int, exc) -> None:
        if not self._active or gen != self._fetch_gen:
            return
        if self._bar is not None:
            self._bar.set_busy(False)
            self._bar.set_results([])
            self._bar.set_result_count(0)
        if isinstance(exc, (AuthenticationError, SessionExpiredError)):
            message = self.tr("Session expired. Please sign in again.")
            self.stop()
        else:
            message = (
                str(exc)
                if isinstance(exc, (TdeiError, ValueError, OSError))
                else self.tr("Map search failed.")
            )
        try:
            self._container.status.ready(message)
        except Exception:  # noqa: BLE001
            pass
        self._container.notifications.error(message)
        LOG.exception("Map search failed: %s", exc)

    @staticmethod
    def _extent_wsen(canvas) -> Tuple[float, float, float, float]:
        rect = canvas.extent()
        src_crs = canvas.mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(
            src_crs, dest_crs, QgsProject.instance()
        )
        transformed = transform.transformBoundingBox(rect)
        transformed.normalize()
        return (
            transformed.xMinimum(),
            transformed.yMinimum(),
            transformed.xMaximum(),
            transformed.yMaximum(),
        )
