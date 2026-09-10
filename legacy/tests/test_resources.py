# coding=utf-8
"""Resources test."""

__author__ = 'test@test.com'
__date__ = '2026-08-26'
__copyright__ = 'Copyright 2026, TDEI'

import unittest

from qgis.PyQt.QtGui import QIcon


class TdeiResourcesTest(unittest.TestCase):
    """Test resources work."""

    def setUp(self):
        """Runs before each test."""
        pass

    def tearDown(self):
        """Runs after each test."""
        pass

    def test_icon_png(self):
        """Test plugin icon resource path resolves."""
        path = ':/plugins/tdei/icon.png'
        icon = QIcon(path)
        self.assertFalse(icon.isNull())


if __name__ == "__main__":
    suite = unittest.makeSuite(TdeiResourcesTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
