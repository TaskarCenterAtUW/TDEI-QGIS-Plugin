# -*- coding: utf-8 -*-
"""Plugin lifecycle: initGui / unload / single main window."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Optional

from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator
from qgis.PyQt.QtGui import QIcon, QKeySequence
from qgis.PyQt.QtWidgets import QAction

from .config.defaults import DEFAULTS
from .config.settings import SettingsManager
from .core.services.container import ServiceContainer
from .core.utils.exception_handler import ExceptionHandler
from .logging.logger import configure_logging, get_logger
from .qgis.layer_context import LayerContextMenuController
from .qgis.map_search import MapSearchController
from .qgis.osw_preview import OswPreviewController
from .ui.dialogs.map_chrome import MapChromeBar

if TYPE_CHECKING:
    from qgis.gui import QgsInterface

LOG = get_logger(__name__)


class TdeiPlugin:
    """QGIS plugin entry — owns lifecycle and the main window singleton."""

    def __init__(self, iface: "QgsInterface") -> None:
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions: List[QAction] = []
        self.menu = self.tr("&TDEI")
        self._translator: Optional[QTranslator] = None
        self._main_window = None
        self._container: Optional[ServiceContainer] = None
        self._layer_context: Optional[LayerContextMenuController] = None
        self._map_search: Optional[MapSearchController] = None
        self._osw_preview: Optional[OswPreviewController] = None
        self._map_chrome: Optional[MapChromeBar] = None
        self._open_action: Optional[QAction] = None
        self._map_search_action: Optional[QAction] = None
        self._install_translator()

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("TDEI", message)

    def initGui(self) -> None:
        configure_logging()
        settings = SettingsManager()
        self._container = ServiceContainer(iface=self.iface, settings=settings)
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        shortcut = str(DEFAULTS.get("ui.open_shortcut", "Ctrl+Shift+T"))
        self._open_action = self.add_action(
            icon_path,
            text=self.tr("TDEI"),
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip=self.tr(
                "Open map search on the map ({shortcut})"
            ).format(shortcut=shortcut),
            shortcut=shortcut,
        )

        search_icon = os.path.join(
            self.plugin_dir, "ui", "icons", "action_map.svg"
        )
        self._map_search_action = self.add_action(
            search_icon if os.path.isfile(search_icon) else icon_path,
            text=self.tr("Search on map"),
            callback=self._toggle_map_search,
            parent=self.iface.mainWindow(),
            status_tip=self.tr(
                "Search TDEI datasets that overlap the current map view"
            ),
            checkable=True,
            add_to_toolbar=False,
            object_name="mActionTdeiMapSearch",
        )

        self._map_search = MapSearchController(self._container)
        self._container.map_search = self._map_search
        self._osw_preview = OswPreviewController(self._container)
        self._container.osw_preview = self._osw_preview
        self._layer_context = LayerContextMenuController(self._container)
        self._layer_context.attach()
        self._container.open_main_window = self.open_main_window
        self._container.open_jobs = self.open_jobs
        self._container.sync_map_chrome = self._sync_map_chrome
        self._container.hide_map_panels = self.hide_map_panels
        self._container.restore_map_panels = self.restore_map_panels
        LOG.info("TDEI plugin initialized (open shortcut: %s)", shortcut)

    def unload(self) -> None:
        self._hide_map_chrome()
        if self._osw_preview is not None:
            try:
                self._osw_preview.stop(silent=True)
            except Exception:  # noqa: BLE001
                pass
            self._osw_preview = None
        if self._map_search is not None:
            try:
                self._map_search.stop()
            except Exception:  # noqa: BLE001
                pass
            self._map_search = None
        if self._container is not None:
            self._container.map_search = None
            self._container.osw_preview = None
        if self._layer_context is not None:
            self._layer_context.detach()
            self._layer_context = None
        if self._main_window is not None:
            try:
                if hasattr(self._main_window, "detach_from_canvas"):
                    self._main_window.detach_from_canvas()
                self._main_window.close()
            except Exception:  # noqa: BLE001 — unload must not raise
                pass
            self._main_window = None
        if self._container is not None:
            self._container.sync_map_chrome = None
            self._container.hide_map_panels = None
            self._container.restore_map_panels = None
            self._container.shutdown()
            self._container = None
        for action in self.actions:
            try:
                self.iface.unregisterMainWindowAction(action)
            except Exception:  # noqa: BLE001 — unload must not raise
                pass
            self.iface.removePluginMenu(self.tr("&TDEI"), action)
            self.iface.removeToolBarIcon(action)
        self.actions.clear()
        self._open_action = None
        self._map_search_action = None
        LOG.info("TDEI plugin unloaded")

    def run(self) -> None:
        """Toolbar / shortcut: show chrome; map search if signed in, else TDEI login."""
        try:
            self._ensure_container()
            chrome = self._map_chrome
            window = self._main_window
            main_open = bool(window is not None and window.isVisible())
            search_on = bool(
                self._map_search is not None
                and getattr(self._map_search, "active", False)
            )
            if chrome is not None and chrome.isVisible():
                # Second click dismisses chrome when map search / TDEI are idle.
                if not main_open and not search_on:
                    self._hide_map_chrome()
                    return
            self._show_map_chrome()

            authenticated = False
            try:
                authenticated = bool(self._container.auth.is_authenticated())
            except Exception:  # noqa: BLE001
                authenticated = False

            # Fresh install / other machine: no session yet → open sign-in.
            if not authenticated:
                if self._map_search_action is not None:
                    self._map_search_action.blockSignals(True)
                    self._map_search_action.setChecked(False)
                    self._map_search_action.blockSignals(False)
                self.open_main_window()
                return

            # Default entry when signed in: map search (hides TDEI panel if open).
            if not search_on:
                action = self._map_search_action
                if action is not None and action.isCheckable():
                    action.blockSignals(True)
                    action.setChecked(True)
                    action.blockSignals(False)
                self._toggle_map_search(True)
            self._sync_map_chrome()
        except Exception as exc:  # noqa: BLE001
            ExceptionHandler.handle(
                exc,
                iface=self.iface,
                user_message=self.tr("Unable to show TDEI tools."),
            )

    def open_main_window(self) -> None:
        """Open the sticky TDEI panel on the map (hides map search)."""
        try:
            self._ensure_container()
            self._stop_map_search_for_tdei()
            if self._main_window is None:
                from .ui.main_window.main_window import MainWindow

                self._main_window = MainWindow(self._container)
                self._main_window.destroyed.connect(self._on_window_destroyed)
            self._attach_main_window_to_map()
            self._show_map_chrome()
            self._sync_map_chrome()
        except Exception as exc:  # noqa: BLE001
            ExceptionHandler.handle(
                exc,
                iface=self.iface,
                user_message=self.tr("Unable to open the TDEI plugin."),
            )

    def _attach_main_window_to_map(self) -> None:
        window = self._main_window
        if window is None:
            return
        canvas = None
        try:
            canvas = self.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is not None and hasattr(window, "position_on_canvas"):
            window.position_on_canvas(canvas)
        else:
            window.show()
            window.raise_()
            window.activateWindow()

    def _stop_map_search_for_tdei(self) -> None:
        if self._map_search is None:
            return
        if not getattr(self._map_search, "active", False):
            return
        try:
            self._map_search.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._map_search_action is not None:
            self._map_search_action.blockSignals(True)
            self._map_search_action.setChecked(False)
            self._map_search_action.blockSignals(False)

    def _hide_main_window_for_map_search(self) -> None:
        window = self._main_window
        if window is None:
            return
        if not window.isVisible():
            return
        try:
            window.hide()
        except Exception:  # noqa: BLE001
            pass

    def hide_map_panels(self) -> dict:
        """Hide TDEI panel, map search and chrome so a map tool can use the canvas.

        Returns what was visible, for :meth:`restore_map_panels`.
        """
        window = self._main_window
        state = {
            "main_window": bool(window is not None and window.isVisible()),
            "chrome": bool(
                self._map_chrome is not None and self._map_chrome.isVisible()
            ),
        }
        self._stop_map_search_for_tdei()
        if state["main_window"]:
            try:
                window.hide()
            except Exception:  # noqa: BLE001
                pass
        self._hide_map_chrome()
        return state

    def restore_map_panels(self, state: Optional[dict] = None) -> None:
        state = state or {}
        if state.get("main_window") and self._main_window is not None:
            self._attach_main_window_to_map()
        if state.get("chrome") or state.get("main_window"):
            self._show_map_chrome()
        self._sync_map_chrome()

    def _ensure_container(self) -> None:
        if self._container is not None:
            return
        settings = SettingsManager()
        self._container = ServiceContainer(iface=self.iface, settings=settings)
        self._container.open_main_window = self.open_main_window
        self._container.open_jobs = self.open_jobs
        self._container.sync_map_chrome = self._sync_map_chrome
        self._container.hide_map_panels = self.hide_map_panels
        self._container.restore_map_panels = self.restore_map_panels
        if self._map_search is None:
            self._map_search = MapSearchController(self._container)
        self._container.map_search = self._map_search
        if self._osw_preview is None:
            self._osw_preview = OswPreviewController(self._container)
        self._container.osw_preview = self._osw_preview

    def open_jobs(self, job_id: str = "") -> None:
        """Show the plugin window on the Jobs tab, optionally filtered to a job."""
        self.open_main_window()
        window = self._main_window
        if window is None:
            return
        try:
            window.open_jobs(job_id)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Could not open Jobs tab: %s", exc)

    def _show_map_chrome(self) -> None:
        canvas = None
        try:
            canvas = self.iface.mapCanvas()
        except Exception:  # noqa: BLE001
            canvas = None
        if canvas is None:
            return
        if self._map_chrome is None:
            icon_path = os.path.join(self.plugin_dir, "icon.png")
            self._map_chrome = MapChromeBar(
                None, plugin_icon_path=icon_path
            )
            self._map_chrome.tdei_clicked.connect(self._toggle_main_window)
            self._map_chrome.map_search_clicked.connect(
                self._on_chrome_map_search
            )
            self._map_chrome.close_clicked.connect(self._close_plugin_ui)
        self._map_chrome.position_on_canvas(canvas)
        try:
            self._map_chrome.raise_()
        except Exception:  # noqa: BLE001
            pass

    def _hide_map_chrome(self) -> None:
        chrome = self._map_chrome
        self._map_chrome = None
        if chrome is None:
            return
        try:
            chrome.detach_from_canvas()
            chrome.hide()
            chrome.deleteLater()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_main_window(self) -> None:
        window = self._main_window
        if window is None:
            self.open_main_window()
            return
        if window.isVisible():
            window.hide()
        else:
            self._stop_map_search_for_tdei()
            self._attach_main_window_to_map()
        self._show_map_chrome()
        self._sync_map_chrome()

    def _sync_map_chrome(self) -> None:
        chrome = self._map_chrome
        if chrome is None:
            return
        window = self._main_window
        visible = bool(window is not None and window.isVisible())
        chrome.set_tdei_visible(visible)
        search_on = bool(
            self._map_search is not None
            and getattr(self._map_search, "active", False)
        )
        chrome.set_map_search_active(search_on)
        if self._map_search_action is not None:
            self._map_search_action.blockSignals(True)
            self._map_search_action.setChecked(search_on)
            self._map_search_action.blockSignals(False)

    def _on_chrome_map_search(self) -> None:
        action = self._map_search_action
        want_on = True
        if self._map_search is not None and getattr(self._map_search, "active", False):
            want_on = False
        if action is not None and action.isCheckable():
            action.blockSignals(True)
            action.setChecked(want_on)
            action.blockSignals(False)
        self._toggle_map_search(want_on)
        self._sync_map_chrome()

    def _close_plugin_ui(self) -> None:
        """Close TDEI UI (window + map search + map chrome). Does not unload."""
        if self._osw_preview is not None:
            try:
                self._osw_preview.stop(silent=True)
            except Exception:  # noqa: BLE001
                pass
        if self._map_search is not None:
            try:
                self._map_search.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._map_search_action is not None:
            self._map_search_action.blockSignals(True)
            self._map_search_action.setChecked(False)
            self._map_search_action.blockSignals(False)
        if self._main_window is not None:
            try:
                if hasattr(self._main_window, "detach_from_canvas"):
                    self._main_window.detach_from_canvas()
                self._main_window.hide()
            except Exception:  # noqa: BLE001
                pass
        self._hide_map_chrome()

    def _toggle_map_search(self, checked: bool = False) -> None:
        action = self._map_search_action
        if self._map_search is None or self._container is None:
            if action is not None:
                action.setChecked(False)
            self._sync_map_chrome()
            return
        # QAction.triggered may pass checked for checkable actions.
        want_on = bool(checked) if action is not None and action.isCheckable() else True
        if action is not None and action.isCheckable():
            want_on = action.isChecked()

        if want_on:
            self._hide_main_window_for_map_search()
            started = self._map_search.start(
                on_stopped=self._on_map_search_stopped
            )
            if not started and action is not None:
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
        else:
            self._map_search.stop()
        self._show_map_chrome()
        self._sync_map_chrome()

    def _on_map_search_stopped(self) -> None:
        action = self._map_search_action
        if action is not None:
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)
        self._sync_map_chrome()

    def add_action(
        self,
        icon_path: str,
        text: str,
        callback,
        enabled_flag: bool = True,
        add_to_menu: bool = True,
        add_to_toolbar: bool = True,
        status_tip: Optional[str] = None,
        whats_this: Optional[str] = None,
        shortcut: Optional[str] = None,
        parent=None,
        checkable: bool = False,
        object_name: str = "mActionTdeiOpen",
    ) -> QAction:
        action = QAction(QIcon(icon_path), text, parent)
        action.setObjectName(object_name)
        action.setCheckable(bool(checkable))
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        if status_tip:
            action.setStatusTip(status_tip)
        if whats_this:
            action.setWhatsThis(whats_this)
        if shortcut:
            # Registers with QGIS so users can remap under Settings → Keyboard Shortcuts.
            self.iface.registerMainWindowAction(action, shortcut)
            action.setShortcut(QKeySequence(shortcut))
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)
        return action

    def _on_window_destroyed(self, *_args) -> None:
        self._main_window = None
        self._sync_map_chrome()

    def _install_translator(self) -> None:
        from qgis.core import QgsSettings

        locale = QgsSettings().value("locale/userLocale", QLocale().name())[0:2]
        locale_path = os.path.join(
            self.plugin_dir, "i18n", "{}.qm".format(locale)
        )
        if os.path.exists(locale_path):
            self._translator = QTranslator()
            self._translator.load(locale_path)
            QCoreApplication.installTranslator(self._translator)
