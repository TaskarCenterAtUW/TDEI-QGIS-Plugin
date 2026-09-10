# -*- coding: utf-8 -*-
"""Main application window — shell only; pages own their workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import (
    QAction,
    QFrame,
    QHBoxLayout,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...config.defaults import ENVIRONMENTS
from ...config.environment import standard_environment_keys
from ..a11y import set_name, set_page
from ..components import AppHeader, PageContainer, Sidebar
from ..dashboard.page import DashboardPage
from ..datasets.page import DatasetsPage
from ..dialogs.confirmation_dialog import ConfirmationDialog
from ..dialogs.map_overlay import apply_glass_frame, pointer_over_overlay
from ..jobs.page import JobsPage
from ..login.page import LoginPage
from ..motion import PAGE_MS, fade_in
from ..navigation import NavigationManager
from ..settings.page import SettingsPage
from ..styles import colors, dimensions
from ..styles.theme import theme

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer


class MainWindow(QFrame):
    """Sticky TDEI app panel on the map canvas (QFrame — not QMainWindow)."""

    def __init__(self, container: "ServiceContainer") -> None:
        # Parent later via position_on_canvas; never embed QMainWindow on canvas.
        super().__init__(None)
        self._container = container
        self.setObjectName("TdeiMainWindow")
        self.setWindowTitle(self.tr("TDEI"))
        self.setWindowFlags(Qt.Widget)
        apply_glass_frame(self)
        self.setFocusPolicy(Qt.StrongFocus)
        self._canvas_host = None
        self._map_canvas_ref = None
        set_page(
            self,
            self.tr("TDEI"),
            self.tr("TDEI plugin for QGIS"),
        )
        dimensions.refresh_ui_scale(self)
        self.setStyleSheet(theme.application_stylesheet() + self._overlay_chrome())
        self.setCursor(Qt.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._nav = NavigationManager()
        self._stack = QStackedWidget()
        shell.addWidget(self._stack, 1)

        self._login = LoginPage(container)
        self._login.login_succeeded.connect(self._show_app)
        self._stack.addWidget(self._login)

        self._app_root = QWidget()
        app_layout = QVBoxLayout(self._app_root)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(0)

        self._header = AppHeader()
        self._header.logout_requested.connect(self._logout)
        self._header.sync_requested.connect(self._on_sync)
        self._header.minimize_requested.connect(self._minimize_window)
        app_layout.addWidget(self._header)
        self._syncing = False

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        nav_items = [
            ("dashboard", self.tr("Dashboard"), "nav_dashboard.svg"),
            ("datasets", self.tr("Datasets"), "nav_datasets.svg"),
            ("jobs", self.tr("Jobs"), "nav_jobs.svg"),
        ]
        footer_items = [
            ("settings", self.tr("Settings"), "nav_settings.svg"),
        ]
        self._sidebar = Sidebar(
            nav_items,
            footer_items=footer_items,
            # Sticky map panel always opens with navigation collapsed.
            collapsed=True,
        )
        self._sidebar.navigate.connect(self._on_navigate)
        self._sidebar.collapsed_changed.connect(self._on_sidebar_collapsed)
        self._pages = PageContainer()
        body.addWidget(self._sidebar)
        body.addWidget(self._pages, 1)
        app_layout.addLayout(body, 1)

        self._stack.addWidget(self._app_root)

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setAccessibleName(self.tr("Status bar"))
        self._progress = QProgressBar()
        self._progress.setObjectName("StatusProgress")
        self._progress.setMinimumWidth(120)
        self._progress.setMaximumWidth(220)
        self._progress.setMaximumHeight(16)
        self._progress.setTextVisible(False)
        self._progress.setAccessibleName(self.tr("Progress"))
        self._progress.hide()
        self._status_bar.addPermanentWidget(self._progress)
        self._status_env = QToolButton()
        self._status_env.setObjectName("StatusEnv")
        self._status_env.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._status_env.setPopupMode(QToolButton.InstantPopup)
        self._status_env.setAutoRaise(True)
        self._status_env.setCursor(Qt.PointingHandCursor)
        self._status_env.setAccessibleName(self.tr("API environment"))
        self._env_menu = QMenu(self._status_env)
        self._env_menu.aboutToShow.connect(self._populate_env_menu)
        self._status_env.setMenu(self._env_menu)
        self._status_bar.addPermanentWidget(self._status_env)
        shell.addWidget(self._status_bar)
        container.status.message_requested.connect(self._on_status_message)
        container.status.progress_requested.connect(self._on_status_progress)
        container.on_environment_changed = self._update_env_label
        self._update_env_label()
        container.status.ready(self.tr("Ready"))
        container.request_sync = self._on_sync

        self._nav.register("dashboard", lambda: DashboardPage(container))
        self._nav.register("datasets", lambda: DatasetsPage(container))
        self._nav.register("jobs", lambda: JobsPage(container))
        self._nav.register("settings", lambda: SettingsPage(container))

        container.notifications.attach_host(self)
        container.auth.session_expired.connect(self._on_session_expired)
        container.auth.login_succeeded.connect(
            lambda _user: container.status.show(
                self.tr("Signed in successfully."), 4000
            )
        )
        container.auth.logged_out.connect(self._on_auth_logged_out)
        container.project.on_project_changed(self._on_project_changed)

        if container.auth.try_restore() and container.auth.is_authenticated():
            user = container.session.user
            if user is None:
                from ...core.models import UserSession

                username = str(
                    container.settings.get("ui.last_username", "") or ""
                )
                container.session.mark_authenticated(
                    UserSession(username=username or "user")
                )
            self._show_app()
            self._refresh_header_profile()
        else:
            self._stack.setCurrentWidget(self._login)
            container.status.ready(self.tr("Sign in to continue"))

    def _on_status_message(self, message: str, timeout_ms: int) -> None:
        self._status_bar.showMessage(message, timeout_ms)
        self._status_bar.setAccessibleDescription(message or "")

    def _on_status_progress(
        self, visible: bool, percent: int, _detail: str
    ) -> None:
        if not visible:
            self._progress.hide()
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._progress.setAccessibleDescription("")
            return
        self._progress.show()
        if percent < 0:
            self._progress.setRange(0, 0)
            self._progress.setAccessibleDescription(self.tr("Busy"))
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(percent)
            self._progress.setAccessibleDescription(
                self.tr("{} percent complete").format(percent)
            )

    def _update_env_label(self) -> None:
        env = self._container.environment()
        label = env.short_label
        self._status_env.setText(label)
        self._status_env.setToolTip(
            self.tr(
                "{label}\n{url}\nClick to switch environment (signs you out)."
            ).format(label=env.label, url=env.api_base_url)
        )
        set_name(
            self._status_env,
            self.tr("API environment"),
            self.tr(
                "{label} — {url}. Click to switch environment."
            ).format(label=label, url=env.api_base_url),
        )

    def _populate_env_menu(self) -> None:
        self._env_menu.clear()
        current = self._container.environment().key
        for key in standard_environment_keys():
            meta = ENVIRONMENTS[key]
            short = {
                "development": self.tr("Development"),
                "staging": self.tr("Staging"),
                "production": self.tr("Production"),
            }.get(key, meta["label"])
            action = QAction(short, self._env_menu)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.setData(key)
            action.setToolTip(meta["api_base_url"])
            action.triggered.connect(
                lambda _checked=False, env_key=key: self._switch_environment(
                    env_key
                )
            )
            self._env_menu.addAction(action)

    def _switch_environment(self, env_key: str) -> None:
        current = self._container.environment().key
        if env_key == current:
            return
        if env_key not in ENVIRONMENTS:
            return
        short = {
            "development": self.tr("Development"),
            "staging": self.tr("Staging"),
            "production": self.tr("Production"),
        }.get(env_key, env_key)
        if not ConfirmationDialog.ask(
            self,
            self.tr("Switch environment"),
            self.tr(
                "Switch to {env}? You will be signed out and must sign in "
                "again for that environment."
            ).format(env=short),
            confirm_text=self.tr("Switch"),
            destructive=True,
        ):
            return
        self._container.settings.set("environment", env_key)
        self._container.refresh_environment()
        self._update_env_label()
        self._container.login_service.sign_out()
        self._header.set_user("")
        if self._stack.currentWidget() is not self._login:
            self._stack.setCurrentWidget(self._login)
            fade_in(self._login, duration_ms=PAGE_MS, parent=self)
            self.setWindowTitle(self.tr("TDEI"))
        self._container.status.ready(
            self.tr("Environment: {env}. Sign in to continue.").format(
                env=short
            )
        )
        self._container.notifications.info(
            self.tr("Switched to {env}. Please sign in.").format(env=short)
        )

    def _show_app(self) -> None:
        self._update_header_user()
        self._update_env_label()
        self._stack.setCurrentWidget(self._app_root)
        fade_in(self._app_root, duration_ms=PAGE_MS, parent=self)
        self._on_navigate("dashboard")
        self._container.status.show(
            self.tr("Welcome back. Choose Datasets to load OpenSidewalks data."),
            6000,
        )

    def _update_header_user(self) -> None:
        user = self._container.session.user
        label = ""
        if user is not None:
            label = self.tr("Signed in as {}").format(user.full_name)
            self._header.set_user(label)
            self._user_label_tooltip(user)
        else:
            self._header.set_user("")

    def _user_label_tooltip(self, user) -> None:
        tip = user.username
        if user.full_name and user.full_name != user.username:
            tip = "{} · {}".format(user.full_name, user.username)
        self._header.set_user_tooltip(tip)

    def _refresh_header_profile(self) -> None:
        worker = self._container.workers.submit(
            self._container.login_service.refresh_profile
        )
        worker.signals.result.connect(self._on_profile_loaded)
        worker.signals.error.connect(lambda _exc: None)

    def _on_profile_loaded(self, user) -> None:
        if user is None:
            return
        self._update_header_user()

    def _on_navigate(self, key: str) -> None:
        page = self._nav.navigate(key)
        self._pages.set_page(page)
        self._sidebar.set_active(key)
        titles = {
            "dashboard": self.tr("Dashboard"),
            "datasets": self.tr("Datasets"),
            "jobs": self.tr("Jobs"),
            "settings": self.tr("Settings"),
        }
        title = titles.get(key, key)
        self.setWindowTitle(self.tr("TDEI — {}").format(title))
        self.setAccessibleDescription(
            self.tr("Viewing {page}").format(page=title)
        )
        self._container.status.show(
            self.tr("Viewing {page}").format(page=title),
            2500,
        )

    def open_jobs(self, job_id: str = "") -> None:
        """Switch to Jobs (after sign-in) and optionally filter to a job id."""
        if not self._container.auth.is_authenticated():
            self._stack.setCurrentWidget(self._login)
            return
        self._update_header_user()
        self._update_env_label()
        self._stack.setCurrentWidget(self._app_root)
        page = self._nav.navigate("jobs")
        self._pages.set_page(page)
        self._sidebar.set_active("jobs")
        self.setWindowTitle(self.tr("TDEI — Jobs"))
        if job_id and hasattr(page, "focus_job"):
            page.focus_job(str(job_id))
        self._container.status.show(
            self.tr("Viewing Jobs"),
            2500,
        )

    def _on_sidebar_collapsed(self, collapsed: bool) -> None:
        self._container.settings.set("ui.sidebar_collapsed", collapsed)

    def _on_sync(self) -> None:
        if self._syncing:
            return
        if not self._container.auth.is_authenticated():
            return
        self._syncing = True
        self._sync_generation = self._container.project.generation
        self._header.set_sync_enabled(False)
        self._container.status.busy(
            self.tr("Syncing local cache to the map…")
        )
        loaded, pending = self._container.cache_sync.inventory_for_sync()
        self._sync_loaded_keys = loaded
        if not pending:
            if not self._sync_still_current():
                self._finish_sync()
                return
            try:
                result = self._container.cache_sync.apply_restore_jobs(
                    loaded, [], []
                )
            except Exception as exc:  # noqa: BLE001
                self._finish_sync()
                self._container.status.ready(
                    self.tr("Sync failed: {}").format(exc)
                )
                self._container.notifications.error(
                    self.tr("Could not sync local cache: {}").format(exc)
                )
                return
            self._finish_sync()
            self._refresh_pages_after_project_change()
            msg = self.tr(
                "Cache already in sync ({n} package(s) in the map)."
            ).format(n=result.skipped)
            if not loaded:
                msg = self.tr("No local packages found in the cache.")
            self._container.status.ready(msg)
            self._container.notifications.info(msg)
            return

        worker = self._container.workers.submit(
            self._container.cache_sync.prepare_pending_keys, pending
        )
        worker.signals.result.connect(self._on_sync_prepared)
        worker.signals.error.connect(self._on_sync_error)

    def _sync_still_current(self) -> bool:
        started = getattr(self, "_sync_generation", None)
        if started is None:
            return True
        return started == self._container.project.generation

    def _on_sync_prepared(self, prepared) -> None:
        if not self._sync_still_current():
            self._finish_sync()
            self._container.status.ready(
                self.tr("Sync cancelled — the QGIS project changed.")
            )
            return
        jobs, errors = prepared
        loaded_keys = getattr(self, "_sync_loaded_keys", []) or []
        try:
            result = self._container.cache_sync.apply_restore_jobs(
                loaded_keys, jobs, errors
            )
        except Exception as exc:  # noqa: BLE001
            self._finish_sync()
            if not self._sync_still_current():
                self._container.status.ready(
                    self.tr("Sync cancelled — the QGIS project changed.")
                )
                return
            self._container.status.ready(
                self.tr("Sync failed: {}").format(exc)
            )
            self._container.notifications.error(
                self.tr("Could not sync local cache: {}").format(exc)
            )
            return
        if not self._sync_still_current():
            self._finish_sync()
            self._container.status.ready(
                self.tr("Sync cancelled — the QGIS project changed.")
            )
            return
        self._finish_sync()
        self._refresh_pages_after_project_change()
        if result.restored == 0 and result.failed == 0:
            msg = self.tr(
                "Cache already in sync ({n} package(s) in the map)."
            ).format(n=result.skipped)
            self._container.status.ready(msg)
            self._container.notifications.info(msg)
            return
        msg = self.tr(
            "Restored {n} package(s) from local cache"
            " ({skipped} already loaded, {failed} failed)."
        ).format(
            n=result.restored,
            skipped=result.skipped,
            failed=result.failed,
        )
        self._container.status.ready(msg)
        if result.failed:
            self._container.notifications.warning(msg)
        else:
            self._container.notifications.success(msg)

    def _on_sync_error(self, exc) -> None:
        self._finish_sync()
        if not self._sync_still_current():
            self._container.status.ready(
                self.tr("Sync cancelled — the QGIS project changed.")
            )
            return
        self._container.status.ready(
            self.tr("Sync failed: {}").format(exc)
        )
        self._container.notifications.error(
            self.tr("Could not sync local cache: {}").format(exc)
        )

    def _finish_sync(self) -> None:
        self._syncing = False
        self._header.set_sync_enabled(True)

    def _on_project_changed(self) -> None:
        # Drop in-flight Sync UI; apply callbacks also check generation.
        if self._syncing:
            self._finish_sync()
        try:
            self._refresh_pages_after_project_change()
        except Exception:  # noqa: BLE001
            pass
        self._container.status.ready(
            self.tr(
                "QGIS project changed. Mapped layers follow the open project. "
                "Use Sync to restore from local cache if needed."
            )
        )

    def _refresh_pages_after_project_change(self) -> None:
        for key in ("datasets", "jobs"):
            page = self._nav.page_if_loaded(key)
            if page is None:
                continue
            if hasattr(page, "on_project_layers_changed"):
                try:
                    page.on_project_layers_changed()
                except Exception:  # noqa: BLE001
                    pass

    def _on_auth_logged_out(self) -> None:
        try:
            self._container.project_groups.clear_session_state()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._container.datasets.invalidate_cache()
        except Exception:  # noqa: BLE001
            pass
        self._container.status.ready(self.tr("Signed out"))

    def _minimize_window(self) -> None:
        """Hide the sticky panel (map chrome TDEI icon restores it)."""
        self.hide()
        sync = getattr(self._container, "sync_map_chrome", None)
        if callable(sync):
            try:
                sync()
            except Exception:  # noqa: BLE001
                pass

    def position_on_canvas(self, canvas) -> None:
        """Attach as a sticky left overlay on the map canvas viewport."""
        if canvas is None:
            return
        host = canvas
        try:
            viewport = canvas.viewport()
            if viewport is not None:
                host = viewport
        except Exception:  # noqa: BLE001
            host = canvas
        self._map_canvas_ref = canvas
        if self._canvas_host is not host:
            if self._canvas_host is not None:
                try:
                    self._canvas_host.removeEventFilter(self)
                except Exception:  # noqa: BLE001
                    pass
            self._canvas_host = host
            if self.parent() is not host:
                self.setParent(host)
            host.installEventFilter(self)
        self._reposition()
        try:
            # Always present the sticky panel with collapsed navigation.
            if hasattr(self, "_sidebar") and self._sidebar is not None:
                self._sidebar.set_collapsed(True)
        except Exception:  # noqa: BLE001
            pass
        self.raise_()
        self.show()

    def detach_from_canvas(self) -> None:
        if self._canvas_host is not None:
            try:
                self._canvas_host.removeEventFilter(self)
            except Exception:  # noqa: BLE001
                pass
            self._canvas_host = None
        self._map_canvas_ref = None

    def _reposition(self) -> None:
        host = self._canvas_host or self.parentWidget()
        if host is None:
            return
        try:
            dimensions.refresh_ui_scale(self)
        except Exception:  # noqa: BLE001
            pass
        margin = dimensions.s(16)
        width = dimensions.overlay_panel_width(host.width())
        height = dimensions.overlay_panel_height(host.height())
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setFixedWidth(width)
        self.setFixedHeight(height)
        self.move(margin, margin)
        # Let pages/tables reflow to the new width.
        try:
            self.updateGeometry()
            if self._stack is not None:
                self._stack.updateGeometry()
        except Exception:  # noqa: BLE001
            pass

    def enterEvent(self, event) -> None:
        pointer_over_overlay(
            self, entering=True, map_canvas=self._map_canvas_ref
        )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        pointer_over_overlay(
            self, entering=False, map_canvas=self._map_canvas_ref
        )
        super().leaveEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._canvas_host and event is not None:
            etype = event.type()
            if etype in (QEvent.Resize, QEvent.Show, QEvent.Move):
                self._reposition()
                self.raise_()
            elif etype == QEvent.Wheel and self.isVisible():
                try:
                    pos = event.pos()
                except Exception:  # noqa: BLE001
                    pos = None
                if pos is not None and self.geometry().contains(pos):
                    local = self.mapFromParent(pos)
                    child = self.childAt(local)
                    target = child if child is not None else self
                    try:
                        from qgis.PyQt.QtWidgets import QApplication

                        QApplication.sendEvent(target, event)
                    except Exception:  # noqa: BLE001
                        pass
                    return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _overlay_chrome() -> str:
        """Glass border so the sticky panel reads as map chrome."""
        return """
            QFrame#TdeiMainWindow {{
                background-color: {glass};
                border: 1px solid {border};
                border-left: 4px solid {accent};
                border-radius: {radius}px;
            }}
        """.format(
            glass=colors.GLASS_SURFACE,
            border=colors.GLASS_BORDER_EDGE,
            accent=colors.PRIMARY,
            radius=dimensions.RADIUS_LG,
        )

    def _logout(self) -> None:
        if not ConfirmationDialog.ask(
            self,
            self.tr("Logout"),
            self.tr("Sign out of TDEI?"),
            confirm_text=self.tr("Logout"),
            destructive=True,
        ):
            return
        self._container.login_service.sign_out()
        self._header.set_user("")
        self._stack.setCurrentWidget(self._login)
        fade_in(self._login, duration_ms=PAGE_MS, parent=self)
        self.setWindowTitle(self.tr("TDEI"))
        self._container.status.ready(self.tr("Signed out"))
        self._container.notifications.info(self.tr("Signed out."))

    def _on_session_expired(self) -> None:
        self._header.set_user("")
        self._stack.setCurrentWidget(self._login)
        fade_in(self._login, duration_ms=PAGE_MS, parent=self)
        self.setWindowTitle(self.tr("TDEI"))
        self._container.status.ready(
            self.tr("Your session has expired. Please sign in again.")
        )
        self._container.notifications.warning(
            self.tr("Your session has expired. Please sign in again.")
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_ui_scale()
        sync = getattr(self._container, "sync_map_chrome", None)
        if callable(sync):
            try:
                sync()
            except Exception:  # noqa: BLE001
                pass

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        sync = getattr(self._container, "sync_map_chrome", None)
        if callable(sync):
            try:
                sync()
            except Exception:  # noqa: BLE001
                pass

    def _apply_ui_scale(self) -> None:
        dimensions.refresh_ui_scale(self)
        self.setStyleSheet(
            theme.application_stylesheet() + self._overlay_chrome()
        )
        if hasattr(self, "_login"):
            try:
                self._login.setStyleSheet(theme.login_stylesheet())
            except Exception:
                pass
        if hasattr(self, "_sidebar"):
            self._sidebar.apply_metrics()
