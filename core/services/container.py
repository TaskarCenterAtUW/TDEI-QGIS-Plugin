# -*- coding: utf-8 -*-
"""Simple constructor-injection service locator for the plugin session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ...api.client import ApiClient
from ...auth.auth_manager import AuthManager
from ...auth.login_service import LoginService
from ...auth.session_manager import SessionManager
from ...auth.token_manager import TokenManager
from ...config.environment import resolve_environment
from ...config.settings import SettingsManager
from ...core.workers import WorkerPool
from ...features.datasets.service import DatasetService
from ...features.mapped_tags.service import TagService
from ...features.jobs.service import JobService
from ...features.cache_sync import CacheSyncService
from ...features.project_groups.service import ProjectGroupService
from ...qgis.basemap_manager import BasemapManager
from ...qgis.layer_manager import LayerManager
from ...qgis.project_manager import ProjectManager
from ...ui.notifications.notification_service import NotificationService
from .status_service import StatusService

if TYPE_CHECKING:
    from qgis.gui import QgsInterface


class ServiceContainer:
    """Wires concrete implementations for one plugin session."""

    def __init__(
        self,
        iface: "QgsInterface",
        settings: Optional[SettingsManager] = None,
    ) -> None:
        self.iface = iface
        self.settings = settings or SettingsManager()
        self.workers = WorkerPool()
        self.tokens = TokenManager(self.settings)
        self.session = SessionManager(self.tokens)
        self.api = ApiClient(
            settings=self.settings,
            token_provider=self.tokens,
            on_unauthorized=self._on_unauthorized,
        )
        self.auth = AuthManager(
            api_client=self.api,
            token_manager=self.tokens,
            session_manager=self.session,
            settings=self.settings,
        )
        self.login_service = LoginService(self.auth)
        self.status = StatusService()
        self.notifications = NotificationService(
            iface=iface, settings=self.settings
        )
        self.layers = LayerManager(
            iface=iface,
            env_key_provider=lambda: resolve_environment(self.settings).key,
        )
        self.basemaps = BasemapManager(self.settings)
        self.project = ProjectManager()
        self.project.connect_project_signals()
        self.project_groups = ProjectGroupService(
            api_client=self.api,
            settings=self.settings,
            session=self.session,
            tokens=self.tokens,
        )
        self.datasets = DatasetService(
            api_client=self.api,
            layer_manager=self.layers,
            settings=self.settings,
            basemap_manager=self.basemaps,
            project_groups=self.project_groups,
        )
        self.jobs = JobService(
            api_client=self.api,
            layer_manager=self.layers,
            settings=self.settings,
        )
        self.tags = TagService(
            layer_manager=self.layers,
            settings=self.settings,
        )
        self.cache_sync = CacheSyncService(
            layer_manager=self.layers,
            basemap_manager=self.basemaps,
        )
        self.on_environment_changed = None
        # Set by plugin — open main window / Jobs tab after layer-menu submit.
        self.open_main_window = None
        self.open_jobs = None
        self.request_sync = None
        self.sync_map_chrome = None
        # Set by plugin — hide / restore map overlays around a map tool (clip).
        self.hide_map_panels = None
        self.restore_map_panels = None
        # Optional: DatasetsPage.notify_dataset_loaded after external download.
        self.on_dataset_loaded = None
        # Optional controllers (map search / clip / OSW preview).
        self.map_search = None
        self.bbox_capture = None
        self.osw_preview = None

    def refresh_environment(self) -> None:
        self.api.reload_base_url()
        if callable(self.on_environment_changed):
            self.on_environment_changed()

    def environment(self):
        return resolve_environment(self.settings)

    def _on_unauthorized(self) -> None:
        self.auth.handle_unauthorized()

    def shutdown(self) -> None:
        preview = getattr(self, "osw_preview", None)
        if preview is not None:
            try:
                preview.stop(silent=True)
            except Exception:  # noqa: BLE001
                pass
        map_search = getattr(self, "map_search", None)
        if map_search is not None and getattr(map_search, "active", False):
            try:
                map_search.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.layers.clear_map_search_layers()
        except Exception:  # noqa: BLE001
            pass
        self.workers.shutdown()
        self.api.close()
