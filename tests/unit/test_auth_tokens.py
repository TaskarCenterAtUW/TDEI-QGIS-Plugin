# -*- coding: utf-8 -*-
"""Unit tests for HTTP error mapping and token expiry."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.tests.fixtures.qgis_stubs import FakeSettings, install_qgis_stubs

install_qgis_stubs()

from tdei.api.errors import map_http_error  # noqa: E402
from tdei.auth.token_manager import TokenManager  # noqa: E402
from tdei.core.exceptions import (  # noqa: E402
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from tdei.core.models import TokenPair  # noqa: E402


class TestErrorMapping(unittest.TestCase):
    def test_401(self):
        exc = MagicMock()
        exc.code = 401
        exc.read.return_value = b'{"message":"nope"}'
        mapped = map_http_error(exc)
        self.assertIsInstance(mapped, AuthenticationError)

    def test_404(self):
        exc = MagicMock()
        exc.code = 404
        exc.read.return_value = b"{}"
        self.assertIsInstance(map_http_error(exc), NotFoundError)

    def test_429(self):
        exc = MagicMock()
        exc.code = 429
        exc.read.return_value = b"{}"
        self.assertIsInstance(map_http_error(exc), RateLimitError)

    def test_500(self):
        exc = MagicMock()
        exc.code = 500
        exc.read.return_value = b'{"message":"boom"}'
        mapped = map_http_error(exc)
        self.assertIsInstance(mapped, ServerError)
        self.assertEqual(mapped.status_code, 500)


class TestTokenManager(unittest.TestCase):
    def test_store_and_load(self):
        settings = FakeSettings()
        manager = TokenManager(settings)
        manager.store(
            TokenPair(access_token="abc", refresh_token="r1", expires_at=None)
        )
        self.assertEqual(manager.get_access_token(), "abc")
        self.assertEqual(manager.get_refresh_token(), "r1")

    def test_expiry(self):
        settings = FakeSettings({"token_refresh_skew_seconds": 60})
        manager = TokenManager(settings)
        manager.store(
            TokenPair(
                access_token="abc",
                expires_at=time.time() - 10,
            )
        )
        self.assertTrue(manager.is_expired())

    def test_clear(self):
        settings = FakeSettings()
        manager = TokenManager(settings)
        manager.store(TokenPair(access_token="abc"))
        manager.clear()
        self.assertIsNone(manager.get_access_token())


if __name__ == "__main__":
    unittest.main()
