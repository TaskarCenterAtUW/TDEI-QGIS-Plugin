# -*- coding: utf-8 -*-
"""Orchestrate zoom → draw bbox → confirm → submit dataset-bbox job."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from qgis.PyQt.QtCore import QObject
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

from ..features.jobs.bbox import format_bbox_csv
from ..logging.logger import get_logger
from ..ui.dialogs.bbox_confirm_bar import BBoxConfirmBar
from .bbox_map_tool import BBoxMapTool

if TYPE_CHECKING:
    from ..core.services.container import ServiceContainer

LOG = get_logger(__name__)


class BBoxCaptureController(QObject):
    """One active capture session at a time."""

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._tool = None  # type: Optional[BBoxMapTool]
        self._previous_tool = None
        self._bar = None  # type: Optional[BBoxConfirmBar]
        self._plugin_window = None
        self._dataset_id = ""
        self._dataset_name = ""
        self._bbox_csv = ""
        self._active = False
        self._confirming = False
        self._ignore_tool_change = False
        self._watching_tools = False
        self._on_finished = None  # type: Optional[Callable]

    @property
    def active(self) -> bool:
        return self._active

    def start(
        self,
        dataset_id: str,
        dataset_name: str = "",
        *,
        plugin_window=None,
        on_finished: Optional[Callable] = None,
    ) -> None:
        if self._active:
            self.cancel()

        iface = self._container.iface
        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is None:
            self._container.notifications.error(
                self.tr("Map canvas is not available.")
            )
            return

        if not self._container.auth.is_authenticated():
            self._container.notifications.warning(
                self.tr("Sign in first, then clip the dataset.")
            )
            open_fn = getattr(self._container, "open_main_window", None)
            if callable(open_fn):
                open_fn()
            return

        self._dataset_id = str(dataset_id or "").strip()
        self._dataset_name = dataset_name or self._dataset_id
        self._on_finished = on_finished
        self._plugin_window = plugin_window
        self._active = True
        self._confirming = False
        self._bbox_csv = ""

        try:
            self._container.datasets.ensure_basemap()
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..ui.busy import busy_action

            with busy_action(
                self._container, self.tr("Preparing map for clip…")
            ):
                self._container.layers.zoom_to_dataset(self._dataset_id)
                self._container.layers.select_dataset_group(self._dataset_id)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Zoom before bbox capture failed: %s", exc)

        self._previous_tool = canvas.mapTool()
        self._tool = BBoxMapTool(canvas)
        self._tool.bbox_drawn.connect(self._on_bbox_drawn)
        self._tool.cancelled.connect(self.cancel)
        self._tool.interaction_changed.connect(self._on_interaction_changed)
        self._tool.set_interaction(BBoxMapTool.INTERACT_DRAW)
        self._ignore_tool_change = True
        canvas.setMapTool(self._tool)
        self._ignore_tool_change = False
        self._connect_tool_watch(canvas)

        try:
            main = iface.mainWindow()
            if main is not None:
                main.raise_()
                main.activateWindow()
        except Exception:  # noqa: BLE001
            pass

        self._show_bar(drawing=True)
        self._container.status.show(
            self.tr(
                "Draw a rectangle for {name}. Switch tools on the clip "
                "toolbar (Draw / Zoom / Pan)."
            ).format(name=self._dataset_name),
            8000,
        )

    def cancel(self) -> None:
        was_active = self._active
        self._cleanup(restore_window=True)
        self._active = False
        if was_active:
            self._container.status.ready(self.tr("Dataset clip cancelled."))
        callback = self._on_finished
        self._on_finished = None
        if callable(callback):
            callback(False)

    def _connect_tool_watch(self, canvas) -> None:
        if self._watching_tools or canvas is None:
            return
        try:
            canvas.mapToolSet.connect(self._on_map_tool_set)
            self._watching_tools = True
        except Exception:  # noqa: BLE001
            LOG.exception("Could not watch map tool changes")

    def _disconnect_tool_watch(self, canvas) -> None:
        if not self._watching_tools or canvas is None:
            return
        try:
            canvas.mapToolSet.disconnect(self._on_map_tool_set)
        except Exception:  # noqa: BLE001
            pass
        self._watching_tools = False

    def _on_map_tool_set(self, new_tool, old_tool=None) -> None:
        if not self._active or self._ignore_tool_change:
            return
        if self._tool is None or new_tool is self._tool:
            return
        self._container.notifications.info(
            self.tr(
                "Clip cancelled because another map tool was selected. "
                "Use the clip toolbar, then try again."
            )
        )
        self.cancel()

    def _on_bbox_drawn(self, rect: QgsRectangle) -> None:
        try:
            wsen = self._rect_to_wsen(rect)
            self._bbox_csv = format_bbox_csv(wsen)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Could not convert bbox: %s", exc)
            self._container.notifications.error(
                self.tr("Could not read that rectangle. Try again.")
            )
            if self._tool is not None:
                self._tool.reset()
            return

        self._confirming = True
        if self._tool is not None:
            self._tool.keep_rectangle(rect)
            self._tool.set_interaction(BBoxMapTool.INTERACT_PAN)

        self._highlight_dataset_group()
        self._show_bar(drawing=False)
        self._container.status.show(
            self.tr(
                "Confirm the clip. Use Zoom or Pan, then Run clip — "
                "or Draw clip to redraw."
            ),
            8000,
        )

    def _ensure_bar(self) -> BBoxConfirmBar:
        if self._bar is None:
            parent = None
            try:
                parent = self._container.iface.mainWindow()
            except Exception:  # noqa: BLE001
                parent = None
            self._bar = BBoxConfirmBar(parent=parent)
            self._bar.cancelled.connect(self.cancel)
            self._bar.confirmed.connect(self._on_confirmed)
            self._bar.redraw_requested.connect(self._on_redraw)
            self._bar.tool_changed.connect(self._on_bar_tool_changed)
        return self._bar

    def _show_bar(self, *, drawing: bool) -> None:
        bar = self._ensure_bar()
        if drawing:
            bar.set_context(self._dataset_name, "")
        else:
            bar.set_context(self._dataset_name, self._bbox_csv)
        mode = (
            self._tool.interaction()
            if self._tool is not None
            else BBoxMapTool.INTERACT_DRAW
        )
        bar.set_tool(mode)
        canvas = self._canvas()
        bar.show()
        bar.position_on_canvas(canvas)
        bar.raise_()

    def _on_bar_tool_changed(self, mode: str) -> None:
        if self._tool is None:
            return
        self._highlight_dataset_group()
        # Selecting Draw while confirming means start over.
        if mode == BBoxMapTool.INTERACT_DRAW and self._confirming:
            self._on_redraw()
            return
        self._apply_interaction(mode)

    def _on_interaction_changed(self, mode: str) -> None:
        if self._bar is not None:
            self._bar.set_tool(mode)
        self._highlight_dataset_group()

    def _apply_interaction(self, mode: str) -> None:
        if self._tool is None:
            return
        self._highlight_dataset_group()
        canvas = self._canvas()
        if canvas is not None and canvas.mapTool() is not self._tool:
            self._ignore_tool_change = True
            try:
                canvas.setMapTool(self._tool)
            finally:
                self._ignore_tool_change = False
        self._tool.set_interaction(mode)
        # Ensure pointer updates immediately (not only after next mouse move).
        try:
            self._tool._update_cursor()
        except Exception:  # noqa: BLE001
            pass

    def _highlight_dataset_group(self) -> None:
        if not self._dataset_id:
            return
        try:
            self._container.layers.select_dataset_group(self._dataset_id)
        except Exception:  # noqa: BLE001
            LOG.exception(
                "Could not highlight dataset group %s", self._dataset_id
            )

    def _canvas(self):
        try:
            return self._container.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            return None

    def _on_redraw(self) -> None:
        canvas = self._canvas()
        if canvas is None or self._tool is None:
            self.cancel()
            return
        self._confirming = False
        self._bbox_csv = ""
        self._tool.reset()
        self._tool.set_phase(BBoxMapTool.PHASE_DRAW)
        self._tool.set_interaction(BBoxMapTool.INTERACT_DRAW)
        self._ignore_tool_change = True
        try:
            if canvas.mapTool() is not self._tool:
                canvas.setMapTool(self._tool)
        finally:
            self._ignore_tool_change = False
        self._show_bar(drawing=True)
        self._container.status.show(
            self.tr("Draw a new rectangle. Cancel or Esc to exit."),
            6000,
        )

    def _on_confirmed(self, file_type: str) -> None:
        dataset_id = self._dataset_id
        bbox_csv = self._bbox_csv
        name = self._dataset_name
        self._cleanup(restore_window=True)
        self._active = False
        callback = self._on_finished
        self._on_finished = None

        self._submit(dataset_id, name, bbox_csv, file_type or "osw")
        if callable(callback):
            callback(True)

    def _submit(
        self, dataset_id: str, name: str, bbox_csv: str, file_type: str
    ) -> None:
        self._container.status.busy(self.tr("Submitting clip job…"))

        def work():
            return self._container.jobs.submit_dataset_bbox(
                dataset_id=dataset_id,
                bbox=bbox_csv,
                file_type=file_type,
            )

        worker = self._container.workers.submit(work)

        def on_result(result):
            job_id = getattr(result, "job_id", "") or ""
            self._container.status.ready(self.tr("Clip job submitted."))
            open_jobs = getattr(self._container, "open_jobs", None)
            if callable(open_jobs) and job_id:
                open_jobs(job_id)
                self._container.notifications.success(
                    self.tr("Clip job {} submitted for {}.").format(
                        job_id, name
                    )
                )
            elif job_id:
                self._container.notifications.success(
                    self.tr("Clip job submitted. Job ID: {}").format(job_id)
                )
            else:
                self._container.notifications.success(
                    self.tr("Clip job submitted.")
                )

        def on_error(exc):
            LOG.exception("dataset-bbox submit failed: %s", exc)
            self._container.status.ready(self.tr("Clip job failed."))
            self._container.notifications.error(
                self.tr("Could not submit clip job: {}").format(exc)
            )

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

    def _cleanup(self, *, restore_window: bool) -> None:
        canvas = self._canvas()
        self._disconnect_tool_watch(canvas)
        self._confirming = False
        self._ignore_tool_change = True

        if self._bar is not None:
            self._bar.hide()
            self._bar.deleteLater()
            self._bar = None

        if self._tool is not None:
            try:
                self._tool.clear()
                if canvas is not None and canvas.mapTool() is self._tool:
                    canvas.unsetMapTool(self._tool)
            except Exception:  # noqa: BLE001
                pass
            self._tool = None

        if canvas is not None and self._previous_tool is not None:
            try:
                canvas.setMapTool(self._previous_tool)
            except Exception:  # noqa: BLE001
                pass
        self._previous_tool = None
        self._ignore_tool_change = False

        if restore_window and self._plugin_window is not None:
            try:
                win = self._plugin_window
                if win.isMinimized():
                    win.showNormal()
                win.raise_()
                win.activateWindow()
            except Exception:  # noqa: BLE001
                pass
        self._plugin_window = None
        self._bbox_csv = ""

    def _rect_to_wsen(self, rect: QgsRectangle):
        canvas = self._container.iface.mapCanvas()
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

    def tr(self, message: str) -> str:
        from qgis.PyQt.QtCore import QCoreApplication

        return QCoreApplication.translate("TDEI", message)
