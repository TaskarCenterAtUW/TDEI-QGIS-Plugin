# -*- coding: utf-8 -*-
"""Routability tool: start edge + destination → route layer over the map."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Hashable, List, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

from ..features.osw.naming import osw_type_from_filename
from ..features.osw.routing import (
    EDGE_ID_FIELD,
    LENGTH_FIELD,
    U_ID_FIELD,
    V_ID_FIELD,
    RoutingGraph,
    has_routing_fields,
    normalize_node_id,
)
from ..logging.logger import get_logger
from ..ui.dialogs.route_bar import RouteBar
from .route_map_tool import RouteMapTool

if TYPE_CHECKING:
    from ..core.services.container import ServiceContainer

LOG = get_logger(__name__)

OUTPUT_PROPERTY = "tdei_routability"  # "route" | "reachable"
SOURCE_PROPERTY = "tdei_routability_source"  # edges layer id
_PICK_TOLERANCE_PX = 10


def is_edges_layer(layer) -> bool:
    """Line layer whose features carry ``_u_id`` / ``_v_id`` node references."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    try:
        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            return False
        if layer.customProperty(OUTPUT_PROPERTY):
            return False
        return has_routing_fields(layer.fields().names())
    except Exception:  # noqa: BLE001
        return False


def find_edges_layer(layers) -> Optional[QgsVectorLayer]:
    """Prefer an ``*.edges.geojson`` layer; else any line layer with node ids."""
    candidates = [layer for layer in layers or () if is_edges_layer(layer)]
    for layer in candidates:
        source = (layer.source() or "").split("|")[0]
        if osw_type_from_filename(source) == "edges":
            return layer
    return candidates[0] if candidates else None


def _format_distance(meters: float) -> str:
    if meters < 1000:
        return "{:.0f} m".format(meters)
    return "{:.2f} km".format(meters / 1000.0)


