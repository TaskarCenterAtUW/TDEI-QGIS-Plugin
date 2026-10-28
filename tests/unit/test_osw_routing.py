# -*- coding: utf-8 -*-
"""Unit tests for OSW edge-graph routing."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.features.osw.routing import (  # noqa: E402
    RoutingGraph,
    has_routing_fields,
    normalize_node_id,
)


def _graph():
    #   a --1-- b --1-- c
    #   |               |
    #   +------5--------+      d --1-- e   (separate island)
    return RoutingGraph.from_edges(
        [
            ("ab", "a", "b", 1.0),
            ("bc", "b", "c", 1.0),
            ("ac", "a", "c", 5.0),
            ("de", "d", "e", 1.0),
        ]
    )


class TestOswRouting(unittest.TestCase):
    def test_normalize_node_id(self):
        self.assertEqual(normalize_node_id(12.0), "12")
        self.assertEqual(normalize_node_id(" 7 "), "7")
        self.assertEqual(normalize_node_id(None), "")
        self.assertEqual(normalize_node_id("NULL"), "")

    def test_has_routing_fields(self):
        self.assertTrue(has_routing_fields(["_id", "_u_id", "_v_id"]))
        self.assertFalse(has_routing_fields(["_id", "_u_id"]))

    def test_skips_edges_without_nodes(self):
        graph = RoutingGraph.from_edges([("x", "", "b", 1.0), ("y", "a", "b", 1.0)])
        self.assertEqual(graph.edge_count, 1)

    def test_shortest_path_prefers_cheaper_route(self):
        result = _graph().shortest_path({"a": 0.0}, {"c": 0.0})
        self.assertIsNotNone(result)
        self.assertEqual(result.edge_keys, ["ab", "bc"])
        self.assertEqual(result.nodes, ["a", "b", "c"])
        self.assertAlmostEqual(result.cost, 2.0)

    def test_graph_is_undirected(self):
        result = _graph().shortest_path({"c": 0.0}, {"a": 0.0})
        self.assertEqual(result.edge_keys, ["bc", "ab"])

    def test_target_offsets_choose_best_endpoint(self):
        # Reaching c directly costs 2 + 10; reaching b costs 1 + 0.5.
        result = _graph().shortest_path({"a": 0.0}, {"c": 10.0, "b": 0.5})
        self.assertEqual(result.target_node, "b")
        self.assertAlmostEqual(result.cost, 1.5)

    def test_multi_source(self):
        result = _graph().shortest_path({"a": 3.0, "c": 0.0}, {"b": 0.0})
        self.assertEqual(result.edge_keys, ["bc"])

    def test_source_is_target(self):
        result = _graph().shortest_path({"a": 0.0}, {"a": 0.0})
        self.assertEqual(result.edge_keys, [])
        self.assertEqual(result.cost, 0.0)

    def test_no_route_between_islands(self):
        self.assertIsNone(_graph().shortest_path({"a": 0.0}, {"e": 0.0}))

    def test_reachable_edges(self):
        graph = _graph()
        self.assertEqual(graph.reachable_edges(["a"]), {"ab", "bc", "ac"})
        self.assertEqual(graph.reachable_edges(["e"]), {"de"})


if __name__ == "__main__":
    unittest.main()
