# -*- coding: utf-8 -*-
"""Stream OSW PMTiles while the map stays inside the dataset area.

Uses a local XYZ tile server + QgsVectorTileLayer so preview works even when
the QGIS/GDAL build has no PMTiles driver (common below GDAL 3.8).
"""

from __future__ import annotations

import gzip
import math
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from qgis.PyQt.QtCore import QCoreApplication, Qt, QObject, QTimer
from qgis.PyQt.QtGui import QColor

from ..core.exceptions import AuthenticationError, SessionExpiredError, TdeiError
from ..logging.logger import get_logger
from ..vendor.pmtiles import Compression, MmapSource, Reader

if TYPE_CHECKING:
    from ..core.services.container import ServiceContainer

LOG = get_logger(__name__)

OSW_PREVIEW_GROUP_NAME = "TDEI OSW Preview"
OSW_PREVIEW_GROUP_PROPERTY = "tdei_osw_preview_group"
OSW_PREVIEW_LAYER_PROPERTY = "tdei_osw_preview"
_DEBOUNCE_MS = 600
_SERVER_STOP_DELAY_MS = 750
_LOADING_PULSE_MS = 50
_TILE_PATH = re.compile(
    r"^/(\d+)/(\d+)/(\d+)\.(?:pbf|mvt)$", re.IGNORECASE
)


