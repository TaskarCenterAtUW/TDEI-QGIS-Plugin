# -*- coding: utf-8 -*-
"""Integration test placeholders (require network / QGIS as noted)."""

from __future__ import annotations

import unittest


class TestIntegrationPlaceholders(unittest.TestCase):
    def test_placeholder(self):
        """Wire live API tests behind an env flag in CI when available."""
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
