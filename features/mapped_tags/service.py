# -*- coding: utf-8 -*-
"""Persist tags on mapped layer groups, cache sidecars, and a suggestion catalog."""

from __future__ import annotations

from typing import List, Sequence

from .logic import merge_catalog, parse_tags_payload, serialize_tags, suggest_tags, unique_tags

CATALOG_SETTING = "ui.mapped_tag_catalog"
TAGS_PROPERTY = "tdei_tags"


class TagService:
    def __init__(self, layer_manager, settings) -> None:
        self._layers = layer_manager
        self._settings = settings

    def tags_for(self, key: str) -> List[str]:
        live = self._layers.get_item_tags(key)
        if live:
            return live
        return self._layers.read_cache_tags(key)

    def set_tags(self, key: str, tags: Sequence[str]) -> List[str]:
        cleaned = unique_tags(tags)
        try:
            self._layers.write_cache_tags(key, cleaned)
        except Exception:  # noqa: BLE001 — still update live group
            pass
        if self._layers.is_dataset_loaded(key):
            self._layers.set_item_tags(key, cleaned)
        self._remember(cleaned)
        return cleaned

    def catalog(self) -> List[str]:
        stored = parse_tags_payload(
            self._settings.get(CATALOG_SETTING, "[]"), limit=200
        )
        live = self._layers.collect_item_tags()
        cached = self._layers.collect_cache_tags()
        return merge_catalog(stored, live, cached)

    def suggest(
        self, query: str, *, exclude: Sequence[str] = ()
    ) -> List[str]:
        return suggest_tags(query, self.catalog(), exclude=exclude)

    def attach_to_items(self, items) -> None:
        for item in items:
            item.tags = self.tags_for(item.key)

    def _remember(self, tags: Sequence[str]) -> None:
        merged = merge_catalog(self.catalog(), tags)
        self._settings.set(CATALOG_SETTING, serialize_tags(merged, limit=200))
