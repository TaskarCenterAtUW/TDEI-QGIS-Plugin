# -*- coding: utf-8 -*-
"""Small time-formatting helpers (no Qt)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def parse_timestamp(value: str) -> Optional[datetime]:
    """Parse gateway timestamps (ISO-8601, optional Z / offset)."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def format_duration(created_at: str, updated_at: str) -> str:
    """Human duration between two timestamps (e.g. ``2 hrs 4 mins``)."""
    start = parse_timestamp(created_at)
    end = parse_timestamp(updated_at)
    if start is None or end is None:
        return ""
    seconds = int(abs((end - start).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append("1 hr" if hours == 1 else "{} hrs".format(hours))
    if mins:
        parts.append("1 min" if mins == 1 else "{} mins".format(mins))
    if not parts:
        if secs:
            parts.append("1 sec" if secs == 1 else "{} secs".format(secs))
        else:
            parts.append("0 mins")
    return " ".join(parts)


def format_timestamp(value: str, *, fallback: str = "—") -> str:
    """Compact local display for an ISO timestamp (e.g. ``2024-03-12 14:05``)."""
    parsed = parse_timestamp(value)
    if parsed is None:
        text = (value or "").strip()
        return text or fallback
    try:
        local = parsed.astimezone().replace(tzinfo=None)
    except Exception:
        local = parsed.replace(tzinfo=None)
    return local.strftime("%Y-%m-%d %H:%M")
