# -*- coding: utf-8 -*-
"""Unit tests for environment resolution."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.tests.fixtures.qgis_stubs import FakeSettings, install_qgis_stubs

install_qgis_stubs()

from tdei.config.environment import (  # noqa: E402
    get_environment_urls,
    resolve_environment,
    set_environment_urls,
)


class TestEnvironment(unittest.TestCase):
    def test_development_default(self):
        settings = FakeSettings({"environment": "development"})
        env = resolve_environment(settings)
        self.assertIn("api-dev.tdei.us", env.api_base_url)
        self.assertIn("portal-api-dev.tdei.us", env.user_management_api_base_url)
        self.assertTrue(env.auth_url.endswith("/authenticate"))
        self.assertEqual(env.short_label, "Development")

    def test_staging_user_management_host(self):
        settings = FakeSettings({"environment": "staging"})
        env = resolve_environment(settings)
        self.assertEqual(
            env.user_management_api_base_url,
            "https://portal-api-stage.tdei.us/api/v1",
        )

    def test_per_env_url_override(self):
        settings = FakeSettings({"environment": "development"})
        set_environment_urls(
            settings,
            "development",
            "https://gw.example.test/api/v1",
            "https://um.example.test/api/v1",
        )
        env = resolve_environment(settings)
        self.assertEqual(env.api_base_url, "https://gw.example.test/api/v1")
        self.assertEqual(
            env.user_management_api_base_url,
            "https://um.example.test/api/v1",
        )
        api, um = get_environment_urls(settings, "staging")
        self.assertIn("api-stage.tdei.us", api)
        self.assertIn("portal-api-stage.tdei.us", um)

    def test_custom_url(self):
        settings = FakeSettings(
            {
                "environment": "custom",
                "custom_api_base_url": "https://example.test/api/v1",
                "custom_user_management_api_base_url": (
                    "https://portal.example.test/api/v1"
                ),
            }
        )
        env = resolve_environment(settings)
        self.assertEqual(env.api_base_url, "https://example.test/api/v1")
        self.assertEqual(
            env.user_management_api_base_url,
            "https://portal.example.test/api/v1",
        )
        self.assertEqual(
            env.auth_url, "https://example.test/api/v1/authenticate"
        )

    def test_custom_um_falls_back_to_gateway(self):
        settings = FakeSettings(
            {
                "environment": "custom",
                "custom_api_base_url": "https://example.test/api/v1",
            }
        )
        env = resolve_environment(settings)
        self.assertEqual(
            env.user_management_api_base_url,
            "https://example.test/api/v1",
        )


if __name__ == "__main__":
    unittest.main()
