# coding=utf-8
"""Dialog tests for TdeiDialog."""

__author__ = 'test@test.com'
__date__ = '2026-08-26'
__copyright__ = 'Copyright 2026, TDEI'

import unittest

from qgis.PyQt.QtWidgets import QLineEdit

from tdei_dialog import TdeiDialog

from utilities import get_qgis_app
QGIS_APP = get_qgis_app()


class TdeiDialogTest(unittest.TestCase):
    """Test dialog widgets load."""

    def setUp(self):
        """Runs before each test."""
        self.dialog = TdeiDialog(None)

    def tearDown(self):
        """Runs after each test."""
        self.dialog = None

    def test_login_widgets(self):
        """Login page exposes username, password, and sign-in controls."""
        self.assertEqual(self.dialog.txtPassword.echoMode(), QLineEdit.Password)
        self.assertEqual(
            self.dialog.stackedWidget.currentWidget(),
            self.dialog.pageLogin)
        self.assertTrue(self.dialog.btnLogin.isEnabled())

    def test_dataset_table_columns(self):
        """Datasets table has tdei_dataset_id and name columns."""
        self.assertEqual(self.dialog.tblDatasets.columnCount(), 3)
        header = self.dialog.tblDatasets.horizontalHeaderItem
        self.assertEqual(header(0).text(), 'tdei_dataset_id')
        self.assertEqual(header(1).text(), 'name')
        self.assertEqual(header(2).text(), 'View in QGIS')


if __name__ == "__main__":
    suite = unittest.makeSuite(TdeiDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
