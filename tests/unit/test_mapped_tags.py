# -*- coding: utf-8 -*-
"""Unit tests for mapped-item tags and search matching."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT))

from tdei.core.models import MappedItem  # noqa: E402
from tdei.features.mapped_tags.logic import (  # noqa: E402
    item_matches_query,
    merge_catalog,
    normalize_tag,
    parse_tags_payload,
    serialize_tags,
    suggest_tags,
    unique_tags,
)


class MappedTagLogicTests(unittest.TestCase):
    def test_normalize_strips_hash_and_space(self):
        self.assertEqual(normalize_tag("  #Sidewalk  "), "Sidewalk")
        self.assertEqual(normalize_tag(""), "")
        self.assertEqual(normalize_tag("a" * 40), "")

    def test_unique_is_case_insensitive(self):
        self.assertEqual(unique_tags(["Curb", "curb", "Ramp"]), ["Curb", "Ramp"])

    def test_serialize_roundtrip(self):
        payload = serialize_tags(["clip", "downtown"])
        self.assertEqual(parse_tags_payload(payload), ["clip", "downtown"])

    def test_suggest_prefers_prefix(self):
        catalog = ["sidewalk", "residential", "clip"]
        self.assertEqual(suggest_tags("si", catalog)[0], "sidewalk")
        self.assertIn("clip", suggest_tags("c", catalog))

    def test_search_matches_name_id_and_tags(self):
        item = MappedItem(
            key="abc-123",
            display_name="Downtown sidewalks",
            tags=["clip", "review"],
        )
        self.assertTrue(item_matches_query(item, "down"))
        self.assertTrue(item_matches_query(item, "abc"))
        self.assertTrue(item_matches_query(item, "clip"))
        self.assertTrue(item_matches_query(item, "#rev"))
        self.assertFalse(item_matches_query(item, "#missing"))
        self.assertTrue(item_matches_query(item, "downtown #clip"))
        self.assertFalse(item_matches_query(item, "downtown #missing"))

    def test_catalog_merge_keeps_order(self):
        merged = merge_catalog(["alpha", "beta"], ["beta", "gamma"])
        self.assertEqual(merged, ["alpha", "beta", "gamma"])
