# -*- coding: utf-8 -*-
"""Jobs history page — list gateway jobs and load downloadable outputs."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyleFactory,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.exceptions import AuthenticationError, SessionExpiredError, TdeiError
from ...core.models import (
    DatasetLocalState,
    JobLoadResult,
    JobRecord,
    MappedItem,
)
from ...core.utils.timefmt import format_duration
from ...features.mapped_tags.logic import item_matches_query
from ..a11y import label_for, set_name, set_page
from ..busy import busy_action
from ..components import (
    CheckHeaderView,
    EmptyState,
    ErrorState,
    IconButton,
    MappedFilterBar,
    SegmentTabs,
    TagEditor,
    centered_checkbox,
    outline_action_button,
    status_badge,
)
from ..dialogs.confirmation_dialog import ConfirmationDialog
from ..styles import colors

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer

_PAGE_SIZE = 10
_SCROLL_LOAD_RATIO = 0.95
_MAPPED_CHECK_WIDTH = 44
_MAPPED_ACTIONS_WIDTH = 214
_ACTION_BTN_WIDTH = 90
_DELETE_BTN_WIDTH = 98
_BULK_DELETE_MIN_WIDTH = 168


class JobsPage(QWidget):
    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._loading_ids: Set[str] = set()
        self._list_loading = False
        self._append_next = False
        self._page = 1
        self._has_more = True
        self._jobs: List[JobRecord] = []
        self._mapped: List[MappedItem] = []
        self._groups_ready = False
        self._project_group_id = ""
        self._job_id_query = ""
        self._build()

    def _build(self) -> None:
        set_page(
            self,
            self.tr("Jobs"),
            self.tr("Track TDEI jobs and open downloadable results."),
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(self.tr("Jobs"))
        title.setObjectName("PageTitle")
        title.setFocusPolicy(Qt.NoFocus)
        self._tabs = SegmentTabs(
            [("list", self.tr("List")), ("mapped", self.tr("Mapped"))]
        )
        self._tabs.changed.connect(self._on_tab_changed)
        self._refresh = IconButton(
            "refresh.svg", self.tr("Refresh")
        )
        self._refresh.setAccessibleDescription(
            self.tr("Reload the jobs list or mapped outputs.")
        )
        self._refresh.clicked.connect(self._on_refresh)
        header.addWidget(title, 0, Qt.AlignVCenter)
        header.addWidget(self._tabs, 0, Qt.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._refresh, 0, Qt.AlignVCenter)
        layout.addLayout(header)

        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._build_list_panel())
        self._mode_stack.addWidget(self._build_mapped_panel())
        layout.addWidget(self._mode_stack, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._reload_from_filters)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_filters())

        self._count = QLabel("")
        self._count.setObjectName("PageSubtitle")
        self._count.setFocusPolicy(Qt.NoFocus)
        self._count.setAccessibleName(self.tr("Job count"))
        layout.addWidget(self._count)

        self._stack = QStackedWidget()
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            [
                self.tr("Job type"),
                self.tr("Status"),
                self.tr("Actions"),
            ]
        )
        set_name(
            self._table,
            self.tr("Jobs table"),
            self.tr("List of TDEI gateway jobs."),
        )
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(1, 120)
        self._table.setColumnWidth(2, 152)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setFocusPolicy(Qt.StrongFocus)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.verticalHeader().setDefaultSectionSize(56)
        self._table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)

        self._empty = EmptyState(
            self.tr("No jobs found"),
            self.tr("No jobs for this project group yet."),
            self.tr("Refresh"),
        )
        self._empty.retry.connect(self.reload)
        self._error = ErrorState(
            self.tr("Unable to load jobs"),
            self.tr("Please try again."),
            self.tr("Retry"),
        )
        self._error.retry.connect(self.reload)
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._error)
        layout.addWidget(self._stack, 1)
        return panel

    def _build_mapped_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar_host = QWidget()
        toolbar_host.setObjectName("MappedToolbar")
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 4, 0, 4)
        toolbar.setSpacing(12)
        self._mapped_count = QLabel("")
        self._mapped_count.setObjectName("PageSubtitle")
        self._mapped_count.setFocusPolicy(Qt.NoFocus)
        self._mapped_count.setAccessibleName(self.tr("Mapped job count"))
        self._mapped_search = MappedFilterBar()
        self._mapped_search.query_changed.connect(self._on_mapped_query)
        self._mapped_bulk_delete = outline_action_button(
            self.tr("Delete selected"),
            color=colors.ERROR,
            hover_bg="#fdecea",
            width=_BULK_DELETE_MIN_WIDTH,
            height=28,
            expand=True,
            icon_name="action_delete.svg",
        )
        self._mapped_bulk_delete.setAccessibleDescription(
            self.tr("Remove selected mapped job outputs from QGIS.")
        )
        self._mapped_bulk_delete.setVisible(False)
        self._mapped_bulk_delete.clicked.connect(self._delete_mapped_selected)
        toolbar.addWidget(self._mapped_count, 0, Qt.AlignVCenter)
        toolbar.addWidget(self._mapped_search, 1, Qt.AlignVCenter)
        toolbar.addWidget(self._mapped_bulk_delete, 0, Qt.AlignVCenter)
        layout.addWidget(toolbar_host)

        self._mapped_stack = QStackedWidget()
        self._mapped_stack.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._mapped_table = QTableWidget(0, 3)
        self._mapped_header = CheckHeaderView(self._mapped_table)
        self._mapped_table.setHorizontalHeader(self._mapped_header)
        self._mapped_header.check_toggled.connect(self._on_mapped_select_all)
        self._mapped_table.setHorizontalHeaderLabels(
            ["", self.tr("Name"), self.tr("Actions")]
        )
        self._mapped_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self._mapped_header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._mapped_header.setSectionResizeMode(2, QHeaderView.Fixed)
        self._mapped_table.setColumnWidth(0, _MAPPED_CHECK_WIDTH)
        self._mapped_table.setColumnWidth(2, _MAPPED_ACTIONS_WIDTH)
        self._mapped_table.verticalHeader().setVisible(False)
        self._mapped_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._mapped_table.setFocusPolicy(Qt.StrongFocus)
        set_name(
            self._mapped_table,
            self.tr("Mapped jobs table"),
            self.tr("Job outputs currently loaded in the QGIS map."),
        )
        self._mapped_table.setAlternatingRowColors(True)
        self._mapped_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mapped_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mapped_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._mapped_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._mapped_table.verticalHeader().setDefaultSectionSize(80)

        self._mapped_empty = EmptyState(
            self.tr("Nothing mapped yet"),
            self.tr(
                "Add a job output from the List tab, or use Sync "
                "to restore packages from local cache after a crash."
            ),
            self.tr("Refresh"),
        )
        self._mapped_empty_action = "refresh"
        self._mapped_empty.retry.connect(self._on_mapped_empty_action)
        self._mapped_stack.addWidget(self._mapped_table)
        self._mapped_stack.addWidget(self._mapped_empty)
        layout.addWidget(self._mapped_stack, 1)
        return panel

    def _build_filters(self) -> QWidget:
        host = QWidget()
        host.setObjectName("DatasetFilters")
        host.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(host)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        id_col, self._job_id_edit, self._job_id_clear = self._filter_field(
            self.tr("Job ID"),
            self.tr("Search Job ID"),
        )
        self._job_id_edit.textChanged.connect(self._on_job_id_typed)
        self._job_id_clear.clicked.connect(self._clear_job_id)

        status_col = QVBoxLayout()
        status_col.setSpacing(2)
        status_label = QLabel(self.tr("Job status"))
        status_label.setObjectName("FilterFieldLabel")
        self._status = QComboBox()
        self._style_input(self._status)
        self._status.setMinimumWidth(160)
        self._status.setFocusPolicy(Qt.StrongFocus)
        for value, label in (
            ("", self.tr("All")),
            ("COMPLETED", self.tr("Completed")),
            ("FAILED", self.tr("Failed")),
            ("IN-PROGRESS", self.tr("In progress")),
            ("ABANDONED", self.tr("Abandoned")),
        ):
            self._status.addItem(label, value)
        self._status.currentIndexChanged.connect(self._on_status_changed)
        label_for(
            status_label,
            self._status,
            name=self.tr("Job status"),
            description=self.tr("Filter jobs by status."),
        )
        status_col.addWidget(status_label)
        status_col.addWidget(self._status)

        row.addLayout(id_col, 1)
        row.addLayout(status_col, 0)
        row.addStretch(0)
        return host

    def _filter_field(self, label: str, placeholder: str):
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel(label)
        title.setObjectName("FilterFieldLabel")
        clear = QPushButton(self.tr("Clear"))
        clear.setObjectName("FilterClear")
        clear.setCursor(Qt.PointingHandCursor)
        clear.setFlat(True)
        clear.setEnabled(False)
        clear.setFocusPolicy(Qt.StrongFocus)
        clear.setAccessibleName(self.tr("Clear {}").format(label))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(clear)
        edit = QLineEdit()
        self._style_input(edit)
        edit.setPlaceholderText(placeholder)
        edit.setFocusPolicy(Qt.StrongFocus)
        label_for(
            title,
            edit,
            name=label,
            description=placeholder,
        )
        col.addLayout(head)
        col.addWidget(edit)
        return col, edit, clear

    @staticmethod
    def _style_input(widget) -> None:
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            widget.setStyle(fusion)
        widget.setAttribute(Qt.WA_MacShowFocusRect, False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._groups_ready:
            self._load_project_groups()
        else:
            if self._tabs.current == "mapped":
                self._reload_mapped()
            else:
                self.reload()

    def _on_tab_changed(self, key: str) -> None:
        if key == "mapped":
            self._mode_stack.setCurrentIndex(1)
            self._reload_mapped()
        else:
            self._mode_stack.setCurrentIndex(0)
            if self._groups_ready and not self._jobs:
                self.reload()
            elif self._groups_ready:
                QTimer.singleShot(0, self._maybe_autoload_more)

    def _on_refresh(self) -> None:
        if self._tabs.current == "mapped":
            self._reload_mapped()
        else:
            self.reload()

    def focus_job(self, job_id: str) -> None:
        """Show List tab filtered to a specific job id (e.g. after layer submit)."""
        job_id = str(job_id or "").strip()
        self._tabs.set_current("list")
        self._mode_stack.setCurrentIndex(0)
        self._job_id_edit.blockSignals(True)
        self._job_id_edit.setText(job_id)
        self._job_id_edit.blockSignals(False)
        self._job_id_query = job_id
        self._job_id_clear.setEnabled(bool(job_id))
        if self._groups_ready:
            self.reload()
        else:
            self._load_project_groups()

    def _on_mapped_empty_action(self) -> None:
        if getattr(self, "_mapped_empty_action", "refresh") == "sync":
            request = getattr(self._container, "request_sync", None)
            if callable(request):
                request()
                return
        self._reload_mapped()

    def _reload_mapped(self) -> None:
        items = self._container.jobs.list_mapped()
        names = {job.map_key: job.display_type for job in self._jobs}
        for item in items:
            if item.key in names:
                item.display_name = names[item.key]
        self._container.tags.attach_to_items(items)
        self._mapped = items
        self._mapped_header.set_checked(False)
        self._mapped_header.set_check_enabled(bool(items))
        self._mapped_search.set_suggestions(self._container.tags.catalog())
        if not items:
            from ...core.models import JOB_MAP_PREFIX

            cached = sum(
                1
                for key in self._container.layers.list_cached_package_keys()
                if key.startswith(JOB_MAP_PREFIX)
            )
            if cached:
                self._mapped_empty_action = "sync"
                self._mapped_empty.set_action_text(self.tr("Sync"))
                self._mapped_empty.set_message(
                    self.tr("Nothing mapped yet"),
                    self.tr(
                        "{n} local job package(s) found on disk. "
                        "Sync to restore them into this project, "
                        "or Download from the List tab. "
                        "Save the QGIS project to keep layers after a crash."
                    ).format(n=cached),
                )
            else:
                self._mapped_empty_action = "refresh"
                self._mapped_empty.set_action_text(self.tr("Refresh"))
                self._mapped_empty.set_message(
                    self.tr("Nothing mapped yet"),
                    self.tr(
                        "Add a job output from the List tab, or Sync "
                        "to restore packages from local cache."
                    ),
                )
            self._mapped_stack.setCurrentWidget(self._mapped_empty)
            self._mapped_count.setText(self.tr("0 mapped"))
            self._mapped_bulk_delete.setVisible(False)
            self._set_status(self.tr("No job outputs currently in the map."))
            return
        self._mapped_stack.setCurrentWidget(self._mapped_table)
        self._mapped_table.setRowCount(0)
        self._mapped_table.setRowCount(len(items))
        for row, item in enumerate(items):
            host, checkbox = centered_checkbox(
                tooltip=self.tr("Select {}").format(
                    item.display_name or item.key
                )
            )
            checkbox.setProperty("mapped_key", item.key)
            checkbox.stateChanged.connect(self._on_mapped_row_check)
            self._mapped_table.setCellWidget(row, 0, host)
            self._mapped_table.setCellWidget(
                row, 1, self._mapped_name_cell(item)
            )
            self._mapped_table.setCellWidget(
                row, 2, self._mapped_action_cell(item)
            )
        self._apply_mapped_filter()
        self._sync_mapped_bulk_delete()
        self._set_status(
            self.tr("Managing {n} mapped job output(s).").format(n=len(items))
        )

    def on_project_layers_changed(self) -> None:
        """Called after Sync or when the QGIS project is opened/cleared."""
        self._loading_ids.clear()
        try:
            if self._tabs.current == "mapped":
                self._reload_mapped()
            if self._jobs:
                self._fill_table(self._jobs)
        except Exception:  # noqa: BLE001 — never crash QGIS on project switch
            pass

    def _on_mapped_query(self, _text: str) -> None:
        self._apply_mapped_filter()

    def _apply_mapped_filter(self) -> None:
        query = self._mapped_search.query() if hasattr(self, "_mapped_search") else ""
        visible = 0
        for row, item in enumerate(self._mapped):
            match = item_matches_query(item, query)
            self._mapped_table.setRowHidden(row, not match)
            if match:
                visible += 1
        total = len(self._mapped)
        if query and total:
            self._mapped_count.setText(
                self.tr("{shown} of {n} mapped").format(shown=visible, n=total)
            )
        else:
            self._mapped_count.setText(
                self.tr("{n} mapped").format(n=total)
            )
        if total and visible == 0:
            self._set_status(self.tr("No mapped job outputs match this search."))
        self._sync_mapped_bulk_delete()

    def _refresh_mapped_catalog(self) -> None:
        catalog = self._container.tags.catalog()
        self._mapped_search.set_suggestions(catalog)
        for row in range(self._mapped_table.rowCount()):
            host = self._mapped_table.cellWidget(row, 1)
            if host is None:
                continue
            editors = host.findChildren(TagEditor)
            if editors:
                editors[0].set_catalog(catalog)

    def _on_mapped_tags_changed(self, key: str, tags: List[str]) -> None:
        saved = self._container.tags.set_tags(key, tags)
        for item in self._mapped:
            if item.key == key:
                item.tags = saved
                break
        self._refresh_mapped_catalog()
        self._apply_mapped_filter()

    def _mapped_name_cell(self, item: MappedItem) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(12, 8, 8, 8)
        col.setSpacing(2)
        name = QLabel(item.display_name or item.key)
        name.setObjectName("DatasetName")
        name.setWordWrap(False)
        name.setToolTip(item.display_name or item.key)
        name.setStyleSheet(
            "QLabel#DatasetName {{ color: {text}; font-size: 13px; "
            "font-weight: 600; }}".format(text=colors.TEXT)
        )
        sub = QLabel(item.subtitle)
        sub.setObjectName("DatasetId")
        sub.setWordWrap(False)
        sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sub.setToolTip(item.subtitle)
        sub.setStyleSheet(
            "QLabel#DatasetId {{ color: {muted}; font-size: 11px; "
            "font-family: Menlo, Monaco, Consolas, monospace; }}".format(
                muted=colors.TEXT_MUTED
            )
        )
        editor = TagEditor()
        editor.set_tags(item.tags or [])
        editor.set_catalog(self._container.tags.catalog())
        editor.tags_changed.connect(
            lambda tags, key=item.key: self._on_mapped_tags_changed(key, tags)
        )
        editor.tag_clicked.connect(
            lambda tag: self._mapped_search.set_query("#{}".format(tag))
        )
        col.addWidget(name)
        col.addWidget(sub)
        col.addWidget(editor)
        return host

    def _mapped_action_cell(self, item: MappedItem) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(8, 4, 12, 4)
        row.setSpacing(6)
        row.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        zoom = outline_action_button(
            self.tr("Zoom"),
            color=colors.PRIMARY,
            hover_bg=colors.SURFACE_ALT,
            width=_ACTION_BTN_WIDTH,
            icon_name="action_zoom.svg",
        )
        zoom.setAccessibleName(
            self.tr("Zoom to {}").format(item.display_name or item.key)
        )
        zoom.clicked.connect(partial(self._zoom_mapped, item.key))
        delete = outline_action_button(
            self.tr("Delete"),
            color=colors.ERROR,
            hover_bg="#fdecea",
            width=_DELETE_BTN_WIDTH,
            icon_name="action_delete.svg",
        )
        delete.setAccessibleName(
            self.tr("Delete {}").format(item.display_name or item.key)
        )
        delete.clicked.connect(partial(self._delete_mapped, item.key))
        row.addWidget(zoom)
        row.addWidget(delete)
        return host

    def _selected_mapped_keys(self) -> List[str]:
        keys: List[str] = []
        for row in range(self._mapped_table.rowCount()):
            if self._mapped_table.isRowHidden(row):
                continue
            checkbox = self._mapped_row_checkbox(row)
            if checkbox is None or not checkbox.isChecked():
                continue
            key = checkbox.property("mapped_key")
            if key:
                keys.append(str(key))
        return keys

    def _mapped_row_checkbox(self, row: int):
        host = self._mapped_table.cellWidget(row, 0)
        if host is None:
            return None
        boxes = host.findChildren(QCheckBox)
        return boxes[0] if boxes else None

    def _sync_mapped_bulk_delete(self) -> None:
        selected = self._selected_mapped_keys()
        count = len(selected)
        if count:
            self._mapped_bulk_delete.setText(
                self.tr("Delete selected ({n})").format(n=count)
            )
            self._mapped_bulk_delete.setVisible(True)
        else:
            self._mapped_bulk_delete.setVisible(False)
            self._mapped_bulk_delete.setText(self.tr("Delete selected"))
        total = sum(
            1
            for row in range(self._mapped_table.rowCount())
            if not self._mapped_table.isRowHidden(row)
        )
        self._mapped_header.set_checked(total > 0 and count == total)

    def _on_mapped_row_check(self, _state: int) -> None:
        self._sync_mapped_bulk_delete()

    def _on_mapped_select_all(self, checked: bool) -> None:
        for row in range(self._mapped_table.rowCount()):
            if self._mapped_table.isRowHidden(row):
                continue
            checkbox = self._mapped_row_checkbox(row)
            if checkbox is None:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._sync_mapped_bulk_delete()

    def _zoom_mapped(self, map_key: str) -> None:
        group = self._container.layers.find_dataset_group(map_key)
        if group is None:
            self._set_status(self.tr("Job output is not on the map."))
            self._container.notifications.warning(
                self.tr("Could not zoom — that job output is not loaded in QGIS.")
            )
            return
        with busy_action(
            self._container, self.tr("Zooming to job output…")
        ):
            try:
                self._container.basemaps.ensure_basemap()
            except Exception:  # noqa: BLE001
                pass
            self._container.layers.zoom_to_dataset(map_key)
        self._set_status(self.tr("Zoomed to mapped job output."))
        self._container.notifications.success(
            self.tr("Checked layers and zoomed to the job output group.")
        )

    def _delete_mapped(self, map_key: str) -> None:
        if not ConfirmationDialog.ask(
            self,
            self.tr("Remove mapped job"),
            self.tr(
                "Remove this job output from QGIS and delete the local download?"
            ),
            confirm_text=self.tr("Delete"),
            destructive=True,
        ):
            return
        self._container.jobs.remove_from_map(map_key, clear_cache=True)
        self._reload_mapped()
        if self._jobs:
            self._fill_table(self._jobs)
        self._set_status(self.tr("Removed job output from QGIS."))
        self._container.notifications.success(
            self.tr("Job output removed from the map.")
        )

    def _delete_mapped_selected(self) -> None:
        keys = self._selected_mapped_keys()
        if not keys:
            return
        if not ConfirmationDialog.ask(
            self,
            self.tr("Remove mapped jobs"),
            self.tr(
                "Remove {n} job output(s) from QGIS and delete local downloads?"
            ).format(n=len(keys)),
            confirm_text=self.tr("Delete"),
            destructive=True,
        ):
            return
        for key in keys:
            self._container.jobs.remove_from_map(key, clear_cache=True)
        self._reload_mapped()
        if self._jobs:
            self._fill_table(self._jobs)
        self._set_status(
            self.tr("Removed {n} job output(s) from QGIS.").format(n=len(keys))
        )
        self._container.notifications.success(
            self.tr("Removed {n} job output(s) from the map.").format(
                n=len(keys)
            )
        )

    def _load_project_groups(self) -> None:
        self._set_status(self.tr("Loading project groups…"), busy=True)
        worker = self._container.workers.submit(
            self._container.project_groups.list_project_groups
        )
        worker.signals.result.connect(self._on_groups_loaded)
        worker.signals.error.connect(self._on_groups_error)

    def _on_groups_loaded(self, groups) -> None:
        self._groups_ready = True
        if not groups:
            self._project_group_id = ""
            self._empty.set_message(
                self.tr("No project groups"),
                self.tr("Join a project group to view jobs."),
            )
            self._stack.setCurrentWidget(self._empty)
            self._set_status(self.tr("No project groups available."))
            return
        # Jobs API requires a project group — use the first returned group.
        self._project_group_id = str(groups[0].id or "").strip()
        self.reload()

    def _on_groups_error(self, exc) -> None:
        self._groups_ready = True
        self._project_group_id = ""
        self._error.set_message(
            self.tr("Unable to load project groups"), str(exc)
        )
        self._stack.setCurrentWidget(self._error)
        self._set_status(self.tr("Failed to load project groups."))

    def _on_job_id_typed(self, text: str) -> None:
        self._job_id_query = text.strip()
        self._job_id_clear.setEnabled(bool(self._job_id_query))
        self._search_timer.start()

    def _clear_job_id(self) -> None:
        self._job_id_edit.clear()

    def _on_status_changed(self) -> None:
        self._reload_from_filters()

    def _reload_from_filters(self) -> None:
        self.reload()

    def _on_table_scrolled(self, value: int) -> None:
        if not self._is_list_active():
            return
        if not self._scroll_past_load_threshold(value):
            return
        self._load_more()

    def _scroll_past_load_threshold(self, value: int) -> bool:
        bar = self._table.verticalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return False
        return (float(value) / float(maximum)) >= _SCROLL_LOAD_RATIO

    def _is_list_active(self) -> bool:
        return self._tabs.current == "list" and self._table.isVisible()

    def _load_more(self) -> None:
        if not self._is_list_active():
            return
        if self._list_loading or not self._has_more:
            return
        self._page += 1
        self._fetch_page(append=True)

    def _maybe_autoload_more(self) -> None:
        """Fill the list viewport only while the List tab is visible."""
        if not self._is_list_active():
            return
        if not self._has_more or self._list_loading:
            return
        bar = self._table.verticalScrollBar()
        if not self._table.isVisible() or self._table.viewport().height() < 40:
            return
        if bar.maximum() <= 0 or self._scroll_past_load_threshold(bar.value()):
            self._load_more()

    def reload(self) -> None:
        if not self._groups_ready:
            return
        group_id = self._project_group_id
        if not group_id:
            self._jobs = []
            self._page = 1
            self._has_more = False
            self._empty.set_message(
                self.tr("No project groups"),
                self.tr("Join a project group to view jobs."),
            )
            self._stack.setCurrentWidget(self._empty)
            self._count.setText("")
            return

        self._page = 1
        self._has_more = True
        self._fetch_page(append=False)

    def _fetch_page(self, *, append: bool) -> None:
        if self._list_loading:
            return
        group_id = self._project_group_id
        if not group_id:
            return
        self._list_loading = True
        self._append_next = append
        if append:
            self._set_status(self.tr("Loading more jobs…"), busy=True)
        else:
            self._set_status(self.tr("Loading jobs…"), busy=True)
            self._refresh.setEnabled(False)
        worker = self._container.workers.submit(
            self._container.jobs.fetch_jobs,
            group_id,
            page_no=self._page,
            page_size=_PAGE_SIZE,
            job_id=self._job_id_query,
            status=str(self._status.currentData() or ""),
        )
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        worker.signals.finished.connect(self._on_list_finished)

    def _on_list_finished(self) -> None:
        self._list_loading = False
        self._refresh.setEnabled(True)
        if self._has_more and self._is_list_active():
            QTimer.singleShot(0, self._maybe_autoload_more)

    def _on_loaded(self, jobs: List[JobRecord]) -> None:
        page_items = list(jobs)
        self._has_more = len(page_items) >= _PAGE_SIZE
        append = self._append_next

        if append:
            self._jobs.extend(page_items)
            if page_items:
                self._append_table_rows(page_items)
        else:
            self._jobs = page_items
            if not page_items:
                self._empty.set_message(
                    self.tr("No jobs found"),
                    self.tr("No jobs for this project group yet."),
                )
                self._stack.setCurrentWidget(self._empty)
                self._count.setText(self.tr("0 jobs"))
                self._set_status(self.tr("No jobs available."))
                return
            self._stack.setCurrentWidget(self._table)
            self._fill_table(page_items)

        count = len(self._jobs)
        self._count.setText(self.tr("{n} job(s)").format(n=count))
        self._set_status(self.tr("Loaded {} job(s).").format(count))

    def _fill_table(self, jobs: List[JobRecord]) -> None:
        bar = self._table.verticalScrollBar()
        scroll = bar.value() if bar is not None else 0
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setRowCount(0)
            self._append_table_rows(jobs)
        finally:
            self._table.setUpdatesEnabled(True)
            if bar is not None:
                bar.setValue(min(scroll, bar.maximum()))

    def _append_table_rows(self, jobs: List[JobRecord]) -> None:
        start = self._table.rowCount()
        self._table.setRowCount(start + len(jobs))
        for offset, job in enumerate(jobs):
            row = start + offset
            state = (
                self._container.jobs.local_state(job)
                if job.has_download
                else None
            )
            self._table.setCellWidget(row, 0, self._type_cell(job))
            self._table.setCellWidget(row, 1, self._status_badge(job.status))
            self._table.setCellWidget(
                row, 2, self._action_cell(job, state)
            )

    def _type_cell(self, job: JobRecord) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(4)

        # Row 1 — job type
        title = QLabel(job.display_type)
        title.setObjectName("DatasetName")
        title.setToolTip(job.display_type)
        title.setStyleSheet(
            "QLabel#DatasetName {{ color: {text}; font-size: 13px; "
            "font-weight: 600; }}".format(text=colors.TEXT)
        )
        col.addWidget(title)

        # Row 2 — job id (left) | duration (right)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(8)

        job_id = QLabel(str(job.id))
        job_id.setObjectName("DatasetId")
        job_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        job_id.setToolTip(self.tr("Job ID: {}").format(job.id))
        job_id.setStyleSheet(
            "QLabel#DatasetId {{ color: {muted}; font-size: 11px; "
            "font-family: Menlo, Monaco, Consolas, monospace; }}".format(
                muted=colors.TEXT_MUTED
            )
        )
        meta.addWidget(job_id, 0, Qt.AlignLeft | Qt.AlignVCenter)
        meta.addStretch(1)

        duration_text = format_duration(job.created_at, job.updated_at)
        if duration_text:
            duration = QLabel(
                self.tr("Duration: {}").format(duration_text)
            )
            duration.setObjectName("JobDuration")
            duration.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tip_parts = []
            if job.created_at:
                tip_parts.append(
                    self.tr("Created: {}").format(job.created_at)
                )
            if job.updated_at:
                tip_parts.append(
                    self.tr("Updated: {}").format(job.updated_at)
                )
            if tip_parts:
                duration.setToolTip("\n".join(tip_parts))
            duration.setStyleSheet(
                "QLabel#JobDuration {{ color: {muted}; font-size: 11px; "
                "font-style: italic; }}".format(muted=colors.TEXT_MUTED)
            )
            meta.addWidget(duration, 0, Qt.AlignRight | Qt.AlignVCenter)

        col.addLayout(meta)
        return host

    def _refresh_action_row(self, job_id: str) -> None:
        """Update only the Actions cell so scroll position stays put."""
        for row, job in enumerate(self._jobs):
            if job.id != job_id:
                continue
            if row >= self._table.rowCount():
                return
            state = (
                self._container.jobs.local_state(job)
                if job.has_download
                else None
            )
            self._table.setCellWidget(row, 2, self._action_cell(job, state))
            return

    def _status_badge(self, status: str) -> QWidget:
        key = (status or "").strip().upper().replace("_", "-")
        if key == "COMPLETED":
            return status_badge(self.tr("Completed"), "success")
        if key == "FAILED":
            return status_badge(self.tr("Failed"), "danger")
        if key in ("IN-PROGRESS", "IN PROGRESS", "RUNNING", "PROCESSING"):
            return status_badge(self.tr("In progress"), "accent")
        if key in ("PENDING", "QUEUED", "REQUESTED"):
            return status_badge(self.tr("Pending"), "warning")
        if key in ("CANCELLED", "CANCELED"):
            return status_badge(self.tr("Cancelled"), "neutral")
        label = (status or "—").replace("_", " ").replace("-", " ").strip()
        if label and label != "—":
            label = label[:1].upper() + label[1:].lower()
        return status_badge(label or "—", "neutral", tooltip=status or "")

    def _action_cell(
        self, job: JobRecord, state: Optional[DatasetLocalState]
    ) -> QWidget:
        host = QWidget()
        host.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(host)
        row.setContentsMargins(4, 4, 6, 4)
        row.setSpacing(0)
        row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if not job.has_download:
            dash = QLabel("—")
            dash.setStyleSheet("color: {};".format(colors.TEXT_MUTED))
            row.addWidget(dash)
            return host
        btn = self._action_button(job, state or DatasetLocalState.REMOTE)
        row.addWidget(btn)
        return host

    def _action_button(
        self, job: JobRecord, state: DatasetLocalState
    ):
        downloading = job.id in self._loading_ids
        if state == DatasetLocalState.LOADED:
            text = self.tr("Zoom to map")
            tip = self.tr("Already in the project — zoom to this job output")
            icon_name = "action_zoom.svg"
            width = 138
        elif downloading:
            text = self.tr("Downloading…")
            tip = self.tr("Download in progress")
            icon_name = "action_download.svg"
            width = 128
        else:
            text = self.tr("Download")
            tip = (
                self.tr("Use the local download — no re-download needed")
                if state == DatasetLocalState.CACHED
                else self.tr("Download job output and add layers to QGIS")
            )
            icon_name = "action_download.svg"
            width = 118

        btn = outline_action_button(
            text,
            color=colors.PRIMARY,
            hover_bg=colors.SURFACE_ALT,
            width=width,
            height=32,
            expand=False,
            icon_name=icon_name,
            icon_size=18,
        )
        btn.setToolTip(tip)
        btn.setAccessibleDescription(tip)
        btn.setEnabled(not downloading)
        if not downloading:
            btn.clicked.connect(partial(self._view, job.id))
        return btn

    def _job_by_id(self, job_id: str) -> Optional[JobRecord]:
        for job in self._jobs:
            if job.id == str(job_id):
                return job
        return None

    def _view(self, job_id: str) -> None:
        job = self._job_by_id(job_id)
        if job is None or not job.has_download:
            return

        state = self._container.jobs.local_state(job)
        if state == DatasetLocalState.LOADED:
            with busy_action(
                self._container, self.tr("Zooming to job output…")
            ):
                try:
                    self._container.basemaps.ensure_basemap()
                except Exception:  # noqa: BLE001
                    pass
                self._container.layers.zoom_to_dataset(job.map_key)
            self._set_status(self.tr("Zoomed to job output."))
            self._container.notifications.success(
                self.tr("Checked layers and zoomed to the job output group.")
            )
            return

        if job.id in self._loading_ids:
            return

        self._loading_ids.add(job.id)
        self._refresh_action_row(job.id)
        self._update_download_status()

        project_gen = self._container.project.generation
        worker = self._container.workers.submit(
            self._container.jobs.prepare_package, job
        )
        worker.signals.result.connect(
            partial(self._on_package_ready, job.id, project_gen)
        )
        worker.signals.error.connect(partial(self._on_view_error, job.id))

    def _update_download_status(self) -> None:
        n = len(self._loading_ids)
        if n <= 0:
            return
        if n == 1:
            self._set_status(self.tr("Downloading job output…"), busy=True)
        else:
            self._set_status(
                self.tr("Downloading {n} job outputs…").format(n=n),
                busy=True,
            )

    def _on_package_ready(
        self,
        job_id: str,
        project_gen: int,
        prepared: Tuple[List[str], str],
    ) -> None:
        if project_gen != self._container.project.generation:
            self._loading_ids.discard(job_id)
            try:
                self._refresh_action_row(job_id)
            except Exception:  # noqa: BLE001
                pass
            if self._loading_ids:
                self._update_download_status()
            else:
                self._set_status(
                    self.tr(
                        "Download kept in cache — QGIS project changed before "
                        "layers were added. Use Sync or Download again."
                    )
                )
            return
        job = self._job_by_id(job_id)
        if job is None:
            self._loading_ids.discard(job_id)
            self._refresh_action_row(job_id)
            if self._loading_ids:
                self._update_download_status()
            return
        geojsons, source = prepared
        self._set_status(self.tr("Adding layers to QGIS…"), busy=True)
        try:
            try:
                self._container.basemaps.ensure_basemap()
            except Exception:  # noqa: BLE001
                pass
            result = self._container.jobs.add_to_map(
                job,
                geojsons,
                source,
                display_name=job.display_type,
                zoom=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._on_view_error(job_id, exc)
            return
        self._loading_ids.discard(job_id)
        self._on_viewed(result)
        if self._loading_ids:
            self._update_download_status()

    def _on_viewed(self, result: JobLoadResult) -> None:
        self._refresh_action_row(result.job_id)
        if self._tabs.current == "mapped":
            self._reload_mapped()
        if result.source == "already_loaded":
            self._set_status(self.tr("Job output already in the map."))
            self._container.notifications.success(
                self.tr(
                    "Job output is already loaded. Use Zoom to map when ready."
                )
            )
            return
        if result.source == "cache":
            msg = self.tr(
                "Added {n} layer(s) from local download (no re-download)."
            ).format(n=result.layer_count)
            self._set_status(msg)
            self._container.notifications.success(
                self.tr(
                    "Added {n} layer(s) from cache. Use Zoom to map when ready."
                ).format(n=result.layer_count)
            )
            return
        msg = self.tr("Downloaded and loaded {n} layer(s).").format(
            n=result.layer_count
        )
        self._set_status(msg)
        self._container.notifications.success(
            self.tr(
                "Loaded {n} layer(s) into QGIS. Use Zoom to map when ready."
            ).format(n=result.layer_count)
        )

    def _on_view_error(self, job_id: str, exc) -> None:
        self._loading_ids.discard(job_id)
        self._refresh_action_row(job_id)
        if self._loading_ids:
            self._update_download_status()
        if isinstance(exc, (AuthenticationError, SessionExpiredError)):
            self._set_status(self.tr("Session expired. Please sign in again."))
            self._container.notifications.warning(
                self.tr("Your session has expired. Please sign in again.")
            )
            return
        message = (
            str(exc)
            if isinstance(exc, TdeiError)
            else self.tr("Could not load job output: {}").format(exc)
        )
        self._set_status(message)
        self._container.notifications.error(message)

    def _on_load_error(self, exc) -> None:
        if self._append_next:
            self._page = max(1, self._page - 1)
            self._has_more = True
            self._set_status(
                self.tr("Could not load more jobs: {}").format(exc)
            )
            return
        if isinstance(exc, (AuthenticationError, SessionExpiredError)):
            self._set_status(self.tr("Session expired. Please sign in again."))
            self._container.notifications.warning(
                self.tr("Your session has expired. Please sign in again.")
            )
            return
        body = str(exc) if isinstance(exc, TdeiError) else self.tr(
            "The server could not complete the request."
        )
        self._error.set_message(self.tr("Unable to load jobs"), body)
        self._stack.setCurrentWidget(self._error)
        self._set_status(self.tr("Failed to load jobs."))

    def _set_status(self, message: str, *, busy: bool = False) -> None:
        status = getattr(self._container, "status", None)
        if status is None:
            return
        if busy:
            status.busy(message)
        else:
            status.ready(message)
