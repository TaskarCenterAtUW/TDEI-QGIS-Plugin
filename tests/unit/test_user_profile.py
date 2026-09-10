# -*- coding: utf-8 -*-
"""Unit tests for user-profile name parsing."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT))

from tdei.api.v1.user_profile import parse_user_profile_names  # noqa: E402
from tdei.core.models import UserSession  # noqa: E402


class TestUserProfileNames(unittest.TestCase):
    def test_camel_case(self):
        first, last = parse_user_profile_names(
            {"firstName": "Ada", "lastName": "Lovelace"}
        )
        self.assertEqual(first, "Ada")
        self.assertEqual(last, "Lovelace")

    def test_snake_case_nested(self):
        first, last = parse_user_profile_names(
            {"data": {"first_name": "Grace", "last_name": "Hopper"}}
        )
        self.assertEqual(first, "Grace")
        self.assertEqual(last, "Hopper")

    def test_full_name_fallback(self):
        user = UserSession(username="a@b.com", display_name="a@b.com")
        self.assertEqual(user.full_name, "a@b.com")
        user.first_name = "Ada"
        user.last_name = "Lovelace"
        self.assertEqual(user.full_name, "Ada Lovelace")


if __name__ == "__main__":
    unittest.main()