class OswPreviewController(QObject):
    """Serve PMTiles over localhost XYZ and show them as vector tiles."""

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._dataset_id = ""
        self._display_name = ""
        self._boundary = None  # QgsGeometry in EPSG:4326
        self._layer_ids: List[str] = []
        self._canvas = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._check_still_in_area)
        self._stop_server_timer = QTimer(self)
        self._stop_server_timer.setSingleShot(True)
        self._stop_server_timer.setInterval(_SERVER_STOP_DELAY_MS)
        self._stop_server_timer.timeout.connect(self._stop_tile_server)
        self._loading = False
        self._serving = False
        self._server = None
        self._server_thread = None
        self._pmtiles_handle = None
        self._reader = None
        self._reader_lock = threading.Lock()
        self._tile_compression = Compression.UNKNOWN
        self._local_path = ""
        self._loading_fill = None  # QgsRubberBand
        self._loading_stroke = None  # QgsRubberBand
        self._loading_phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(_LOADING_PULSE_MS)
        self._pulse_timer.timeout.connect(self._tick_loading_pulse)

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("TDEI", message)

    @property
    def active(self) -> bool:
        return bool(self._dataset_id)

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    def is_viewing(self, dataset_id: str) -> bool:
        return bool(dataset_id) and self._dataset_id == str(dataset_id).strip()

    def start(
        self,
        dataset_id: str,
        display_name: str = "",
        *,
        boundary_layer=None,
    ) -> None:
        """Fetch PMTiles, serve locally, and add a vector-tile overlay."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id or self._loading:
            return
        if self.is_viewing(dataset_id):
            return
        if not self._container.auth.is_authenticated():
            self._container.notifications.warning(
                self.tr("Sign in first, then view OSW on the map.")
            )
            open_fn = getattr(self._container, "open_main_window", None)
            if callable(open_fn):
                open_fn()
            return

        self.stop(silent=True)
        self._loading = True
        self._dataset_id = dataset_id
        self._display_name = (display_name or "").strip() or dataset_id
        self._boundary = self._boundary_wgs84(boundary_layer)
        self._start_loading_animation(boundary_layer)
        try:
            self._container.status.busy(
                self.tr("Loading OSW tiles for {name}…").format(
                    name=self._display_name
                )
            )
        except Exception:  # noqa: BLE001
            self._container.status.show(
                self.tr("Opening OSW view for {name}…").format(
                    name=self._display_name
                ),
                0,
            )
        worker = self._container.workers.submit(
            self._prepare_local_pmtiles, dataset_id
        )
        worker.signals.result.connect(self._on_prepared)
        worker.signals.error.connect(self._on_url_error)

    def _prepare_local_pmtiles(self, dataset_id: str) -> str:
        """Background: resolve SAS URL and cache the PMTiles archive locally."""
        url = self._normalize_pmtiles_url(
            self._container.datasets.fetch_osw_pmtiles_url(dataset_id)
        )
        return self._ensure_local_pmtiles(url, dataset_id)

    def stop(self, *, silent: bool = False) -> None:
        """Remove preview layers first, then stop the tile server (delayed)."""
        self._loading = False
        self._serving = False
        self._stop_loading_animation()
        was_active = bool(self._dataset_id or self._layer_ids or self._server)
        self._disconnect_canvas()
        # Drop the layer before killing the socket so QGIS stops requesting.
        self._remove_layers()
        try:
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.processEvents()
        except Exception:  # noqa: BLE001
            pass
        # Delay shutdown so in-flight tile GETs can finish with empty 200s.
        if self._server is not None:
            self._stop_server_timer.start()
        else:
            self._stop_tile_server()
        self._dataset_id = ""
        self._display_name = ""
        self._boundary = None
        self._local_path = ""
        if was_active and not silent:
            try:
                self._container.status.ready(self.tr("OSW view closed."))
            except Exception:  # noqa: BLE001
                pass

    def _start_loading_animation(self, boundary_layer) -> None:
        """Pulse a rubber-band overlay on the dataset area while PMTiles load."""
        self._stop_loading_animation()
        canvas = None
        try:
            canvas = self._container.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is None:
            return

        from qgis.core import QgsGeometry, QgsWkbTypes
        from qgis.gui import QgsRubberBand

        geometries = []
        if boundary_layer is not None:
            try:
                for feature in boundary_layer.getFeatures():
                    geom = feature.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    geometries.append(QgsGeometry(geom))
            except Exception:  # noqa: BLE001
                LOG.exception("Could not read boundary for loading overlay")
        if not geometries and self._boundary is not None:
            geometries.append(QgsGeometry(self._boundary))
        if not geometries:
            return

        fill = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        stroke = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        fill.setFillColor(QColor(50, 0, 110, 50))
        fill.setStrokeColor(QColor(50, 0, 110, 0))
        fill.setWidth(0)
        stroke.setFillColor(QColor(0, 0, 0, 0))
        stroke.setStrokeColor(QColor(98, 0, 234, 220))
        stroke.setWidth(3)
        try:
            stroke.setLineStyle(Qt.DashLine)
        except Exception:  # noqa: BLE001
            pass

        for geom in geometries:
            try:
                if boundary_layer is not None:
                    fill.addGeometry(geom, boundary_layer)
                    stroke.addGeometry(geom, boundary_layer)
                else:
                    fill.addGeometry(geom, None)
                    stroke.addGeometry(geom, None)
            except Exception:  # noqa: BLE001
                try:
                    fill.setToGeometry(geom, boundary_layer)
                    stroke.setToGeometry(geom, boundary_layer)
                except Exception:  # noqa: BLE001
                    pass

        fill.show()
        stroke.show()
        self._loading_fill = fill
        self._loading_stroke = stroke
        self._loading_phase = 0.0
        self._pulse_timer.start()
        try:
            canvas.refresh()
        except Exception:  # noqa: BLE001
            pass

    def _stop_loading_animation(self) -> None:
        self._pulse_timer.stop()
        from qgis.core import QgsWkbTypes

        for attr in ("_loading_fill", "_loading_stroke"):
            rubber = getattr(self, attr, None)
            setattr(self, attr, None)
            if rubber is None:
                continue
            try:
                rubber.reset(QgsWkbTypes.PolygonGeometry)
            except Exception:  # noqa: BLE001
                try:
                    rubber.reset()
                except Exception:  # noqa: BLE001
                    pass
            try:
                rubber.hide()
            except Exception:  # noqa: BLE001
                pass

    def _tick_loading_pulse(self) -> None:
        if not self._loading:
            self._stop_loading_animation()
            return
        self._loading_phase += 0.18
        wave = 0.5 + 0.5 * math.sin(self._loading_phase)
        fill_alpha = int(30 + 55 * wave)
        stroke_alpha = int(140 + 100 * wave)
        width = 2 + int(3 * wave)
        fill = self._loading_fill
        stroke = self._loading_stroke
        try:
            if fill is not None:
                fill.setFillColor(QColor(98, 0, 234, fill_alpha))
            if stroke is not None:
                stroke.setStrokeColor(QColor(50, 0, 110, stroke_alpha))
                stroke.setWidth(width)
        except Exception:  # noqa: BLE001
            pass
        # Full canvas refresh every ~200ms keeps the pulse visible without jank.
        if int(self._loading_phase * 5) != int((self._loading_phase - 0.18) * 5):
            try:
                canvas = self._container.iface.mapCanvas()
                if canvas is not None:
                    canvas.refresh()
            except Exception:  # noqa: BLE001
                pass

    def _on_prepared(self, local_path) -> None:
        if not self._loading or not self._dataset_id:
            return
        local_path = str(local_path or "").strip()
        # Keep the pulse until tiles are on the map, then clear it.
        try:
            self._container.status.show(
                self.tr("Adding OSW tiles for {name}…").format(
                    name=self._display_name
                ),
                0,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            added = self._start_preview_from_file(local_path)
        except Exception as exc:  # noqa: BLE001
            self._on_url_error(exc)
            return
        self._loading = False
        self._stop_loading_animation()
        if not added:
            self.stop(silent=True)
            message = self.tr("Could not open OSW tiles for this dataset.")
            self._container.status.ready(message)
            self._container.notifications.error(message)
            return
        self._zoom_to_preview_area()
        self._connect_canvas()
        msg = self.tr(
            "Viewing OSW for {name}. Pan outside the area to exit."
        ).format(name=self._display_name)
        self._container.status.ready(msg)
        self._container.notifications.success(msg)

    def _on_url_error(self, exc) -> None:
        self._loading = False
        dataset_id = self._dataset_id
        self.stop(silent=True)
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
            if isinstance(exc, (TdeiError, ValueError, OSError))
            else self.tr("Could not open OSW view for {id}.").format(
                id=dataset_id or "dataset"
            )
        )
        LOG.exception("OSW preview failed for %s: %s", dataset_id, exc)
        self._container.status.ready(message)
        self._container.notifications.error(message)

    @staticmethod
    def _normalize_pmtiles_url(url) -> str:
        text = str(url or "").strip().strip('"').strip("'")
        if text.startswith("//"):
            text = "https:" + text
        if not text.startswith("http"):
            raise ValueError("Invalid PMTiles URL.")
        return text

    def _ensure_local_pmtiles(self, url: str, dataset_id: str) -> str:
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_"
            for char in dataset_id
        ) or "dataset"
        root = self._container.layers.ensure_cache_root()
        folder = os.path.join(root, "_osw_preview")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, "{}.pmtiles".format(safe))
        if os.path.isfile(dest) and os.path.getsize(dest) > 1024:
            try:
                with open(dest, "rb") as handle:
                    magic = handle.read(7)
                if magic == b"PMTiles":
                    return dest
            except OSError:
                pass

        request = Request(url, method="GET")
        request.add_header("Accept", "application/octet-stream,*/*")
        with urlopen(request, timeout=180) as response:
            data = response.read()
        if not data or len(data) < 127 or not data.startswith(b"PMTiles"):
            raise ValueError(
                "Downloaded file is not a PMTiles archive. "
                "Viewer tiles may not be generated for this dataset yet."
            )
        tmp = dest + ".part"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, dest)
        LOG.info(
            "Cached OSW PMTiles for %s (%s bytes)", dataset_id, len(data)
        )
        return dest

    def _start_preview_from_file(self, local_path: str) -> int:
        if not local_path or not os.path.isfile(local_path):
            raise ValueError("PMTiles cache file is missing.")
        self._local_path = local_path
        self._stop_server_timer.stop()
        port, zmin, zmax = self._start_tile_server(local_path)
        return self._add_vector_tile_layer(port, zmin, zmax)

    def _read_tile(self, zoom: int, tile_x: int, tile_y: int) -> bytes:
        """Return raw (possibly gzipped) tile bytes, or empty if missing/stopped."""
        if not self._serving:
            return b""
        reader = self._reader
        if reader is None:
            return b""
        with self._reader_lock:
            if not self._serving or self._reader is None:
                return b""
            raw = self._reader.get(zoom, tile_x, tile_y)
        return raw or b""

    def _decode_tile(self, raw: bytes) -> bytes:
        if not raw:
            return b""
        # Prefer header compression; also sniff gzip magic.
        is_gzip = raw[:2] == b"\x1f\x8b"
        if self._tile_compression == Compression.GZIP or is_gzip:
            try:
                return gzip.decompress(raw)
            except Exception:  # noqa: BLE001
                return raw
        return raw

    def _start_tile_server(self, local_path: str):
        """Bind a localhost XYZ server over the PMTiles file; return port,zmin,zmax."""
        handle = open(local_path, "rb")
        reader = Reader(MmapSource(handle))
        header = reader.header()
        zmin = int(header.get("min_zoom") or 0)
        zmax = int(header.get("max_zoom") or 22)
        self._tile_compression = header.get("tile_compression") or Compression.UNKNOWN
        self._reader = reader
        self._pmtiles_handle = handle
        self._serving = True

        controller = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                path = self.path.split("?", 1)[0]
                match = _TILE_PATH.match(path)
                if match is None:
                    self._write_bytes(404, b"Not Found", "text/plain")
                    return
                if not controller._serving:
                    # Empty 200 — QGIS times out on connection resets / late 204.
                    self._write_bytes(
                        200, b"", "application/vnd.mapbox-vector-tile"
                    )
                    return
                zoom, tile_x, tile_y = (
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )
                try:
                    raw = controller._read_tile(zoom, tile_x, tile_y)
                    payload = controller._decode_tile(raw)
                except Exception:  # noqa: BLE001
                    LOG.exception(
                        "Tile read failed z=%s x=%s y=%s", zoom, tile_x, tile_y
                    )
                    self._write_bytes(
                        200, b"", "application/vnd.mapbox-vector-tile"
                    )
                    return
                self._write_bytes(
                    200, payload, "application/vnd.mapbox-vector-tile"
                )

            def _write_bytes(self, status: int, body: bytes, content_type: str):
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    if body:
                        self.wfile.write(body)
                except Exception:  # noqa: BLE001
                    pass

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        # Avoid hang if a worker is stuck — keep request handling snappy.
        try:
            server.timeout = 2
        except Exception:  # noqa: BLE001
            pass
        port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            name="tdei-osw-pmtiles-{}".format(controller._dataset_id[:8]),
            daemon=True,
        )
        self._server = server
        self._server_thread = thread
        thread.start()
        LOG.info(
            "OSW preview tile server on 127.0.0.1:%s (z %s–%s) for %s",
            port,
            zmin,
            zmax,
            self._dataset_id,
        )
        return port, zmin, zmax

    def _stop_tile_server(self) -> None:
        self._serving = False
        self._stop_server_timer.stop()
        server = self._server
        self._server = None
        self._server_thread = None
        self._reader = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
        handle = self._pmtiles_handle
        self._pmtiles_handle = None
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass

    def _add_vector_tile_layer(self, port: int, zmin: int, zmax: int) -> int:
        from qgis.core import QgsProject, QgsVectorTileLayer

        # Encode URL so QGIS does not mangle query parsing; keep {z}/{x}/{y}.
        tile_url = "http://127.0.0.1:{port}/{{z}}/{{x}}/{{y}}.pbf".format(
            port=port
        )
        encoded = quote(tile_url, safe=":/?=&%")
        # Put braces back (quote may leave them; ensure literal placeholders).
        encoded = (
            encoded.replace("%7B", "{")
            .replace("%7D", "}")
            .replace("%7b", "{")
            .replace("%7d", "}")
        )
        zmin = max(0, int(zmin))
        zmax = max(zmin, int(zmax))
        uri = "type=xyz&url={url}&zmin={zmin}&zmax={zmax}".format(
            url=encoded,
            zmin=zmin,
            zmax=zmax,
        )
        title = (self._display_name or "OSW")[:80]
        layer = QgsVectorTileLayer(uri, title)
        if not layer.isValid():
            uri = "type=xyz&url={}".format(tile_url)
            layer = QgsVectorTileLayer(uri, title)
        if not layer.isValid():
            err = ""
            try:
                err = str(layer.error().message() or "").strip()
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(
                err or "QgsVectorTileLayer rejected the local tile URL."
            )

        self._style_vector_tile_layer(layer)
        layer.setCustomProperty(OSW_PREVIEW_LAYER_PROPERTY, "1")
        layer.setCustomProperty("tdei_dataset_id", self._dataset_id)
        layer.setCustomProperty("tdei_display_name", self._display_name)
        try:
            layer.setOpacity(0.95)
        except Exception:  # noqa: BLE001
            pass

        group = self._ensure_preview_group()
        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        try:
            group.insertLayer(0, layer)
        except Exception:  # noqa: BLE001
            group.addLayer(layer)
        self._layer_ids.append(layer.id())
        try:
            group.setItemVisibilityChecked(True)
            group.setExpanded(True)
            for child in group.findLayers():
                if child is not None:
                    child.setItemVisibilityChecked(True)
        except Exception:  # noqa: BLE001
            pass
        # Draw above map-search fills when possible.
        try:
            root = project.layerTreeRoot()
            node = root.findLayer(layer.id())
            if node is not None and group is not None:
                clone = node.clone()
                parent = node.parent()
                if parent is not None:
                    parent.insertChildNode(0, clone)
                    parent.removeChildNode(node)
        except Exception:  # noqa: BLE001
            pass
        if self._container.iface is not None:
            try:
                self._container.iface.mapCanvas().refreshAllLayers()
            except Exception:  # noqa: BLE001
                pass
        return 1

    @staticmethod
    def _style_vector_tile_layer(layer) -> None:
        """Bright default symbology so OSW features are visible on the basemap."""
        try:
            from qgis.core import (
                QgsVectorTileBasicRenderer,
                QgsVectorTileBasicRendererStyle,
                QgsWkbTypes,
            )

            styles = []
            line = QgsVectorTileBasicRendererStyle()
            line.setStyleName("tdei-osw-line")
            line.setLayerName("")
            line.setGeometryType(QgsWkbTypes.LineGeometry)
            line.setFilterExpression("")
            try:
                from qgis.core import QgsLineSymbol

                symbol = QgsLineSymbol.createSimple(
                    {
                        "color": "50,0,110,220",
                        "width": "1.2",
                        "capstyle": "round",
                        "joinstyle": "round",
                    }
                )
                line.setSymbol(symbol)
            except Exception:  # noqa: BLE001
                pass
            styles.append(line)

            fill = QgsVectorTileBasicRendererStyle()
            fill.setStyleName("tdei-osw-fill")
            fill.setLayerName("")
            fill.setGeometryType(QgsWkbTypes.PolygonGeometry)
            try:
                from qgis.core import QgsFillSymbol

                symbol = QgsFillSymbol.createSimple(
                    {
                        "color": "50,0,110,40",
                        "outline_color": "50,0,110,200",
                        "outline_width": "0.6",
                    }
                )
                fill.setSymbol(symbol)
            except Exception:  # noqa: BLE001
                pass
            styles.append(fill)

            point = QgsVectorTileBasicRendererStyle()
            point.setStyleName("tdei-osw-point")
            point.setLayerName("")
            point.setGeometryType(QgsWkbTypes.PointGeometry)
            try:
                from qgis.core import QgsMarkerSymbol

                symbol = QgsMarkerSymbol.createSimple(
                    {
                        "color": "98,0,234,220",
                        "size": "2.2",
                        "outline_color": "50,0,110,255",
                        "outline_width": "0.4",
                    }
                )
                point.setSymbol(symbol)
            except Exception:  # noqa: BLE001
                pass
            styles.append(point)

            renderer = QgsVectorTileBasicRenderer()
            renderer.setStyles(styles)
            layer.setRenderer(renderer)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not style OSW vector tile layer")

    def _zoom_to_preview_area(self) -> None:
        try:
            if self._container.layers.zoom_to_map_search_dataset(
                self._dataset_id
            ):
                return
        except Exception:  # noqa: BLE001
            pass
        if self._boundary is None or self._container.iface is None:
            return
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsProject,
            )

            canvas = self._container.iface.mapCanvas()
            if canvas is None:
                return
            geom = self._boundary
            rect = geom.boundingBox()
            dest = canvas.mapSettings().destinationCrs()
            src = QgsCoordinateReferenceSystem("EPSG:4326")
            if dest is not None and dest.isValid() and dest != src:
                xform = QgsCoordinateTransform(src, dest, QgsProject.instance())
                rect = xform.transformBoundingBox(rect)
            try:
                rect.scale(1.2)
            except Exception:  # noqa: BLE001
                pass
            canvas.setExtent(rect)
            canvas.refresh()
        except Exception:  # noqa: BLE001
            LOG.exception("Could not zoom to OSW preview area")

    def _ensure_preview_group(self):
        from qgis.core import QgsLayerTreeGroup, QgsProject

        root = QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if str(child.customProperty(OSW_PREVIEW_GROUP_PROPERTY) or "") == "1":
                return child
            if child.name() == OSW_PREVIEW_GROUP_NAME:
                child.setCustomProperty(OSW_PREVIEW_GROUP_PROPERTY, "1")
                return child
        try:
            group = root.insertGroup(0, OSW_PREVIEW_GROUP_NAME)
        except Exception:  # noqa: BLE001
            group = root.addGroup(OSW_PREVIEW_GROUP_NAME)
        group.setCustomProperty(OSW_PREVIEW_GROUP_PROPERTY, "1")
        return group

    def _remove_layers(self) -> None:
        from qgis.core import QgsLayerTreeGroup, QgsProject

        project = QgsProject.instance()
        ids = list(self._layer_ids)
        self._layer_ids = []
        try:
            for layer in list(project.mapLayers().values()):
                if (
                    str(layer.customProperty(OSW_PREVIEW_LAYER_PROPERTY) or "")
                    == "1"
                ):
                    ids.append(layer.id())
        except Exception:  # noqa: BLE001
            pass
        unique = list(dict.fromkeys(ids))
        if unique:
            try:
                project.removeMapLayers(unique)
            except Exception:  # noqa: BLE001
                LOG.exception("Could not remove OSW preview layers")
        root = project.layerTreeRoot()
        for child in list(root.children()):
            if not isinstance(child, QgsLayerTreeGroup):
                continue
            if (
                str(child.customProperty(OSW_PREVIEW_GROUP_PROPERTY) or "")
                == "1"
                or child.name() == OSW_PREVIEW_GROUP_NAME
            ):
                try:
                    root.removeChildNode(child)
                except Exception:  # noqa: BLE001
                    pass

    def _boundary_wgs84(self, layer) -> Optional[object]:
        if layer is None:
            return None
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsGeometry,
                QgsProject,
            )

            parts = []
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                parts.append(QgsGeometry(geom))
            if not parts:
                return None
            combined = QgsGeometry.unaryUnion(parts)
            if combined is None or combined.isEmpty():
                return None
            src = layer.crs()
            dest = QgsCoordinateReferenceSystem("EPSG:4326")
            if src is not None and src.isValid() and src != dest:
                xform = QgsCoordinateTransform(src, dest, QgsProject.instance())
                combined.transform(xform)
            return combined
        except Exception:  # noqa: BLE001
            LOG.exception("Could not build OSW preview boundary")
            return None

    def _connect_canvas(self) -> None:
        canvas = None
        try:
            canvas = self._container.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is None:
            return
        self._disconnect_canvas()
        self._canvas = canvas
        try:
            canvas.extentsChanged.connect(self._on_extents_changed)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not watch canvas extents for OSW preview")
            self._canvas = None

    def _disconnect_canvas(self) -> None:
        self._debounce.stop()
        canvas = self._canvas
        self._canvas = None
        if canvas is None:
            return
        try:
            canvas.extentsChanged.disconnect(self._on_extents_changed)
        except Exception:  # noqa: BLE001
            pass

    def _on_extents_changed(self) -> None:
        if not self._dataset_id or not self._serving:
            return
        self._debounce.start()

    def _check_still_in_area(self) -> None:
        if not self._dataset_id or self._boundary is None or not self._serving:
            return
        canvas = self._canvas
        if canvas is None:
            try:
                canvas = self._container.iface.mapCanvas()
            except Exception:  # noqa: BLE001
                return
        if canvas is None:
            return
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsGeometry,
                QgsProject,
            )

            extent = canvas.extent()
            canvas_crs = canvas.mapSettings().destinationCrs()
            rect_geom = QgsGeometry.fromRect(extent)
            dest = QgsCoordinateReferenceSystem("EPSG:4326")
            if (
                canvas_crs is not None
                and canvas_crs.isValid()
                and canvas_crs != dest
            ):
                xform = QgsCoordinateTransform(
                    canvas_crs, dest, QgsProject.instance()
                )
                rect_geom.transform(xform)
            if rect_geom.intersects(self._boundary):
                return
        except Exception:  # noqa: BLE001
            LOG.exception("OSW preview extent check failed")
            return
        LOG.info(
            "OSW preview exit — view left dataset area (%s)", self._dataset_id
        )
        name = self._display_name or self._dataset_id
        self.stop(silent=True)
        try:
            self._container.status.ready(
                self.tr("Left {name} area — OSW view closed.").format(name=name)
            )
            self._container.notifications.info(
                self.tr("Left the dataset area — OSW view closed.")
            )
        except Exception:  # noqa: BLE001
            pass
