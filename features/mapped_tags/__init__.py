# -*- coding: utf-8 -*-
from .logic import (
    item_matches_query,
    merge_catalog,
    normalize_tag,
    parse_tags_payload,
    serialize_tags,
    suggest_tags,
    unique_tags,
)
from .service import CATALOG_SETTING, TAGS_PROPERTY, TagService

__all__ = [
    "CATALOG_SETTING",
    "TAGS_PROPERTY",
    "TagService",
    "item_matches_query",
    "merge_catalog",
    "normalize_tag",
    "parse_tags_payload",
    "serialize_tags",
    "suggest_tags",
    "unique_tags",
]