class RoutabilityController(QObject):
    """One routability session at a time on one edges layer."""

    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._active = False
        self._layer = None  # type: Optional[QgsVectorLayer]
        self._title = ""
        self._graph = None  # type: Optional[RoutingGraph]
        self._index = None  # type: Optional[QgsSpatialIndex]
        self._edge_ids = {}  # type: Dict[Hashable, str]
        self._tool = None  # type: Optional[RouteMapTool]
        self._previous_tool = None
        self._bar = None  # type: Optional[RouteBar]
        self._start_fid = None
        self._start_along = 0.0  # clicked position along the start edge
        self._dest = None  # type: Optional[Tuple[int, float, QgsPointXY]]
        self._start_band = None
        self._dest_band = None
        self._hidden_panels = None
        self._ignore_tool_change = False

    @property
    def active(self) -> bool:
        return self._active

    def tr(self, message: str) -> str:
        from qgis.PyQt.QtCore import QCoreApplication

        return QCoreApplication.translate("TDEI", message)

    # ── session ────────────────────────────────────────────────────────

    def start(self, layer, title: str = "") -> None:
        if self._active:
            self.finish(silent=True)
        if not is_edges_layer(layer):
            self._container.notifications.warning(
                self.tr(
                    "Routability needs an edges line layer with {u} and {v} fields."
                ).format(u=U_ID_FIELD, v=V_ID_FIELD)
            )
            return
        canvas = self._canvas()
        if canvas is None:
            self._container.notifications.error(
                self.tr("Map canvas is not available.")
            )
            return

        clip = getattr(self._container, "bbox_capture", None)
        if clip is not None and getattr(clip, "active", False):
            try:
                clip.cancel()
            except Exception:  # noqa: BLE001
                pass

        if not self._build_graph(layer):
            return

        self._layer = layer
        self._title = title or layer.name()
        self._active = True
        self._start_fid = None
        self._dest = None
        self._hide_map_panels()

        self._previous_tool = canvas.mapTool()
        self._tool = RouteMapTool(canvas)
        self._tool.point_picked.connect(self._on_point_picked)
        self._tool.cancelled.connect(self.finish)
        self._tool.interaction_changed.connect(self._on_interaction_changed)
        self._set_map_tool(canvas)
        try:
            canvas.mapToolSet.connect(self._on_map_tool_set)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not watch map tool changes")
        QgsProject.instance().layerWillBeRemoved.connect(self._on_layer_removed)

        self._bar = RouteBar(parent=self._container.iface.mainWindow())
        self._bar.tool_changed.connect(self._on_bar_tool_changed)
        self._bar.clear_requested.connect(self._clear)
        self._bar.done.connect(self.finish)
        self._bar.set_title(self._title)
        self._bar.set_tool(RouteMapTool.INTERACT_START)
        self._bar.position_on_canvas(canvas)

        self._container.status.show(
            self.tr(
                "Routability: {n} edges, {m} nodes. Click a start edge."
            ).format(n=self._graph.edge_count, m=self._graph.node_count),
            8000,
        )

    def finish(self, silent: bool = False) -> None:
        if not self._active:
            return
        self._active = False
        canvas = self._canvas()
        if canvas is not None:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_set)
            except Exception:  # noqa: BLE001
                pass
        try:
            QgsProject.instance().layerWillBeRemoved.disconnect(
                self._on_layer_removed
            )
        except Exception:  # noqa: BLE001
            pass
        if self._bar is not None:
            self._bar.hide()
            self._bar.deleteLater()
            self._bar = None
        self._clear_bands()
        if self._tool is not None:
            self._ignore_tool_change = True
            try:
                if canvas is not None and canvas.mapTool() is self._tool:
                    canvas.unsetMapTool(self._tool)
                    if self._previous_tool is not None:
                        canvas.setMapTool(self._previous_tool)
            except Exception:  # noqa: BLE001
                pass
            self._ignore_tool_change = False
            self._tool = None
        self._previous_tool = None
        self._graph = None
        self._index = None
        self._edge_ids = {}
        self._layer = None
        self._restore_map_panels()
        if not silent:
            self._container.status.ready(self.tr("Routability tool closed."))

    # ── graph ──────────────────────────────────────────────────────────

    def _build_graph(self, layer) -> bool:
        from ..ui.busy import busy_action

        fields = layer.fields()
        u_idx = fields.indexOf(U_ID_FIELD)
        v_idx = fields.indexOf(V_ID_FIELD)
        id_idx = fields.indexOf(EDGE_ID_FIELD)
        len_idx = fields.indexOf(LENGTH_FIELD)
        attrs = [idx for idx in (u_idx, v_idx, id_idx, len_idx) if idx >= 0]
        measure = self._distance_area(layer)
        graph = RoutingGraph()
        index = QgsSpatialIndex(QgsSpatialIndex.FlagStoreFeatureGeometries)
        edge_ids = {}
        try:
            with busy_action(self._container, self.tr("Building routing graph…")):
                request = QgsFeatureRequest().setSubsetOfAttributes(attrs)
                for feature in layer.getFeatures(request):
                    geom = feature.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    length = self._attr_length(feature, len_idx)
                    if length is None:
                        length = measure.measureLength(geom)
                    if not graph.add_edge(
                        feature.id(),
                        feature.attribute(u_idx),
                        feature.attribute(v_idx),
                        length,
                    ):
                        continue
                    index.addFeature(feature)
                    if id_idx >= 0:
                        edge_ids[feature.id()] = normalize_node_id(
                            feature.attribute(id_idx)
                        )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Could not build routing graph: %s", exc)
            self._container.notifications.error(
                self.tr("Could not read the edges layer: {}").format(exc)
            )
            return False
        if graph.edge_count == 0:
            self._container.notifications.warning(
                self.tr(
                    "No edges with {u} and {v} values were found in this layer."
                ).format(u=U_ID_FIELD, v=V_ID_FIELD)
            )
            return False
        self._graph = graph
        self._index = index
        self._edge_ids = edge_ids
        return True

    @staticmethod
    def _attr_length(feature, idx: int) -> Optional[float]:
        if idx < 0:
            return None
        try:
            value = float(feature.attribute(idx))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _distance_area(layer) -> QgsDistanceArea:
        measure = QgsDistanceArea()
        measure.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        measure.setEllipsoid("WGS84")
        return measure

    # ── picking ────────────────────────────────────────────────────────

    def _on_point_picked(self, mode: str, canvas_point) -> None:
        if not self._active or self._layer is None:
            return
        point = self._to_layer_crs(canvas_point)
        if point is None:
            return
        if mode == RouteMapTool.INTERACT_START:
            self._pick_start(canvas_point, point)
        elif mode == RouteMapTool.INTERACT_DEST:
            self._pick_destination(point)

    def _pick_start(self, canvas_point, point: QgsPointXY) -> None:
        tolerance = self._pick_tolerance(canvas_point)
        ids = self._index.nearestNeighbor(point, 1, tolerance)
        if not ids:
            self._container.status.show(
                self.tr("No edge there — click directly on an edge line."), 5000
            )
            return
        self._start_fid = ids[0]
        self._start_along, start_point = self._snap_on_edge(self._start_fid, point)
        self._show_start_band(start_point)
        self._set_interaction(RouteMapTool.INTERACT_DEST)
        if self._dest is not None:
            self._compute_route()
        else:
            self._bar_result(
                self.tr("Start edge: {}").format(self._edge_label(self._start_fid))
            )

    def _pick_destination(self, point: QgsPointXY) -> None:
        if self._start_fid is None:
            self._container.status.show(
                self.tr("Pick a start edge first."), 4000
            )
            self._set_interaction(RouteMapTool.INTERACT_START)
            return
        ids = self._index.nearestNeighbor(point, 1)
        if not ids:
            return
        fid = ids[0]
        along, snapped_point = self._snap_on_edge(fid, point)
        self._dest = (fid, along, snapped_point)
        self._show_dest_band(snapped_point)
        self._compute_route()

    def _snap_on_edge(self, fid, point: QgsPointXY) -> Tuple[float, QgsPointXY]:
        """Distance along edge *fid* (layer units) and the snapped point."""
        geom = self._index.geometry(fid)
        along = max(0.0, geom.lineLocatePoint(QgsGeometry.fromPointXY(point)))
        snapped = geom.interpolate(along)
        if snapped is None or snapped.isEmpty():
            return along, point
        return along, snapped.asPoint()

    def _pick_tolerance(self, canvas_point) -> float:
        canvas = self._canvas()
        offset = _PICK_TOLERANCE_PX * canvas.mapUnitsPerPixel()
        a = self._to_layer_crs(canvas_point)
        b = self._to_layer_crs(
            QgsPointXY(canvas_point.x() + offset, canvas_point.y())
        )
        if a is None or b is None:
            return 0.0
        return max(a.distance(b), 1e-9)

    def _to_layer_crs(self, canvas_point) -> Optional[QgsPointXY]:
        canvas = self._canvas()
        if canvas is None or self._layer is None:
            return None
        try:
            transform = QgsCoordinateTransform(
                canvas.mapSettings().destinationCrs(),
                self._layer.crs(),
                QgsProject.instance(),
            )
            return QgsPointXY(transform.transform(QgsPointXY(canvas_point)))
        except Exception:  # noqa: BLE001
            LOG.exception("Could not transform picked point")
            return None

    # ── routing ────────────────────────────────────────────────────────

    def _compute_route(self) -> None:
        graph = self._graph
        if graph is None or self._start_fid is None or self._dest is None:
            return
        start_u, start_v, _start_len = graph.edges[self._start_fid]
        start_along = self._start_along
        start_geom_len = self._index.geometry(self._start_fid).length() or 0.0
        dest_fid, along, _snapped = self._dest
        dest_u, dest_v, dest_len = graph.edges[dest_fid]
        dest_geom = self._index.geometry(dest_fid)
        geom_len = dest_geom.length() or 0.0
        fraction = min(1.0, along / geom_len) if geom_len > 0 else 0.0

        if dest_fid == self._start_fid:
            total, _count = self._render_route(
                [("start", self._start_fid, (start_along, along))]
            )
            self._bar_result(
                self.tr("The destination is on the start edge ({}).").format(
                    _format_distance(total)
                )
            )
            return

        # Path choice treats the whole start edge as the start (both ends free);
        # only the drawn start piece runs from the clicked point.
        result = graph.shortest_path(
            {start_u: 0.0, start_v: 0.0},
            {dest_u: fraction * dest_len, dest_v: (1.0 - fraction) * dest_len},
        )
        if result is None:
            reachable = graph.reachable_edges([start_u, start_v])
            self._render_reachable(reachable)
            message = self.tr(
                "No route: the destination isn't connected to the start edge. "
                "Showing the {n} edge(s) reachable from the start edge."
            ).format(n=len(reachable))
            self._bar_result(message)
            self._container.notifications.warning(message)
            return

        departure = result.nodes[0] if result.nodes else start_u
        if departure == start_u:
            start_segment = (0.0, start_along)
        else:
            start_segment = (start_along, start_geom_len)
        parts = [("start", self._start_fid, start_segment)]
        parts.extend(("path", key, None) for key in result.edge_keys)
        if dest_fid not in result.edge_keys:
            if result.target_node == dest_u:
                segment = (0.0, along)
            else:
                segment = (along, geom_len)
            parts.append(("destination", dest_fid, segment))
        total, count = self._render_route(parts)
        self._bar_result(
            self.tr("Route: {n} edge(s), {d}.").format(
                n=count, d=_format_distance(total)
            )
        )
        self._container.status.show(
            self.tr("Route found — {}.").format(_format_distance(total)), 6000
        )

    # ── output layers ──────────────────────────────────────────────────

    def _render_route(self, parts) -> Tuple[float, int]:
        """Write route rows; return (drawn length in metres, row count)."""
        self._remove_output("reachable")
        layer = self._output_layer("route")
        provider = layer.dataProvider()
        provider.truncate()
        features = []
        total = 0.0
        for role, fid, segment in parts:
            geom = self._index.geometry(fid)
            u_id, v_id, length = self._graph.edges[fid]
            if segment is not None:
                # Clicked exactly on a node: nothing of this edge is walked.
                if abs(segment[1] - segment[0]) <= 1e-12:
                    continue
                full = geom.length() or 0.0
                if full > 0:
                    length = length * abs(segment[1] - segment[0]) / full
                geom = self._substring(geom, *segment)
            feature = QgsFeature(layer.fields())
            feature.setGeometry(self._as_multi(geom))
            feature.setAttributes(
                [
                    len(features) + 1,
                    role,
                    self._edge_ids.get(fid, ""),
                    u_id,
                    v_id,
                    round(length, 2),
                ]
            )
            features.append(feature)
            total += length
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()
        LOG.info(
            "Routability route: %s parts, %.1f m on %s",
            len(features),
            total,
            self._title,
        )
        return total, len(features)

    def _render_reachable(self, keys) -> None:
        self._remove_output("route")
        layer = self._output_layer("reachable")
        provider = layer.dataProvider()
        provider.truncate()
        features = []
        for fid in keys:
            u_id, v_id, length = self._graph.edges[fid]
            feature = QgsFeature(layer.fields())
            feature.setGeometry(self._as_multi(self._index.geometry(fid)))
            feature.setAttributes(
                [0, "reachable", self._edge_ids.get(fid, ""), u_id, v_id, round(length, 2)]
            )
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()

    @staticmethod
    def _as_multi(geom: QgsGeometry) -> QgsGeometry:
        multi = QgsGeometry(geom)
        if not multi.isMultipart():
            multi.convertToMultiType()
        return multi

    @staticmethod
    def _substring(geom: QgsGeometry, start: float, end: float) -> QgsGeometry:
        try:
            curve = geom.constGet()
            if geom.isMultipart():
                curve = curve.geometryN(0)
            part = curve.curveSubstring(min(start, end), max(start, end))
            if part is not None and not part.isEmpty():
                return QgsGeometry(part)
        except Exception:  # noqa: BLE001
            LOG.debug("curveSubstring failed; using whole edge", exc_info=True)
        return QgsGeometry(geom)

    def _output_layer(self, kind: str) -> QgsVectorLayer:
        existing = self._find_output(kind)
        if existing is not None:
            return existing
        name = (
            self.tr("Route — {}") if kind == "route" else self.tr("Reachable — {}")
        ).format(self._title)
        layer = QgsVectorLayer("MultiLineString", name, "memory")
        layer.setCrs(self._layer.crs())
        layer.dataProvider().addAttributes(
            [
                QgsField("seq", QVariant.Int),
                QgsField("role", QVariant.String),
                QgsField("edge_id", QVariant.String),
                QgsField(U_ID_FIELD, QVariant.String),
                QgsField(V_ID_FIELD, QVariant.String),
                QgsField("length_m", QVariant.Double),
            ]
        )
        layer.updateFields()
        layer.setCustomProperty(OUTPUT_PROPERTY, kind)
        layer.setCustomProperty(SOURCE_PROPERTY, self._layer.id())
        self._style_output(layer, kind)
        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        project.layerTreeRoot().insertLayer(0, layer)
        return layer

    @staticmethod
    def _style_output(layer: QgsVectorLayer, kind: str) -> None:
        if kind == "route":
            symbol = QgsLineSymbol.createSimple(
                {
                    "line_color": "255,255,255,235",
                    "line_width": "2.8",
                    "line_width_unit": "MM",
                    "capstyle": "round",
                    "joinstyle": "round",
                }
            )
            core = QgsLineSymbol.createSimple(
                {
                    "line_color": "255,109,0,255",
                    "line_width": "1.6",
                    "line_width_unit": "MM",
                    "capstyle": "round",
                    "joinstyle": "round",
                }
            )
            symbol.appendSymbolLayer(core.symbolLayer(0).clone())
        else:
            symbol = QgsLineSymbol.createSimple(
                {
                    "line_color": "98,0,234,170",
                    "line_width": "1.2",
                    "line_width_unit": "MM",
                    "capstyle": "round",
                    "joinstyle": "round",
                }
            )
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _find_output(self, kind: str) -> Optional[QgsVectorLayer]:
        if self._layer is None:
            return None
        source_id = self._layer.id()
        for layer in QgsProject.instance().mapLayers().values():
            try:
                if (
                    str(layer.customProperty(OUTPUT_PROPERTY) or "") == kind
                    and str(layer.customProperty(SOURCE_PROPERTY) or "") == source_id
                ):
                    return layer
            except Exception:  # noqa: BLE001
                continue
        return None

    def _remove_output(self, kind: str) -> None:
        layer = self._find_output(kind)
        if layer is not None:
            QgsProject.instance().removeMapLayer(layer.id())

    # ── map markers ────────────────────────────────────────────────────

    def _show_start_band(self, point: QgsPointXY) -> None:
        if self._start_band is None:
            self._start_band = self._marker_band(QColor(0, 160, 90, 255))
        if self._start_band is not None:
            self._start_band.setToGeometry(
                QgsGeometry.fromPointXY(point), self._layer
            )

    def _show_dest_band(self, point: QgsPointXY) -> None:
        if self._dest_band is None:
            self._dest_band = self._marker_band(QColor(214, 40, 40, 255))
        if self._dest_band is not None:
            self._dest_band.setToGeometry(
                QgsGeometry.fromPointXY(point), self._layer
            )

    def _marker_band(self, color: QColor):
        canvas = self._canvas()
        if canvas is None:
            return None
        band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        band.setColor(color)
        band.setIcon(QgsRubberBand.ICON_CIRCLE)
        band.setIconSize(14)
        band.setWidth(3)
        return band

    def _clear_bands(self) -> None:
        canvas = self._canvas()
        for band in (self._start_band, self._dest_band):
            if band is None:
                continue
            try:
                band.reset()
                if canvas is not None:
                    canvas.scene().removeItem(band)
            except Exception:  # noqa: BLE001
                pass
        self._start_band = None
        self._dest_band = None

    # ── toolbar / tool sync ────────────────────────────────────────────

    def _clear(self) -> None:
        self._start_fid = None
        self._dest = None
        self._clear_bands()
        self._remove_output("route")
        self._remove_output("reachable")
        self._bar_result("")
        self._set_interaction(RouteMapTool.INTERACT_START)

    def _set_interaction(self, mode: str) -> None:
        if self._tool is not None:
            self._tool.set_interaction(mode)
        if self._bar is not None:
            self._bar.set_tool(mode)

    def _on_bar_tool_changed(self, mode: str) -> None:
        canvas = self._canvas()
        if canvas is not None and self._tool is not None:
            if canvas.mapTool() is not self._tool:
                self._set_map_tool(canvas)
            self._tool.set_interaction(mode)

    def _on_interaction_changed(self, mode: str) -> None:
        if self._bar is not None:
            self._bar.set_tool(mode)

    def _bar_result(self, text: str) -> None:
        if self._bar is not None:
            self._bar.set_result(text)

    def _edge_label(self, fid) -> str:
        edge_id = self._edge_ids.get(fid, "")
        return edge_id or self.tr("feature {}").format(fid)

    def _set_map_tool(self, canvas) -> None:
        self._ignore_tool_change = True
        try:
            canvas.setMapTool(self._tool)
        finally:
            self._ignore_tool_change = False

    def _on_map_tool_set(self, new_tool, _old_tool=None) -> None:
        if not self._active or self._ignore_tool_change:
            return
        if new_tool is self._tool:
            return
        self._container.status.show(
            self.tr("Routability closed because another map tool was selected."),
            5000,
        )
        self.finish(silent=True)

    def _on_layer_removed(self, layer_id: str) -> None:
        if self._active and self._layer is not None and self._layer.id() == layer_id:
            self._container.notifications.info(
                self.tr("Routability closed because the edges layer was removed.")
            )
            self.finish(silent=True)

    def _canvas(self):
        try:
            return self._container.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            return None

    def _hide_map_panels(self) -> None:
        hide_fn = getattr(self._container, "hide_map_panels", None)
        if not callable(hide_fn) or self._hidden_panels is not None:
            return
        try:
            self._hidden_panels = hide_fn() or {}
        except Exception:  # noqa: BLE001
            LOG.exception("Could not hide map panels for routability")
            self._hidden_panels = {}

    def _restore_map_panels(self) -> None:
        state = self._hidden_panels
        self._hidden_panels = None
        restore_fn = getattr(self._container, "restore_map_panels", None)
        if state is None or not callable(restore_fn):
            return
        try:
            restore_fn(state)
        except Exception:  # noqa: BLE001
            LOG.exception("Could not restore map panels after routability")
