# -*- coding: utf-8 -*-
"""Centralized application logging (never log secrets)."""

from __future__ import annotations

import logging
import re
from typing import Optional

_CONFIGURED = False
_SENSITIVE = re.compile(
    r"(password|passwd|secret|token|authorization|bearer|refresh)",
    re.IGNORECASE,
)


class RedactingFilter(logging.Filter):
    """Strip obvious credential patterns from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if _SENSITIVE.search(message):
            record.msg = "[redacted sensitive log content]"
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    root = logging.getLogger("tdei")
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] tdei.%(name)s: %(message)s"
            )
        )
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    if name.startswith("tdei"):
        return logging.getLogger(name)
    return logging.getLogger("tdei.{}".format(name))
