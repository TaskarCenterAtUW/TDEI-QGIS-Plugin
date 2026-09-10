# -*- coding: utf-8 -*-
"""Datasets page — filters + table + load into QGIS via DatasetService."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from qgis.PyQt.QtCore import Qt, QTimer, QSize
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyleFactory,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.exceptions import AuthenticationError, SessionExpiredError, TdeiError
from ...core.models import (
    Dataset,
    DatasetLoadResult,
    DatasetLocalState,
    DatasetScope,
    MappedItem,
)
from ...features.mapped_tags.logic import item_matches_query
from ...features.osw.metadata import (
    load_geojson_file,
    raw_has_valid_dataset_area,
    set_dataset_area_on_metadata,
)
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
    tinted_icon,
)
from ..dialogs.confirmation_dialog import ConfirmationDialog
from ..jobs.runner import run_dataset_job
from ..styles import colors, dimensions
from ..styles import dimensions as ui_dimensions

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer

_PAGE_SIZE = 10
_SCROLL_LOAD_RATIO = 0.95
_MAPPED_CHECK_WIDTH = 44
_MAPPED_ACTIONS_WIDTH = 340
_ACTION_BTN_WIDTH = 90
_DELETE_BTN_WIDTH = 98
_BULK_DELETE_MIN_WIDTH = 168
_DATASET_ACTION_BTN_WIDTH = 138
_DATASET_MORE_BTN_SIZE = 32
_DATASET_ACTIONS_COL_WIDTH = 220
_DATASET_AREA_ICON_SIZE = 28


class DatasetsPage(QWidget):
    def __init__(self, container: "ServiceContainer", parent=None) -> None:
        super().__init__(parent)
        self._container = container
        self._loading_ids: Set[str] = set()
        self._adding_area_ids: Set[str] = set()
        self._list_loading = False
        self._append_next = False
        self._page = 1
        self._has_more = True
        self._datasets: List[Dataset] = []
        self._mapped: List[MappedItem] = []
        self._name_query = ""
        self._id_query = ""
        self._scope_ready = False
        self._bbox_capture = None
        self._build()
        # Context-menu / external downloads refresh this page when present.
        self._container.on_dataset_loaded = self.notify_dataset_loaded

    def notify_dataset_loaded(self, result) -> None:
        """Called after a dataset is loaded outside this page (e.g. map search)."""
        self._on_viewed(result)

    def _build(self) -> None:
        set_page(
            self,
            self.tr("Datasets"),
            self.tr("Browse, load, and manage OpenSidewalks datasets."),
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(self.tr("Datasets"))
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
            self.tr("Reload the datasets list or mapped items.")
        )
        self._refresh.clicked.connect(self._on_refresh)
        header.addWidget(title, 0, Qt.AlignVCenter)
        header.addWidget(self._tabs, 0, Qt.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._refresh, 0, Qt.AlignVCenter)
        layout.addLayout(header)

        self._mode_stack = QStackedWidget()
        self._mode_stack.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._mode_stack.addWidget(self._build_list_panel())
        self._mode_stack.addWidget(self._build_mapped_panel())
        layout.addWidget(self._mode_stack, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._reload_from_filters)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_filters())

        self._count = QLabel("")
        self._count.setObjectName("PageSubtitle")
        self._count.setFocusPolicy(Qt.NoFocus)
        self._count.setAccessibleName(self.tr("Dataset count"))
        layout.addWidget(self._count)

        self._stack = QStackedWidget()
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            [
                self.tr("Name"),
                self.tr("Status"),
                self.tr("Actions"),
            ]
        )
        set_name(
            self._table,
            self.tr("Datasets table"),
            self.tr("List of available TDEI datasets."),
        )
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(1, 128)
        self._table.setColumnWidth(2, _DATASET_ACTIONS_COL_WIDTH)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setFocusPolicy(Qt.StrongFocus)
        self._table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.verticalHeader().setDefaultSectionSize(60)
        self._table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)

        self._empty = EmptyState(
            self.tr("No datasets found"),
            self.tr("There are currently no datasets available."),
            self.tr("Refresh"),
        )
        self._empty.retry.connect(self.reload)
        self._error = ErrorState(
            self.tr("Unable to load datasets"),
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
        self._mapped_count.setAccessibleName(self.tr("Mapped dataset count"))
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
            self.tr("Remove selected mapped datasets from QGIS.")
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
            self.tr("Mapped datasets table"),
            self.tr("Datasets currently loaded in the QGIS map."),
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
                "Add a dataset from the List tab, or use Sync "
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
        outer = QHBoxLayout(host)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)

        name_col, self._name_edit, self._name_clear = self._filter_field(
            self.tr("Dataset"),
            self.tr("Search Dataset"),
        )
        self._name_edit.textChanged.connect(self._on_name_typed)
        self._name_clear.clicked.connect(self._clear_name)

        id_col, self._id_edit, self._id_clear = self._filter_field(
            self.tr("Dataset ID"),
            self.tr("Search Dataset ID"),
        )
        self._id_edit.textChanged.connect(self._on_id_typed)
        self._id_clear.clicked.connect(self._clear_id)

        scope_col = QVBoxLayout()
        scope_col.setSpacing(2)
        scope_label = QLabel(self.tr("Dataset Scope"))
        scope_label.setObjectName("FilterFieldLabel")
        self._scope = QComboBox()
        self._style_input(self._scope)
        self._scope.setMinimumWidth(dimensions.s(160))
        self._scope.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._scope.setFocusPolicy(Qt.StrongFocus)
        self._scope.addItem(
            self.tr("My Project Groups"), DatasetScope.MY_PROJECT_GROUPS.value
        )
        self._scope.currentIndexChanged.connect(self._on_scope_changed)
        label_for(
            scope_label,
            self._scope,
            name=self.tr("Dataset Scope"),
            description=self.tr("Filter datasets by project group scope."),
        )
        scope_col.addWidget(scope_label)
        scope_col.addWidget(self._scope)

        outer.addLayout(name_col, 1)
        outer.addLayout(id_col, 1)
        outer.addLayout(scope_col, 1)
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
        edit.setClearButtonEnabled(False)
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
        if not self._scope_ready:
            self._load_scope_options()
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
            if self._scope_ready and not self._datasets:
                self.reload()
            elif self._scope_ready:
                QTimer.singleShot(0, self._maybe_autoload_more)

    def _on_refresh(self) -> None:
        if self._tabs.current == "mapped":
            self._reload_mapped()
        else:
            self.reload()

    def _on_mapped_empty_action(self) -> None:
        if getattr(self, "_mapped_empty_action", "refresh") == "sync":
            request = getattr(self._container, "request_sync", None)
            if callable(request):
                request()
                return
        self._reload_mapped()

    def _reload_mapped(self) -> None:
        items = self._container.datasets.list_mapped()
        names = {ds.id: (ds.name or ds.id) for ds in self._datasets}
        for item in items:
            if item.key in names:
                item.display_name = names[item.key]
        self._container.tags.attach_to_items(items)
        self._mapped = items
        self._mapped_header.set_checked(False)
        self._mapped_header.set_check_enabled(bool(items))
        self._mapped_search.set_suggestions(self._container.tags.catalog())
        if not items:
            cached = len(self._container.layers.list_cached_package_keys())
            if cached:
                self._mapped_empty_action = "sync"
                self._mapped_empty.set_action_text(self.tr("Sync"))
                self._mapped_empty.set_message(
                    self.tr("Nothing mapped yet"),
                    self.tr(
                        "{n} local package(s) found on disk. "
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
                        "Add a dataset from the List tab, or Sync "
                        "to restore packages from local cache."
                    ),
                )
            self._mapped_stack.setCurrentWidget(self._mapped_empty)
            self._mapped_count.setText(self.tr("0 mapped"))
            self._mapped_bulk_delete.setVisible(False)
            self._set_status(self.tr("No datasets currently in the map."))
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
            self.tr("Managing {n} mapped dataset(s).").format(n=len(items))
        )

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
            self._set_status(self.tr("No mapped datasets match this search."))
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
        if item.kind == "dataset":
            # Mapped tab: prefer local package area when present.
            defined = self._container.datasets.dataset_area_defined(item.key)
            if defined is not None:
                area_icon = self._dataset_area_indicator(bool(defined))
                if area_icon is not None:
                    row.addWidget(area_icon, 0, Qt.AlignVCenter)
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
        row.addWidget(zoom)
        if item.kind == "dataset":
            clip = outline_action_button(
                self.tr("Clip"),
                color=colors.PRIMARY,
                hover_bg=colors.SURFACE_ALT,
                width=_ACTION_BTN_WIDTH,
                icon_name="tool_clip.svg",
            )
            clip.setAccessibleName(
                self.tr("Clip {}").format(item.display_name or item.key)
            )
            clip.setAccessibleDescription(
                self.tr(
                    "Draw a bounding box on the map and submit a clip job."
                )
            )
            clip.clicked.connect(partial(self._clip_mapped, item))
            row.addWidget(clip)
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

    def _zoom_mapped(self, dataset_id: str) -> None:
        group = self._container.layers.find_dataset_group(dataset_id)
        if group is None:
            self._set_status(self.tr("Dataset is not on the map."))
            self._container.notifications.warning(
                self.tr("Could not zoom — that dataset is not loaded in QGIS.")
            )
            return
        with busy_action(
            self._container, self.tr("Zooming to dataset…")
        ):
            try:
                self._container.datasets.ensure_basemap()
            except Exception:  # noqa: BLE001
                pass
            self._container.layers.zoom_to_dataset(dataset_id)
        self._set_status(self.tr("Zoomed to mapped dataset."))
        self._container.notifications.success(
            self.tr("Checked layers and zoomed to the dataset group.")
        )

    def _clip_mapped(self, item: MappedItem) -> None:
        if item.kind != "dataset":
            return
        from ...qgis.bbox_capture import BBoxCaptureController

        if self._bbox_capture is None:
            self._bbox_capture = BBoxCaptureController(
                self._container, parent=self
            )
            self._container.bbox_capture = self._bbox_capture
        map_search = getattr(self._container, "map_search", None)
        if map_search is not None and getattr(map_search, "active", False):
            try:
                map_search.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._bbox_capture.active:
            self._bbox_capture.cancel()
        self._bbox_capture.start(
            item.key,
            item.display_name or item.key,
            plugin_window=self.window(),
        )

    def _delete_mapped(self, dataset_id: str) -> None:
        if not ConfirmationDialog.ask(
            self,
            self.tr("Remove mapped dataset"),
            self.tr(
                "Remove this dataset from QGIS and delete the local download?"
            ),
            confirm_text=self.tr("Delete"),
            destructive=True,
        ):
            return
        self._container.datasets.remove_from_map(dataset_id, clear_cache=True)
        self._reload_mapped()
        self._refresh_row_states()
        self._set_status(self.tr("Removed dataset from QGIS."))
        self._container.notifications.success(
            self.tr("Dataset removed from the map.")
        )

    def _delete_mapped_selected(self) -> None:
        keys = self._selected_mapped_keys()
        if not keys:
            return
        if not ConfirmationDialog.ask(
            self,
            self.tr("Remove mapped datasets"),
            self.tr(
                "Remove {n} dataset(s) from QGIS and delete local downloads?"
            ).format(n=len(keys)),
            confirm_text=self.tr("Delete"),
            destructive=True,
        ):
            return
        for key in keys:
            self._container.datasets.remove_from_map(key, clear_cache=True)
        self._reload_mapped()
        self._refresh_row_states()
        self._set_status(
            self.tr("Removed {n} dataset(s) from QGIS.").format(n=len(keys))
        )
        self._container.notifications.success(
            self.tr("Removed {n} dataset(s) from the map.").format(n=len(keys))
        )

    def _load_scope_options(self) -> None:
        self._set_status(self.tr("Loading project groups…"), busy=True)
        worker = self._container.workers.submit(
            self._container.project_groups.list_project_groups
        )
        worker.signals.result.connect(self._on_scope_groups_loaded)
        worker.signals.error.connect(self._on_scope_groups_error)

    def _on_scope_groups_loaded(self, groups) -> None:
        saved = str(
            self._container.settings.get(
                "ui.dataset_scope", DatasetScope.MY_PROJECT_GROUPS.value
            )
            or DatasetScope.MY_PROJECT_GROUPS.value
        )
        self._scope.blockSignals(True)
        while self._scope.count() > 1:
            self._scope.removeItem(1)
        for group in groups:
            self._scope.addItem(group.name, group.id)
        index = self._scope.findData(saved)
        if index < 0:
            index = 0
        self._scope.setCurrentIndex(index)
        self._scope.blockSignals(False)
        self._scope_ready = True
        self.reload()

    def _on_scope_groups_error(self, exc) -> None:
        self._scope_ready = True
        self._container.notifications.warning(
            self.tr("Could not load project groups: {}").format(exc)
        )
        self.reload()

    def reload(self) -> None:
        if not self._scope_ready:
            return
        self._page = 1
        self._has_more = True
        self._fetch_page(append=False)

    def _fetch_page(self, *, append: bool) -> None:
        if self._list_loading:
            return
        self._list_loading = True
        self._append_next = append
        if append:
            self._set_status(self.tr("Loading more datasets…"), busy=True)
        else:
            self._set_status(self.tr("Loading datasets…"), busy=True)
            self._refresh.setEnabled(False)
        scope, project_group_id = self._current_scope_selection()
        worker = self._container.workers.submit(
            self._container.datasets.list_datasets,
            name=self._name_query,
            dataset_id=self._id_query,
            scope=scope,
            project_group_id=project_group_id,
            page_no=self._page,
            page_size=_PAGE_SIZE,
        )
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        worker.signals.finished.connect(self._on_list_finished)

    def _current_scope_selection(self):
        data = self._scope.currentData()
        if data == DatasetScope.MY_PROJECT_GROUPS.value or data in (None, ""):
            return DatasetScope.MY_PROJECT_GROUPS, None
        return DatasetScope.CURRENT_PROJECT_GROUP, str(data)

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
        # Hidden / zero-height tables report maximum()==0; never treat that as
        # "needs more pages" or pagination loops forever on Mapped.
        if not self._table.isVisible() or self._table.viewport().height() < 40:
            return
        if bar.maximum() <= 0 or self._scroll_past_load_threshold(bar.value()):
            self._load_more()

    def _on_name_typed(self, text: str) -> None:
        self._name_query = text.strip()
        self._name_clear.setEnabled(bool(self._name_query))
        self._search_timer.start()

    def _on_id_typed(self, text: str) -> None:
        self._id_query = text.strip()
        self._id_clear.setEnabled(bool(self._id_query))
        self._search_timer.start()

    def _clear_name(self) -> None:
        self._name_edit.clear()

    def _clear_id(self) -> None:
        self._id_edit.clear()

    def _on_scope_changed(self) -> None:
        self._container.settings.set("ui.dataset_scope", self._scope.currentData())
        self._reload_from_filters()

    def _on_list_finished(self) -> None:
        self._list_loading = False
        self._refresh.setEnabled(True)
        if self._has_more and self._is_list_active():
            QTimer.singleShot(0, self._maybe_autoload_more)

    def _on_loaded(self, datasets: List[Dataset]) -> None:
        page_items = list(datasets)
        self._has_more = len(page_items) >= _PAGE_SIZE
        append = self._append_next

        if append:
            self._datasets.extend(page_items)
            if page_items:
                self._append_table_rows(page_items)
        else:
            self._datasets = page_items
            if not page_items:
                self._empty.set_message(
                    self.tr("No datasets found"),
                    self.tr("There are currently no datasets available."),
                )
                self._stack.setCurrentWidget(self._empty)
                self._count.setText(self.tr("0 datasets"))
                self._set_status(self.tr("No datasets available."))
                return
            self._stack.setCurrentWidget(self._table)
            self._fill_table(page_items)

        count = len(self._datasets)
        loaded = sum(
            1
            for ds in self._datasets
            if self._container.datasets.local_state(ds.id)
            == DatasetLocalState.LOADED
        )
        cached = sum(
            1
            for ds in self._datasets
            if self._container.datasets.local_state(ds.id)
            == DatasetLocalState.CACHED
        )
        self._count.setText(
            self.tr("{n} dataset(s)").format(n=count)
        )
        self._set_status(
            self.tr(
                "{total} datasets · {loaded} in map · {cached} cached locally"
            ).format(total=count, loaded=loaded, cached=cached)
        )

    def _fill_table(self, datasets: List[Dataset]) -> None:
        bar = self._table.verticalScrollBar()
        scroll = bar.value() if bar is not None else 0
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setRowCount(0)
            self._append_table_rows(datasets)
        finally:
            self._table.setUpdatesEnabled(True)
            if bar is not None:
                bar.setValue(min(scroll, bar.maximum()))

    def _append_table_rows(self, datasets: List[Dataset]) -> None:
        start = self._table.rowCount()
        self._table.setRowCount(start + len(datasets))
        for offset, dataset in enumerate(datasets):
            row = start + offset
            state = self._container.datasets.local_state(dataset.id)
            self._table.setCellWidget(row, 0, self._name_cell(dataset))
            self._table.setCellWidget(
                row, 1, self._release_status_badge(dataset.status)
            )
            self._table.setCellWidget(
                row, 2, self._action_cell(dataset.id, state)
            )

    def _name_cell(self, dataset: Dataset) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(3)

        title = dataset.name.strip() or self.tr("(unnamed)")
        name = QLabel(title)
        name.setObjectName("DatasetName")
        name.setWordWrap(False)
        name.setToolTip(title)
        name.setStyleSheet(
            "QLabel#DatasetName {{ color: {text}; font-size: 13px; "
            "font-weight: 600; }}".format(text=colors.TEXT)
        )
        col.addWidget(name)

        dataset_id = (dataset.id or "").strip() or "—"
        version = (dataset.version or "").strip() or "—"
        parts = [
            "{} {}".format(self.tr("ID"), dataset_id),
            "{} {}".format(self.tr("Version"), version),
        ]
        meta = QLabel("  |  ".join(parts))
        meta.setObjectName("DatasetMeta")
        meta.setWordWrap(False)
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta.setToolTip(
            "\n".join(
                (
                    self.tr("ID: {}").format(dataset_id),
                    self.tr("Version: {}").format(version),
                )
            )
        )
        meta.setStyleSheet(
            "QLabel#DatasetMeta {{ color: {muted}; font-size: 11px; }}".format(
                muted=colors.TEXT_MUTED
            )
        )
        col.addWidget(meta)
        return host

    def _refresh_row_states(self) -> None:
        if self._datasets:
            self._fill_table(self._datasets)

    def _refresh_action_row(self, dataset_id: str) -> None:
        """Update only the Actions cell so scroll position stays put."""
        for row, dataset in enumerate(self._datasets):
            if dataset.id != dataset_id:
                continue
            if row >= self._table.rowCount():
                return
            state = self._container.datasets.local_state(dataset_id)
            self._table.setCellWidget(
                row, 2, self._action_cell(dataset_id, state)
            )
            return

    def on_project_layers_changed(self) -> None:
        """Called after Sync or when the QGIS project is opened/cleared."""
        # Drop in-flight Download UI; package-ready also checks project generation.
        self._loading_ids.clear()
        try:
            if self._bbox_capture is not None and getattr(
                self._bbox_capture, "active", False
            ):
                self._bbox_capture.cancel()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._tabs.current == "mapped":
                self._reload_mapped()
            if self._datasets:
                self._refresh_row_states()
        except Exception:  # noqa: BLE001 — never crash QGIS on project switch
            pass

    def _release_status_badge(self, status: str) -> QWidget:
        key = (status or "").strip().casefold()
        if key in ("publish", "published"):
            return status_badge(self.tr("Publish"), "success")
        if key in ("pre-release", "prerelease", "pre_release"):
            return status_badge(self.tr("Pre-Release"), "warning")
        label = (status or "").strip() or "—"
        return status_badge(label, "neutral", tooltip=status or "")

    def _action_cell(
        self, dataset_id: str, state: DatasetLocalState
    ) -> QWidget:
        host = QWidget()
        host.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(host)
        row.setContentsMargins(4, 4, 6, 4)
        row.setSpacing(4)
        row.setAlignment(Qt.AlignVCenter)
        btn = self._action_button(dataset_id, state)
        row.addWidget(btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        has_area = self._dataset_has_api_area(dataset_id)
        area_icon = self._dataset_area_indicator(has_area)
        if area_icon is not None:
            row.addWidget(area_icon, 0, Qt.AlignVCenter)
        row.addStretch(1)
        more = self._dataset_more_button(dataset_id, has_area=has_area)
        if more is not None:
            row.addWidget(more, 0, Qt.AlignRight | Qt.AlignVCenter)
        return host

    def _find_dataset(self, dataset_id: str) -> Optional[Dataset]:
        wanted = str(dataset_id or "").strip()
        for dataset in self._datasets:
            if str(getattr(dataset, "id", "") or "").strip() == wanted:
                return dataset
        return None

    def _dataset_has_api_area(self, dataset_id: str) -> bool:
        """Whether the datasets list response embeds a valid dataset_area."""
        dataset = self._find_dataset(dataset_id)
        if dataset is None:
            return False
        return raw_has_valid_dataset_area(getattr(dataset, "raw", None))

    def _dataset_area_indicator(self, has_area: bool):
        """Map icon: green when API area is valid, red when missing/invalid."""
        if has_area:
            tip = self.tr("Dataset area defined")
            color = colors.SUCCESS
            object_name = "DatasetAreaOk"
        else:
            tip = self.tr("Dataset area not defined")
            color = colors.ERROR
            object_name = "DatasetAreaWarning"
        btn = QToolButton()
        btn.setObjectName(object_name)
        btn.setCursor(Qt.ArrowCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAttribute(Qt.WA_MacShowFocusRect, False)
        btn.setAutoRaise(True)
        btn.setEnabled(False)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setFixedSize(_DATASET_AREA_ICON_SIZE, _DATASET_AREA_ICON_SIZE)
        btn.setIcon(
            tinted_icon(
                "action_map.svg",
                color,
                size=ui_dimensions.s(18),
                dpr=ui_dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(ui_dimensions.s(18), ui_dimensions.s(18)))
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setAccessibleDescription(tip)
        btn.setStyleSheet(
            "QToolButton#{name} {{ background: transparent; "
            "border: none; padding: 0; }}"
            "QToolButton#{name}:disabled {{ color: {color}; }}".format(
                name=object_name,
                color=color,
            )
        )
        return btn

    def _dataset_more_button(self, dataset_id: str, *, has_area: bool):
        """⋮ overflow for dataset jobs and add-dataset-area."""
        jobs = []
        if self._container.settings.feature_enabled("jobs"):
            jobs = list(self._container.jobs.list_dataset_row_jobs() or [])
        can_generate_area = not has_area
        if not jobs and not can_generate_area:
            return None

        more = QToolButton()
        more.setObjectName("DatasetMoreButton")
        more.setCursor(Qt.PointingHandCursor)
        more.setFocusPolicy(Qt.StrongFocus)
        more.setAttribute(Qt.WA_MacShowFocusRect, False)
        more.setAutoRaise(True)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setToolButtonStyle(Qt.ToolButtonIconOnly)
        more.setFixedSize(_DATASET_MORE_BTN_SIZE, _DATASET_MORE_BTN_SIZE)
        more.setIcon(
            tinted_icon(
                "more_vert.svg",
                colors.TEXT_SECONDARY,
                size=ui_dimensions.s(18),
                dpr=ui_dimensions.device_pixel_ratio(more),
            )
        )
        more.setIconSize(QSize(ui_dimensions.s(18), ui_dimensions.s(18)))
        more.setToolTip(self.tr("More actions"))
        more.setAccessibleName(self.tr("More actions"))
        more.setAccessibleDescription(
            self.tr(
                "Open more actions for this dataset, such as add "
                "dataset area or Self Merge."
            )
        )
        more.setStyleSheet(
            "QToolButton#DatasetMoreButton {{ background: {surface}; "
            "border: 1px solid {border}; border-radius: 4px; padding: 0; }}"
            "QToolButton#DatasetMoreButton:hover {{ background: {alt}; "
            "border-color: {primary}; }}"
            "QToolButton#DatasetMoreButton:focus {{ border: 2px solid {focus}; }}"
            "QToolButton#DatasetMoreButton::menu-indicator {{ image: none; "
            "width: 0; }}".format(
                surface=colors.SURFACE,
                border=colors.BORDER,
                alt=colors.SURFACE_ALT,
                primary=colors.PRIMARY,
                focus=colors.FOCUS,
            )
        )

        menu = QMenu(more)
        menu.setToolTipsVisible(True)
        if can_generate_area:
            generate = menu.addAction(self.tr("Add dataset area"))
            generate.setToolTip(
                self.tr(
                    "Build a concave-hull dataset_area from OSW layers, "
                    "set it on the metadata from the dataset API response, "
                    "and upload via edit metadata."
                )
            )
            generate.triggered.connect(
                partial(self._add_dataset_area, dataset_id)
            )
        for job in jobs:
            action = menu.addAction(job.title)
            action.setToolTip(job.title)
            action.triggered.connect(
                partial(self._run_dataset_row_job, job, dataset_id)
            )
        more.setMenu(menu)
        return more

    def _add_dataset_area(self, dataset_id: str) -> None:
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id or dataset_id in self._adding_area_ids:
            return
        self._adding_area_ids.add(dataset_id)
        datasets = self._container.datasets
        if datasets.has_local_package(dataset_id):
            self._finish_add_dataset_area(dataset_id)
            return
        self._set_status(
            self.tr("Fetching OSW layers to build area…"), busy=True
        )
        worker = self._container.workers.submit(
            datasets.prepare_package, dataset_id
        )
        worker.signals.result.connect(
            partial(self._on_package_ready_for_area, dataset_id)
        )
        worker.signals.error.connect(
            partial(self._on_add_dataset_area_error, dataset_id)
        )

    def _on_package_ready_for_area(self, dataset_id: str, _prepared) -> None:
        if dataset_id not in self._adding_area_ids:
            return
        self._finish_add_dataset_area(dataset_id)

    def _finish_add_dataset_area(self, dataset_id: str) -> None:
        dataset = self._find_dataset(dataset_id)
        raw = getattr(dataset, "raw", None) if dataset is not None else None
        try:
            with busy_action(
                self._container, self.tr("Adding dataset area…")
            ):
                area_path, kind, added = (
                    self._container.datasets.add_dataset_area(
                        dataset_id,
                        raw=raw if isinstance(raw, dict) else None,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._on_add_dataset_area_error(dataset_id, exc)
            return

        self._adding_area_ids.discard(dataset_id)
        self._patch_dataset_raw_area(dataset_id, area_path)
        self._refresh_action_row(dataset_id)
        if added:
            self._container.notifications.success(
                self.tr(
                    "Dataset area added from {kind} and metadata updated."
                ).format(kind=kind)
            )
            self._set_status(self.tr("Dataset area added."))
        else:
            self._container.notifications.success(
                self.tr(
                    "Dataset area added from {kind} and metadata updated. "
                    "Load the dataset to see it on the map."
                ).format(kind=kind)
            )
            self._set_status(self.tr("Dataset area and metadata updated."))

    def _patch_dataset_raw_area(self, dataset_id: str, area_path: str) -> None:
        """Update in-memory list raw so the row icon turns green immediately."""
        area = load_geojson_file(area_path)
        if area is None:
            return
        dataset = self._find_dataset(dataset_id)
        if dataset is None or not isinstance(getattr(dataset, "raw", None), dict):
            return
        try:
            meta = dataset.raw.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                dataset.raw["metadata"] = meta
            set_dataset_area_on_metadata(meta, area)
        except Exception:  # noqa: BLE001
            pass

    def _on_add_dataset_area_error(self, dataset_id: str, exc) -> None:
        self._adding_area_ids.discard(dataset_id)
        message = str(exc).strip() if exc is not None else ""
        if not message:
            message = self.tr("Could not add dataset area.")
        self._container.notifications.error(message)
        self._set_status(self.tr("Add dataset area failed."))
        self._refresh_action_row(dataset_id)

    def _run_dataset_row_job(self, job, dataset_id: str) -> None:
        run_dataset_job(
            self._container,
            job,
            dataset_id,
            parent=self.window(),
        )

    def _action_button(
        self, dataset_id: str, state: DatasetLocalState
    ):
        downloading = dataset_id in self._loading_ids
        if state == DatasetLocalState.LOADED:
            text = self.tr("Zoom to map")
            tip = self.tr("Already in the project — zoom to this dataset")
            icon_name = "action_zoom.svg"
        elif downloading:
            text = self.tr("Downloading…")
            tip = self.tr("Download in progress")
            icon_name = "action_download.svg"
        else:
            # REMOTE or CACHED: download (or reuse local cache) and add to map.
            text = self.tr("Download")
            tip = (
                self.tr("Use the local download — no re-download needed")
                if state == DatasetLocalState.CACHED
                else self.tr("Download and add layers to QGIS")
            )
            icon_name = "action_download.svg"

        btn = outline_action_button(
            text,
            color=colors.PRIMARY,
            hover_bg=colors.SURFACE_ALT,
            width=_DATASET_ACTION_BTN_WIDTH,
            height=32,
            expand=False,
            icon_name=icon_name,
            icon_size=18,
        )
        btn.setToolTip(tip)
        btn.setAccessibleDescription(tip)
        btn.setEnabled(not downloading)
        if not downloading:
            btn.clicked.connect(partial(self._view, dataset_id))
        return btn

    def _on_load_error(self, exc) -> None:
        if self._append_next:
            self._page = max(1, self._page - 1)
            self._has_more = True
            self._set_status(
                self.tr("Could not load more datasets: {}").format(exc)
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
        self._error.set_message(self.tr("Unable to load datasets"), body)
        self._stack.setCurrentWidget(self._error)
        self._set_status(self.tr("Failed to load datasets."))

    def _view(self, dataset_id: str) -> None:
        state = self._container.datasets.local_state(dataset_id)
        if state == DatasetLocalState.LOADED:
            with busy_action(
                self._container, self.tr("Zooming to dataset…")
            ):
                self._container.datasets.ensure_basemap()
                self._container.layers.zoom_to_dataset(dataset_id)
            self._set_status(self.tr("Zoomed to dataset."))
            self._container.notifications.success(
                self.tr("Checked layers and zoomed to the dataset group.")
            )
            return

        if dataset_id in self._loading_ids:
            return

        self._loading_ids.add(dataset_id)
        self._refresh_action_row(dataset_id)
        self._update_download_status()

        project_gen = self._container.project.generation
        worker = self._container.workers.submit(
            self._container.datasets.prepare_package, dataset_id
        )
        worker.signals.result.connect(
            partial(self._on_package_ready, dataset_id, project_gen)
        )
        worker.signals.error.connect(
            partial(self._on_view_error, dataset_id)
        )

    def _update_download_status(self) -> None:
        n = len(self._loading_ids)
        if n <= 0:
            return
        if n == 1:
            self._set_status(self.tr("Downloading dataset…"), busy=True)
        else:
            self._set_status(
                self.tr("Downloading {n} datasets…").format(n=n),
                busy=True,
            )

    def _on_package_ready(
        self,
        dataset_id: str,
        project_gen: int,
        prepared: Tuple[List[str], str],
    ) -> None:
        if project_gen != self._container.project.generation:
            self._loading_ids.discard(dataset_id)
            try:
                self._refresh_action_row(dataset_id)
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
        geojsons, source = prepared
        self._set_status(
            self.tr("Adding layers to QGIS…"), busy=True
        )
        try:
            display = ""
            for ds in self._datasets:
                if ds.id == dataset_id:
                    display = ds.name or ""
                    break
            result = self._container.datasets.add_to_map(
                dataset_id,
                geojsons,
                source,
                display_name=display,
                zoom=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._on_view_error(dataset_id, exc)
            return
        self._loading_ids.discard(dataset_id)
        self._on_viewed(result)
        if self._loading_ids:
            self._update_download_status()

    def _on_viewed(self, result: DatasetLoadResult) -> None:
        self._refresh_action_row(result.dataset_id)
        if self._tabs.current == "mapped":
            self._reload_mapped()
        if result.source == "already_loaded":
            self._set_status(self.tr("Dataset already in the map."))
            self._container.notifications.success(
                self.tr("Dataset is already loaded. Use Zoom to map when ready.")
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

    def _on_view_error(self, dataset_id: str, exc) -> None:
        self._loading_ids.discard(dataset_id)
        self._refresh_action_row(dataset_id)
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
            else self.tr("Could not load dataset: {}").format(exc)
        )
        self._set_status(message)
        self._container.notifications.error(message)

    def _set_status(self, message: str, *, busy: bool = False) -> None:
        status = getattr(self._container, "status", None)
        if status is None:
            return
        if busy:
            status.busy(message)
        else:
            status.ready(message)
