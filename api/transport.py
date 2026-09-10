# -*- coding: utf-8 -*-
"""Low-level HTTP transport using stdlib urllib (QGIS-safe, no extra deps)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..logging.logger import get_logger
from .errors import map_http_error, map_url_error

LOG = get_logger(__name__)


class HttpTransport:
    def __init__(self, default_timeout: int = 30) -> None:
        self.default_timeout = default_timeout

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[bytes, int, Dict[str, str]]:
        headers = dict(headers or {})
        request = Request(url, data=body, headers=headers, method=method)
        timeout = timeout if timeout is not None else self.default_timeout
        LOG.debug("HTTP %s %s", method, _safe_url(url))
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                status = getattr(response, "status", 200)
                return data, status, dict(response.headers)
        except HTTPError as exc:
            raise map_http_error(exc) from exc
        except URLError as exc:
            raise map_url_error(exc) from exc


def encode_json(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


def decode_json(data: bytes) -> Any:
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _safe_url(url: str) -> str:
    # Never log query tokens if present
    if "?" in url:
        return url.split("?", 1)[0] + "?…"
    return url
