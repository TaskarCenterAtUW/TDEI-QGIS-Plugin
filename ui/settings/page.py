# -*- coding: utf-8 -*-
"""Plugin settings — sectioned layout with clear action hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Tuple

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyleFactory,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...config.defaults import ENVIRONMENTS
from ...config.environment import (
    get_environment_urls,
    set_environment_urls,
    standard_environment_keys,
)
from ...qgis.basemaps import BASEMAP_PROVIDERS, DEFAULT_BASEMAP
from ..a11y import set_name, set_page
from ..components import (
    DangerButton,
    PrimaryButton,
    SecondaryButton,
    SegmentTabs,
)
from ..dialogs.confirmation_dialog import ConfirmationDialog
from ..styles import colors, dimensions, typography

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer


class SettingsPage(QWidget):
    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._env_fields: Dict[str, Tuple[QLineEdit, QLineEdit]] = {}
        self._build()

    def _build(self) -> None:
        set_page(
            self,
            self.tr("Settings"),
            self.tr("Configure API environment, basemap, and preferences."),
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel(self.tr("Settings"))
        title.setObjectName("PageTitle")
        title.setFocusPolicy(Qt.NoFocus)
        subtitle = QLabel(
            self.tr("Configure API environment, basemap, and preferences.")
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFocusPolicy(Qt.NoFocus)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        root.addWidget(self._section_connection())
        root.addWidget(self._section_map())
        root.addWidget(self._section_preferences())
        root.addWidget(self._section_session())
        root.addStretch(1)

        set_name(
            self._timeout,
            self.tr("Request timeout"),
            self.tr("HTTP request timeout in seconds"),
        )
        set_name(
            self._basemap,
            self.tr("Basemap"),
            self.tr(
                "Basemap shown under TDEI layers when you view a dataset in QGIS."
            ),
        )

    def _section_connection(self) -> QFrame:
        card, body = self._card(
            self.tr("Environments"),
            self.tr(
                "API gateway and user-management URLs per environment. "
                "Switch the active environment from the status bar "
                "(switching signs you out)."
            ),
        )

        items = [
            (key, self._tab_label(key)) for key in standard_environment_keys()
        ]
        tabs = SegmentTabs(items)
        tabs.setObjectName("SettingsEnvTabs")
        tabs.setAccessibleName(self.tr("Environment"))
        tabs.setAccessibleDescription(
            self.tr("Choose which environment URLs to edit.")
        )
        for btn in tabs.findChildren(QToolButton):
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._env_tabs = tabs

        stack = QStackedWidget()
        stack.setObjectName("SettingsEnvStack")
        self._env_stack = stack
        active = str(
            self._container.settings.get("environment", "development") or ""
        )
        key_to_index = {}
        for index, key in enumerate(standard_environment_keys()):
            meta = ENVIRONMENTS[key]
            page = QFrame()
            page.setObjectName("SettingsEnvPanel")
            page.setAttribute(Qt.WA_StyledBackground, True)
            api_url, um_url = get_environment_urls(self._container.settings, key)

            api_edit = QLineEdit(api_url)
            self._style_input(api_edit)
            api_edit.setObjectName("SettingsEnvUrl")
            api_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            api_edit.setMinimumWidth(0)
            api_edit.setPlaceholderText(meta["api_base_url"])
            set_name(
                api_edit,
                self.tr("{} API gateway").format(meta["label"]),
                self.tr("Gateway API base URL for {}.").format(meta["label"]),
            )

            um_edit = QLineEdit(um_url)
            self._style_input(um_edit)
            um_edit.setObjectName("SettingsEnvUrl")
            um_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            um_edit.setMinimumWidth(0)
            um_edit.setPlaceholderText(meta["user_management_api_base_url"])
            set_name(
                um_edit,
                self.tr("{} user-management API").format(meta["label"]),
                self.tr(
                    "User-management API base URL for {}."
                ).format(meta["label"]),
            )

            form = self._form(expanding_fields=True)
            form.addRow(self.tr("API gateway URL"), api_edit)
            form.addRow(self.tr("User-management URL"), um_edit)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(12, 12, 12, 12)
            page_layout.addLayout(form)
            page_layout.addStretch(1)
            stack.addWidget(page)
            key_to_index[key] = index
            self._env_fields[key] = (api_edit, um_edit)

        def _on_env_tab(key: str) -> None:
            stack.setCurrentIndex(key_to_index.get(key, 0))

        tabs.changed.connect(_on_env_tab)
        if active in key_to_index:
            tabs.set_current(active)
            stack.setCurrentIndex(key_to_index[active])
        else:
            stack.setCurrentIndex(0)

        body.addWidget(tabs, 0, Qt.AlignLeft)
        body.addWidget(stack)

        self._timeout = QSpinBox()
        self._style_input(self._timeout)
        self._timeout.setRange(5, 300)
        self._timeout.setSuffix(self.tr(" s"))
        self._timeout.setFixedWidth(120)
        self._timeout.setValue(
            self._container.settings.int("request_timeout_seconds", 30)
        )
        self._timeout.setToolTip(self.tr("HTTP request timeout in seconds"))

        timeout_form = self._form()
        timeout_row = QWidget()
        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.addWidget(self._timeout)
        timeout_layout.addStretch(1)
        timeout_form.addRow(self.tr("Request timeout"), timeout_row)
        body.addLayout(timeout_form)

        hint = QLabel(
            self.tr(
                "Downloads and local cache are stored separately per environment."
            )
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        body.addWidget(hint)
        return card

    @staticmethod
    def _tab_label(key: str) -> str:
        return {
            "development": "Development",
            "staging": "Staging",
            "production": "Production",
        }.get(key, key)

    def _section_map(self) -> QFrame:
        card, body = self._card(
            self.tr("Map"),
            self.tr(
                "Basemap under TDEI layers. After a crash, use Sync in the "
                "header to restore packages from local cache. Saving the "
                "QGIS project keeps layers without needing Sync."
            ),
        )
        form = self._form()

        self._basemap = QComboBox()
        self._style_input(self._basemap)
        self._basemap.setMinimumWidth(280)
        for key, meta in BASEMAP_PROVIDERS.items():
            self._basemap.addItem(meta["label"], key)
        basemap_key = str(
            self._container.settings.get("basemap.provider", DEFAULT_BASEMAP)
            or DEFAULT_BASEMAP
        )
        basemap_index = self._basemap.findData(basemap_key)
        if basemap_index < 0:
            basemap_index = self._basemap.findData(DEFAULT_BASEMAP)
        if basemap_index >= 0:
            self._basemap.setCurrentIndex(basemap_index)

        form.addRow(self.tr("Basemap"), self._basemap)

        hint = QLabel(
            self.tr(
                "Tiles stream online (no offline download). "
                "OpenStreetMap is recommended. Google options need network "
                "access and follow Google Maps terms of use."
            )
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        body.addLayout(form)
        body.addWidget(hint)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 8, 0, 0)
        actions.setSpacing(10)
        apply_btn = SecondaryButton(self.tr("Apply basemap now"))
        apply_btn.setMaximumWidth(200)
        apply_btn.setToolTip(
            self.tr("Update the basemap in the current QGIS project immediately")
        )
        apply_btn.setAccessibleDescription(
            self.tr("Update the basemap in the current QGIS project immediately")
        )
        apply_btn.clicked.connect(self._apply_basemap)
        actions.addWidget(apply_btn)
        actions.addStretch(1)
        body.addLayout(actions)
        return card

    def _section_preferences(self) -> QFrame:
        card, body = self._card(
            self.tr("Preferences"),
            self.tr("Optional plugin behavior."),
        )
        self._toasts = QCheckBox(self.tr("Show toast notifications"))
        self._style_input(self._toasts)
        self._toasts.setChecked(
            self._container.settings.bool("ui.show_toasts", True)
        )
        self._motion = QCheckBox(self.tr("Animate page and sidebar transitions"))
        self._style_input(self._motion)
        self._motion.setChecked(
            self._container.settings.bool("ui.motion", True)
        )
        self._motion.setToolTip(
            self.tr(
                "Short fades and sidebar width animation. "
                "Turn off for reduced motion, or set TDEI_REDUCE_MOTION=1."
            )
        )
        self._jobs = QCheckBox(self.tr("Enable TDEI jobs from the layer menu"))
        self._style_input(self._jobs)
        self._jobs.setChecked(self._container.settings.feature_enabled("jobs"))

        prefs = QVBoxLayout()
        prefs.setContentsMargins(0, 0, 0, 0)
        prefs.setSpacing(6)
        prefs.addWidget(self._toasts)
        prefs.addWidget(self._motion)
        prefs.addWidget(self._jobs)
        body.addLayout(prefs)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setSpacing(10)
        save = PrimaryButton(self.tr("Save settings"))
        save.setMinimumWidth(140)
        save.setMaximumWidth(200)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        footer.addStretch(1)
        body.addLayout(footer)
        return card

    def _section_session(self) -> QFrame:
        card, body = self._card(
            self.tr("Session"),
            self.tr("Sign-out and clear stored authentication on this machine."),
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        clear = DangerButton(self.tr("Clear saved session"))
        clear.setMinimumWidth(160)
        clear.setMaximumWidth(220)
        clear.setAccessibleDescription(
            self.tr("Removes local tokens and returns you to the login screen.")
        )
        clear.clicked.connect(self._clear_session)
        note = QLabel(
            self.tr("Removes local tokens and returns you to the login screen.")
        )
        note.setObjectName("FieldHint")
        note.setWordWrap(True)
        row.addWidget(clear, 0, Qt.AlignVCenter)
        row.addWidget(note, 1)
        body.addLayout(row)
        return card

    def _card(self, title: str, description: str):
        card = QFrame()
        card.setObjectName("SettingsCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("SettingsSectionTitle")
        heading.setFocusPolicy(Qt.NoFocus)
        heading.setAccessibleName(title)
        desc = QLabel(description)
        desc.setObjectName("FieldHint")
        desc.setWordWrap(True)
        desc.setFocusPolicy(Qt.NoFocus)
        desc.setAccessibleDescription(description)
        head.addWidget(heading)
        head.addWidget(desc)
        outer.addLayout(head)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        outer.addLayout(body)

        card.setAccessibleName(title)
        card.setAccessibleDescription(description)
        card.setStyleSheet(self._card_stylesheet())
        return card, body

    @staticmethod
    def _style_input(widget) -> None:
        """Prefer Fusion so stylesheets apply consistently on macOS."""
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            widget.setStyle(fusion)
        widget.setAttribute(Qt.WA_MacShowFocusRect, False)

    @staticmethod
    def _form(expanding_fields: bool = False) -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if expanding_fields:
            form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        else:
            form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        return form

    @staticmethod
    def _card_stylesheet() -> str:
        return """
            QFrame#SettingsCard {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QLabel#SettingsSectionTitle {{
                color: {text};
                font-size: {fs_lg}px;
                font-weight: {fw_semi};
            }}
            QLabel#FieldHint {{
                color: {text_secondary};
                font-size: {fs_sm}px;
            }}
            QCheckBox {{
                color: {text};
                font-size: {fs_md}px;
                spacing: 8px;
            }}
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
                border: 2px solid {focus};
            }}
        """.format(
            surface=colors.SURFACE,
            border=colors.BORDER,
            radius=dimensions.RADIUS_LG,
            text=colors.TEXT,
            text_secondary=colors.TEXT_SECONDARY,
            focus=colors.FOCUS,
            fs_sm=typography.FONT_SIZE_SM,
            fs_md=typography.FONT_SIZE_MD,
            fs_lg=typography.FONT_SIZE_LG,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
        )

    def _save(self) -> None:
        for key, (api_edit, um_edit) in self._env_fields.items():
            set_environment_urls(
                self._container.settings,
                key,
                api_edit.text(),
                um_edit.text(),
            )
        self._container.settings.set(
            "request_timeout_seconds", self._timeout.value()
        )
        self._container.settings.set(
            "basemap.provider", self._basemap.currentData()
        )
        self._container.settings.set("ui.show_toasts", self._toasts.isChecked())
        self._container.settings.set("ui.motion", self._motion.isChecked())
        self._container.settings.set("feature.jobs", self._jobs.isChecked())
        self._container.refresh_environment()
        try:
            self._container.basemaps.ensure_basemap()
        except Exception:  # noqa: BLE001
            pass
        self._container.notifications.success(self.tr("Settings saved."))
        self._container.status.show(self.tr("Settings saved."), 4000)

    def _apply_basemap(self) -> None:
        self._container.settings.set(
            "basemap.provider", self._basemap.currentData()
        )
        try:
            layer = self._container.basemaps.ensure_basemap()
        except Exception as exc:  # noqa: BLE001
            self._container.notifications.error(
                self.tr("Could not add basemap: {}").format(exc)
            )
            return
        if layer is None and self._basemap.currentData() == "none":
            self._container.notifications.info(self.tr("Basemap removed."))
            self._container.status.show(self.tr("Basemap removed."), 4000)
            return
        if layer is None:
            self._container.notifications.error(
                self.tr("Could not create the basemap layer.")
            )
            return
        self._container.notifications.success(
            self.tr("Basemap ready: {}").format(layer.name())
        )
        self._container.status.show(
            self.tr("Basemap: {}").format(layer.name()), 4000
        )

    def _clear_session(self) -> None:
        if not ConfirmationDialog.ask(
            self,
            self.tr("Clear session"),
            self.tr("Clear stored authentication tokens and sign out?"),
            confirm_text=self.tr("Clear"),
            destructive=True,
        ):
            return
        self._container.login_service.sign_out()
        self._container.notifications.info(self.tr("Session cleared."))
        self._container.status.ready(self.tr("Session cleared"))
