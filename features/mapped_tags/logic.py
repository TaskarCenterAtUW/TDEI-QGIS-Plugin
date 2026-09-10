# -*- coding: utf-8 -*-
"""Mapped-item tags: normalize, suggest, and search matching."""

from __future__ import annotations

import json
import re
from typing import Iterable, List, Optional, Sequence

from ...core.models import MappedItem

MAX_TAG_LENGTH = 32
MAX_TAGS_PER_ITEM = 8
_WS = re.compile(r"\s+")


def normalize_tag(raw: str) -> str:
    """Return a display tag, or empty if the value is not usable."""
    text = _WS.sub(" ", (raw or "").strip())
    if text.startswith("#"):
        text = text[1:].strip()
    text = text.strip(" ,;|")
    if not text or len(text) > MAX_TAG_LENGTH:
        return ""
    if any(ch in text for ch in "\n\t,"):
        return ""
    return text


def tag_key(tag: str) -> str:
    return (tag or "").casefold()


def unique_tags(
    tags: Iterable[str], *, limit: int = MAX_TAGS_PER_ITEM
) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in tags:
        tag = normalize_tag(str(raw))
        if not tag:
            continue
        key = tag_key(tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if limit and len(out) >= limit:
            break
    return out


def parse_tags_payload(raw, *, limit: int = MAX_TAGS_PER_ITEM) -> List[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return unique_tags(raw, limit=limit)
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return unique_tags((part for part in text.split(",")), limit=limit)
    if isinstance(data, list):
        return unique_tags(data, limit=limit)
    return []


def serialize_tags(tags: Sequence[str], *, limit: int = MAX_TAGS_PER_ITEM) -> str:
    return json.dumps(unique_tags(tags, limit=limit), ensure_ascii=False)


def merge_catalog(*groups: Iterable[str]) -> List[str]:
    return unique_tags(
        (tag for group in groups for tag in group),
        limit=200,
    )


def suggest_tags(
    query: str,
    catalog: Sequence[str],
    *,
    exclude: Optional[Sequence[str]] = None,
    limit: int = 8,
) -> List[str]:
    needle = tag_key(normalize_tag(query) or (query or "").strip())
    blocked = {tag_key(item) for item in (exclude or [])}
    starts: List[str] = []
    contains: List[str] = []
    for tag in catalog:
        key = tag_key(tag)
        if not key or key in blocked:
            continue
        if needle and not needle in key:
            continue
        if needle and key.startswith(needle):
            starts.append(tag)
        else:
            contains.append(tag)
    ordered = starts + contains
    # Preserve catalog order within each bucket.
    seen = set()
    out: List[str] = []
    for tag in ordered:
        key = tag_key(tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def item_matches_query(item: MappedItem, query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return True
    name = (item.display_name or "").casefold()
    subtitle = (item.subtitle or "").casefold()
    key = (item.key or "").casefold()
    tags = [tag_key(tag) for tag in (item.tags or [])]
    for token in text.split():
        if token.startswith("#"):
            needle = tag_key(normalize_tag(token))
            if not needle:
                return False
            if needle not in tags and not any(needle in tag for tag in tags):
                return False
            continue
        needle = token.casefold()
        if not needle:
            continue
        in_text = needle in name or needle in subtitle or needle in key
        in_tags = any(needle in tag for tag in tags)
        if not (in_text or in_tags):
            return False
    return True
