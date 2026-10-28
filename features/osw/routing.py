# -*- coding: utf-8 -*-
"""OSW edge graph routing (pure Python — no QGIS imports).

Edges connect nodes through ``_u_id`` (start node) and ``_v_id`` (end node).
Pedestrian OSW edges are walkable both ways, so the graph is undirected.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from itertools import count
from typing import Dict, Hashable, Iterable, List, Mapping, Optional, Set, Tuple

U_ID_FIELD = "_u_id"
V_ID_FIELD = "_v_id"
EDGE_ID_FIELD = "_id"
LENGTH_FIELD = "length"


def normalize_node_id(value) -> str:
    """Node ids may be ints, floats (``12.0``) or strings — compare as text."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.upper() in ("NULL", "NONE"):
        return ""
    return text


def has_routing_fields(field_names: Iterable[str]) -> bool:
    names = {str(name) for name in field_names or ()}
    return U_ID_FIELD in names and V_ID_FIELD in names


@dataclass
class RouteResult:
    edge_keys: List[Hashable]  # edges walked, in order (excludes start edge)
    nodes: List[str]  # node ids from the start node to the end node
    cost: float  # path cost including target offset
    target_node: str  # node where the path reaches the destination edge


@dataclass
class RoutingGraph:
    """Undirected multigraph keyed by OSW node ids."""

    adjacency: Dict[str, List[Tuple[str, Hashable, float]]] = field(
        default_factory=dict
    )
    edges: Dict[Hashable, Tuple[str, str, float]] = field(default_factory=dict)

    @classmethod
    def from_edges(
        cls, records: Iterable[Tuple[Hashable, object, object, float]]
    ) -> "RoutingGraph":
        graph = cls()
        for key, u, v, cost in records:
            graph.add_edge(key, u, v, cost)
        return graph

    def add_edge(self, key: Hashable, u, v, cost: float) -> bool:
        u_id = normalize_node_id(u)
        v_id = normalize_node_id(v)
        if not u_id or not v_id:
            return False
        try:
            weight = max(0.0, float(cost))
        except (TypeError, ValueError):
            weight = 0.0
        self.edges[key] = (u_id, v_id, weight)
        self.adjacency.setdefault(u_id, []).append((v_id, key, weight))
        if v_id != u_id:
            self.adjacency.setdefault(v_id, []).append((u_id, key, weight))
        return True

    @property
    def node_count(self) -> int:
        return len(self.adjacency)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def shortest_path(
        self,
        sources: Mapping[str, float],
        targets: Mapping[str, float],
    ) -> Optional[RouteResult]:
        """Multi-source Dijkstra.

        *sources* / *targets* map node id → extra cost to enter / leave the
        graph there (e.g. the distance along a partially walked edge).
        """
        dist: Dict[str, float] = {}
        prev: Dict[str, Tuple[str, Hashable]] = {}
        tie = count()
        heap: List[Tuple[float, int, str]] = []
        for node, offset in (sources or {}).items():
            node = normalize_node_id(node)
            if not node:
                continue
            cost = max(0.0, float(offset or 0.0))
            if cost < dist.get(node, float("inf")):
                dist[node] = cost
                heapq.heappush(heap, (cost, next(tie), node))

        wanted = {
            normalize_node_id(node): max(0.0, float(offset or 0.0))
            for node, offset in (targets or {}).items()
            if normalize_node_id(node)
        }
        if not heap or not wanted:
            return None

        best_cost = float("inf")
        best_node = ""
        settled: Set[str] = set()
        while heap:
            cost, _tie, node = heapq.heappop(heap)
            if node in settled:
                continue
            if cost >= best_cost:
                break
            settled.add(node)
            if node in wanted:
                total = cost + wanted[node]
                if total < best_cost:
                    best_cost = total
                    best_node = node
            for neighbor, key, weight in self.adjacency.get(node, ()):
                if neighbor in settled:
                    continue
                candidate = cost + weight
                if candidate < dist.get(neighbor, float("inf")):
                    dist[neighbor] = candidate
                    prev[neighbor] = (node, key)
                    heapq.heappush(heap, (candidate, next(tie), neighbor))

        if not best_node:
            return None
        nodes = [best_node]
        keys: List[Hashable] = []
        cursor = best_node
        while cursor in prev:
            parent, key = prev[cursor]
            keys.append(key)
            nodes.append(parent)
            cursor = parent
        keys.reverse()
        nodes.reverse()
        return RouteResult(
            edge_keys=keys, nodes=nodes, cost=best_cost, target_node=best_node
        )

    def reachable_edges(self, sources: Iterable[str]) -> Set[Hashable]:
        """Every edge connected to *sources* (breadth-first)."""
        seen_nodes: Set[str] = set()
        found: Set[Hashable] = set()
        stack = [normalize_node_id(node) for node in sources or ()]
        stack = [node for node in stack if node]
        while stack:
            node = stack.pop()
            if node in seen_nodes:
                continue
            seen_nodes.add(node)
            for neighbor, key, _weight in self.adjacency.get(node, ()):
                found.add(key)
                if neighbor not in seen_nodes:
                    stack.append(neighbor)
        return found
