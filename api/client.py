# -*- coding: utf-8 -*-
"""Central API client — all HTTP goes through here."""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional
from urllib.parse import quote, urlencode

from ..config.environment import resolve_environment
from ..core.exceptions import AuthenticationError, UnexpectedApiError
from ..core.models import TokenPair
from ..logging.logger import get_logger
from .transport import HttpTransport, decode_json, encode_json

if TYPE_CHECKING:
    from ..config.settings import SettingsManager
    from ..auth.token_manager import TokenManager

LOG = get_logger(__name__)


class ApiClient:
    """Authenticated JSON/binary HTTP client for TDEI Gateway."""

    def __init__(
        self,
        settings: "SettingsManager",
        token_provider: "TokenManager",
        on_unauthorized: Optional[Callable[[], None]] = None,
        transport: Optional[HttpTransport] = None,
    ) -> None:
        self._settings = settings
        self._tokens = token_provider
        self._on_unauthorized = on_unauthorized
        self._transport = transport or HttpTransport(
            default_timeout=settings.int("request_timeout_seconds", 30)
        )
        self.reload_base_url()

    def reload_base_url(self) -> None:
        env = resolve_environment(self._settings)
        self.base_url = env.api_base_url
        self.user_management_base_url = env.user_management_api_base_url
        self.auth_url = env.auth_url

    def close(self) -> None:
        pass

    def authenticate(self, username: str, password: str) -> TokenPair:
        payload = encode_json({"username": username, "password": password})
        try:
            data, _status, _headers = self._transport.request(
                self.auth_url,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body=payload,
                timeout=self._settings.int("request_timeout_seconds", 30),
            )
        except AuthenticationError as exc:
            raise AuthenticationError(
                "Invalid username or password."
            ) from exc
        body = decode_json(data)
        return self._parse_token_response(body)

    def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Refresh access token when the API supports it.

        Current TDEI authenticate API may not expose refresh; this endpoint
        path is configurable for forward compatibility.
        """
        url = "{}/authenticate/refresh".format(self.base_url.rstrip("/"))
        payload = encode_json({"refresh_token": refresh_token})
        data, _status, _headers = self._transport.request(
            url,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body=payload,
        )
        return self._parse_token_response(decode_json(data))

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._json("GET", path, **kwargs)

    def get_text(self, path: str, **kwargs: Any) -> str:
        """GET a plain-text (or JSON-string) body — used for SAS URL endpoints."""
        params = kwargs.pop("params", None)
        base_url = kwargs.pop("base_url", None)
        url = self._url(path, base_url=base_url) + _query_string(params)
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/json, text/plain, */*")
        data, status, _headers = self._authorized_request(
            url, method="GET", headers=headers, **kwargs
        )
        if not data:
            if 200 <= status < 300:
                return ""
            raise UnexpectedApiError("Empty response from TDEI.", status_code=status)
        raw = data.decode("utf-8", errors="replace").strip()
        if not raw:
            return ""
        # Express may send a JSON-encoded string or raw URL text.
        if raw.startswith('"') or raw.startswith("{"):
            try:
                parsed = decode_json(data)
            except ValueError:
                parsed = None
            if isinstance(parsed, str):
                return parsed.strip()
            if isinstance(parsed, dict):
                for key in ("url", "sasUrl", "sas_url", "pmTilesUrl", "pm_tiles_url"):
                    value = parsed.get(key)
                    if value:
                        return str(value).strip()
        return raw.strip().strip('"')

    def get_user_management(self, path: str, **kwargs: Any) -> Any:
        """GET against the user-management (portal) API host."""
        kwargs["base_url"] = self.user_management_base_url
        return self._json("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._json("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._json("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._json("DELETE", path, **kwargs)

    def download(
        self,
        path: str,
        dest_path: str,
        *,
        timeout: Optional[int] = None,
        query: str = "",
    ) -> str:
        data = self.download_bytes(path, timeout=timeout, query=query)
        parent = os.path.dirname(dest_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest_path, "wb") as handle:
            handle.write(data)
        return dest_path

    def download_bytes(
        self,
        path: str,
        *,
        timeout: Optional[int] = None,
        query: str = "",
    ) -> bytes:
        url = self._url(path) + query
        data, _status, _headers = self._authorized_request(
            url,
            method="GET",
            headers={"Accept": "application/octet-stream"},
            timeout=timeout
            or self._settings.int("download_timeout_seconds", 180),
        )
        if not data:
            raise UnexpectedApiError("Download returned an empty file.")
        return data

    def post_multipart(
        self,
        url: str,
        *,
        fields: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._multipart(
            "POST",
            url,
            fields=fields,
            files=files,
            timeout=timeout,
        )

    def put_multipart(
        self,
        url: str,
        *,
        fields: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._multipart(
            "PUT",
            url,
            fields=fields,
            files=files,
            timeout=timeout,
        )

    def _multipart(
        self,
        method: str,
        url: str,
        *,
        fields: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        body, content_type = _encode_multipart(fields or {}, files or {})
        data, _status, response_headers = self._authorized_request(
            url,
            method=method,
            headers={"Accept": "application/json", "Content-Type": content_type},
            body=body,
            timeout=timeout or self._settings.int("job_timeout_seconds", 60),
        )
        result = _parse_job_response(data)
        location = response_headers.get("Location") or response_headers.get("location")
        if location and "location" not in result:
            result["location"] = location
        return result

    def post_json_url(
        self,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        headers = {"Accept": "application/json"}
        body = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = encode_json(json_body)
        data, _status, response_headers = self._authorized_request(
            url,
            method="POST",
            headers=headers,
            body=body,
            timeout=timeout or self._settings.int("job_timeout_seconds", 60),
        )
        result = _parse_job_response(data)
        location = response_headers.get("Location") or response_headers.get("location")
        if location and "location" not in result:
            result["location"] = location
        return result

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        params = kwargs.pop("params", None)
        base_url = kwargs.pop("base_url", None)
        url = self._url(path, base_url=base_url) + _query_string(params)
        headers = {"Accept": "application/json"}
        body = None
        json_body = kwargs.pop("json", None)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = encode_json(json_body)
        data, status, _headers = self._authorized_request(
            url, method=method, headers=headers, body=body, **kwargs
        )
        if not data:
            if 200 <= status < 300:
                return {}
            raise UnexpectedApiError("Empty response from TDEI.", status_code=status)
        try:
            return decode_json(data)
        except ValueError as exc:
            raise UnexpectedApiError("TDEI returned invalid JSON.") from exc

    def _authorized_request(self, url: str, **kwargs: Any):
        headers = dict(kwargs.pop("headers", {}) or {})
        token = self._tokens.get_access_token()
        if token:
            headers["Authorization"] = "Bearer {}".format(token)
        try:
            return self._transport.request(url, headers=headers, **kwargs)
        except AuthenticationError:
            if self._on_unauthorized:
                self._on_unauthorized()
            raise

    def _url(self, path: str, base_url: Optional[str] = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        root = (base_url or self.base_url).rstrip("/")
        return "{}/{}".format(root, path.lstrip("/"))

    @staticmethod
    def _parse_token_response(body: Any) -> TokenPair:
        if not isinstance(body, dict):
            raise AuthenticationError("Unexpected authentication response.")
        access = (
            body.get("access_token")
            or body.get("accessToken")
            or body.get("token")
        )
        if not access:
            raise AuthenticationError(
                "Sign in succeeded but no access token was returned."
            )
        refresh = body.get("refresh_token") or body.get("refreshToken")
        expires_at = None
        expires_in = body.get("expires_in") or body.get("expiresIn")
        if expires_in is not None:
            try:
                expires_at = time.time() + float(expires_in)
            except (TypeError, ValueError):
                expires_at = None
        return TokenPair(
            access_token=str(access),
            refresh_token=str(refresh) if refresh else None,
            expires_at=expires_at,
            token_type=str(body.get("token_type") or body.get("tokenType") or "Bearer"),
        )


def _parse_job_response(data: bytes) -> Dict[str, Any]:
    if not data:
        return {}
    raw = data.decode("utf-8", errors="replace").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {"job_id": raw, "_raw": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"job_id": str(parsed)}


def _query_string(params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return ""
    items = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            items.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                if item is None or item == "":
                    continue
                if isinstance(item, bool):
                    items.append((key, "true" if item else "false"))
                else:
                    items.append((key, str(item)))
        else:
            items.append((key, str(value)))
    if not items:
        return ""
    return "?" + urlencode(items)


def _encode_multipart(
    fields: Dict[str, Any], files: Dict[str, str]
) -> tuple:
    boundary = "----TdeiBoundary7MA4YWxkTrZu0gW"
    chunks = []

    def add_field(name: str, value: Any) -> None:
        chunks.append("--{}\r\n".format(boundary).encode("utf-8"))
        chunks.append(
            'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(
                name
            ).encode("utf-8")
        )
        chunks.append("{}".format(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for name, value in fields.items():
        if value is None or value == "":
            continue
        add_field(name, value)
    for name, path in files.items():
        if not path:
            continue
        filename = os.path.basename(path)
        with open(path, "rb") as handle:
            payload = handle.read()
        chunks.append("--{}\r\n".format(boundary).encode("utf-8"))
        chunks.append(
            'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
                name, filename
            ).encode("utf-8")
        )
        chunks.append(b"Content-Type: application/octet-stream\r\n\r\n")
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append("--{}--\r\n".format(boundary).encode("utf-8"))
    return b"".join(chunks), "multipart/form-data; boundary={}".format(boundary)
