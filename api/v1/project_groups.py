# -*- coding: utf-8 -*-
"""API v1 project-group helpers."""

from __future__ import annotations

from typing import Any, List

from ...core.models import ProjectGroup


def parse_project_groups(payload: Any) -> List[ProjectGroup]:
    items = _as_list(payload)
    groups: List[ProjectGroup] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        group_id = str(
            item.get("tdei_project_group_id")
            or item.get("project_group_id")
            or ""
        ).strip()
        if not group_id or group_id in seen:
            continue
        name = str(
            item.get("project_group_name")
            or item.get("name")
            or group_id
        ).strip()
        roles = item.get("roles") or []
        if not isinstance(roles, list):
            roles = []
        groups.append(
            ProjectGroup(
                id=group_id,
                name=name,
                roles=[str(r) for r in roles],
                raw=item,
            )
        )
        seen.add(group_id)
    return groups


def _as_list(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (
            "project_groups",
            "data",
            "items",
            "results",
            "groups",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
