# -*- coding: utf-8 -*-
"""API v1 jobs list helpers."""

from __future__ import annotations

from typing import Any, List

from ...core.models import JobRecord


def parse_jobs(payload: Any) -> List[JobRecord]:
    items = _as_list(payload)
    jobs: List[JobRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        job_id = item.get("job_id")
        if job_id is None or job_id == "":
            continue
        download = item.get("download_url")
        download_url = "" if download is None else str(download).strip()
        jobs.append(
            JobRecord(
                id=str(job_id),
                job_type=str(item.get("job_type") or ""),
                status=str(item.get("status") or ""),
                download_url=download_url,
                message=str(item.get("message") or ""),
                project_group_id=str(item.get("tdei_project_group_id") or ""),
                project_group_name=str(
                    item.get("tdei_project_group_name") or ""
                ),
                created_at=str(item.get("created_at") or ""),
                updated_at=str(
                    item.get("updated_at") or item.get("last_updated_at") or ""
                ),
                raw=item,
            )
        )
    return jobs


def _as_list(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("jobs", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
