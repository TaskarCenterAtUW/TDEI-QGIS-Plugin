# -*- coding: utf-8 -*-
"""Map-search status bar overlay on the QGIS map canvas."""

from __future__ import annotations

from functools import partial
from typing import Sequence

from qgis.PyQt.QtCore import QSize, QStringListModel, QTimer, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...features.osw.metadata import raw_has_valid_dataset_area
from ..a11y import keyboard_focus, set_name
from ..components import tinted_icon
from ..styles import colors, dimensions, typography
from .map_overlay import apply_glass_frame, pointer_over_overlay

# Combo sentinels (not real project-group UUIDs).
_ALL_GROUPS_DATA = "all"
_MY_GROUPS_DATA = "myProjectGroups"
_STATUS_ALL = "All"
_RESULT_LIMIT = 10
_AREA_ICON_SIZE = 22
_AREA_ICON_PX = 16
_MORE_BTN_SIZE = 28
_HAS_AREA_ROLE = Qt.UserRole + 1
_STATUS_ROLE = Qt.UserRole + 2
_VIEW_FULL = "full"
_VIEW_COMPACT = "compact"
_VIEW_SMALL = "small"
_BUSY_STRIPE_MS = 28
_BUSY_STRIPE_WIDTH = 4


class _BusyEdgeStripe(QWidget):
    """Animated purple vertical stripe along the left edge while a request runs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapSearchBusyStripe")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(_BUSY_STRIPE_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._active:
            if active:
                self.sync_to_parent()
                self.raise_()
            return
        self._active = active
        if active:
            self._phase = 0.0
            self.sync_to_parent()
            self.show()
            self.raise_()
            if not self._timer.isActive():
                self._timer.start()
            self.update()
        else:
            self._timer.stop()
            self.hide()

    def sync_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(2, dimensions.s(_BUSY_STRIPE_WIDTH))
        self.setGeometry(0, 0, width, max(1, parent.height()))

    def _tick(self) -> None:
        # ~1.4s for a full bounce cycle.
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        radius = max(2.0, float(dimensions.s(10)))
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, width * 3, height, radius, radius)
        painter.setClipPath(clip)

        track = QColor(colors.PRIMARY)
        track.setAlpha(210)
        painter.fillRect(0, 0, width, height, track)

        band = max(24, int(height * 0.32))
        # Triangle wave: travel down then up.
        t = self._phase
        travel = (t * 2.0) if t < 0.5 else (2.0 - t * 2.0)
        y = int(travel * max(0, height - band))

        glow = QLinearGradient(0, y, 0, y + band)
        top = QColor(colors.PRIMARY_LIGHT)
        top.setAlpha(0)
        mid = QColor("#c4b0e8")
        mid.setAlpha(255)
        bottom = QColor(colors.PRIMARY_LIGHT)
        bottom.setAlpha(0)
        glow.setColorAt(0.0, top)
        glow.setColorAt(0.45, mid)
        glow.setColorAt(0.55, mid)
        glow.setColorAt(1.0, bottom)
        painter.fillRect(0, y, width, band, glow)


def _theme_or_tinted(qgis_names, fallback_svg: str, color: str, size: int):
    try:
        from qgis.core import QgsApplication

        for name in qgis_names:
            icon = QgsApplication.getThemeIcon(name)
            if icon is not None and not icon.isNull():
                return icon
    except Exception:  # noqa: BLE001
        pass
    return tinted_icon(fallback_svg, color, size=size)


class MapSearchBar(QFrame):
    """Overlay stuck to the map canvas while dataset search is active."""

    closed = pyqtSignal()
    project_group_changed = pyqtSignal(str)  # group id or "" for my groups
    status_filter_changed = pyqtSignal(str)  # All | Publish | Pre-Release
    name_filter_changed = pyqtSignal(str)
    ignore_map_extent_changed = pyqtSignal(bool)
    dataset_selected = pyqtSignal(str)  # highlight area (no zoom)
    dataset_zoom_requested = pyqtSignal(str)  # zoom map to dataset area
    add_dataset_area_requested = pyqtSignal(str)  # generate area when missing
    download_requested = pyqtSignal(str)  # download / add to map / zoom

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MapSearchBar")
        # dataset_id -> (label, enabled, tooltip); read each time ⋮ opens.
        self._download_state_fn = None
        apply_glass_frame(self)
        # Child of the canvas (not a Tool window) so it stays with the map view.
        self.setWindowFlags(Qt.Widget)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        set_name(
            self,
            self.tr("Map search"),
            self.tr(
                "Search TDEI datasets that overlap the current map view."
            ),
        )
        self._zoom_ok = True
        self._count = 0
        self._busy = False
        self._busy_message = ""
        self._syncing_groups = False
        self._syncing_status = False
        self._canvas = None
        self._map_canvas_ref = None
        self._iface = None
        self._nav_syncing = False
        self._nav_tools = {}
        self._nav_active_key = ""
        self._view_mode = _VIEW_FULL
        self.setStyleSheet(self._stylesheet(active=True))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        # Header: map icon + title …… compact / small
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self._brand = QToolButton()
        self._brand.setObjectName("MapSearchBrand")
        self._brand.setAutoRaise(True)
        self._brand.setCursor(Qt.PointingHandCursor)
        self._brand.setFocusPolicy(Qt.StrongFocus)
        self._brand.setToolButtonStyle(Qt.ToolButtonIconOnly)
        keyboard_focus(self._brand)
        self._brand.clicked.connect(self._on_brand_clicked)
        brand_px = dimensions.s(18)
        self._brand.setIcon(
            tinted_icon(
                "action_map.svg",
                colors.PRIMARY,
                size=brand_px,
                dpr=dimensions.device_pixel_ratio(self._brand),
            )
        )
        self._brand.setIconSize(QSize(brand_px, brand_px))
        self._brand.setFixedSize(dimensions.s(28), dimensions.s(28))
        set_name(
            self._brand,
            self.tr("Map search"),
            self.tr("Collapse to title only, or expand when minimized."),
        )

        self._eyebrow = QLabel(self.tr("MAP SEARCH"))
        self._eyebrow.setObjectName("MapSearchEyebrow")
        self._eyebrow.setFocusPolicy(Qt.NoFocus)
        self._eyebrow.setCursor(Qt.PointingHandCursor)
        self._eyebrow.installEventFilter(self)

        self._compact_btn = self._mode_button(
            "view_compact.svg",
            self.tr("Compact"),
            self.tr("Compact — hide the dataset search section."),
            self._on_compact_clicked,
        )
        self._small_btn = self._mode_button(
            "view_small.svg",
            self.tr("Small"),
            self.tr("Small — title bar only."),
            self._on_small_clicked,
        )
        self._close = self._mode_button(
            "action_close.svg",
            self.tr("Close"),
            self.tr("Stop map search and clear result layers."),
            self.closed.emit,
        )
        self._close.setCheckable(False)
        self._close.setObjectName("MapSearchCloseBtn")
        self._paint_close_button(self._close)
        header.addWidget(self._brand, 0, Qt.AlignVCenter)
        header.addWidget(self._eyebrow, 0, Qt.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._compact_btn, 0, Qt.AlignVCenter)
        header.addWidget(self._small_btn, 0, Qt.AlignVCenter)
        header.addWidget(self._close, 0, Qt.AlignVCenter)

        self._body = QWidget()
        self._body.setObjectName("MapSearchBody")
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        # Entire dataset-search section (collapsed by compact mode).
        self._search_section = QWidget()
        self._search_section.setObjectName("MapSearchSection")
        search_layout = QVBoxLayout(self._search_section)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)

        self._title = QLabel(self.tr("Searching this view…"))
        self._title.setObjectName("MapSearchTitle")
        self._title.setWordWrap(True)
        self._title.setFocusPolicy(Qt.NoFocus)
        self._title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._hint = QLabel(
            self.tr("Pan or zoom — results update when the view settles.")
        )
        self._hint.setObjectName("MapSearchHint")
        self._hint.setWordWrap(True)
        self._hint.setFocusPolicy(Qt.NoFocus)
        self._hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Fixed copy block so searching ↔ empty text swaps do not resize the panel.
        self._copy_block = QWidget()
        self._copy_block.setObjectName("MapSearchCopy")
        self._copy_block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        copy_layout = QVBoxLayout(self._copy_block)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(2)
        copy_layout.addWidget(self._title)
        copy_layout.addWidget(self._hint)
        self._apply_copy_block_heights()

        filters = QWidget()
        filters.setObjectName("MapSearchFilters")
        filters_layout = QVBoxLayout(filters)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(10)

        def _labeled_field(label_text: str, field: QWidget) -> QWidget:
            wrap = QWidget()
            col = QVBoxLayout(wrap)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(4)
            label = QLabel(label_text)
            label.setObjectName("MapSearchLabel")
            label.setFocusPolicy(Qt.NoFocus)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            field.setMinimumWidth(0)
            col.addWidget(label)
            col.addWidget(field)
            return wrap

        self._groups = QComboBox()
        self._groups.setObjectName("MapSearchCombo")
        keyboard_focus(self._groups)
        set_name(
            self._groups,
            self.tr("Project group"),
            self.tr(
                "Filter map search by project group. "
                "All applies no group filter. "
                "My Project Groups includes all of your groups."
            ),
        )
        self._groups.addItem(self.tr("All"), _ALL_GROUPS_DATA)
        self._groups.addItem(self.tr("My Project Groups"), _MY_GROUPS_DATA)
        self._groups.currentIndexChanged.connect(self._on_group_changed)
        filters_layout.addWidget(
            _labeled_field(self.tr("Project group"), self._groups)
        )

        self._status = QComboBox()
        self._status.setObjectName("MapSearchCombo")
        keyboard_focus(self._status)
        set_name(
            self._status,
            self.tr("Status"),
            self.tr(
                "Filter map search by dataset release status. "
                "All includes Publish and Pre-Release."
            ),
        )
        self._status.addItem(self.tr("All"), _STATUS_ALL)
        self._status.addItem(self.tr("Publish"), "Publish")
        self._status.addItem(self.tr("Pre-Release"), "Pre-Release")
        self._status.setCurrentIndex(0)
        self._status.currentIndexChanged.connect(self._on_status_changed)
        filters_layout.addWidget(
            _labeled_field(self.tr("Status"), self._status)
        )

        # Find-datasets accordion (inside search section).
        self._find_block = QWidget()
        self._find_block.setObjectName("MapSearchFindBlock")
        find_layout = QVBoxLayout(self._find_block)
        find_layout.setContentsMargins(0, 0, 0, 0)
        find_layout.setSpacing(6)

        self._panel_collapsed = True
        self._results_shown = 0
        self._panel_toggle = QToolButton()
        self._panel_toggle.setObjectName("MapSearchSectionToggle")
        self._panel_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._panel_toggle.setAutoRaise(True)
        self._panel_toggle.setCursor(Qt.PointingHandCursor)
        self._panel_toggle.setFocusPolicy(Qt.StrongFocus)
        keyboard_focus(self._panel_toggle)
        self._panel_toggle.clicked.connect(self._toggle_panel)

        self._panel_body = QWidget()
        self._panel_body.setObjectName("MapSearchPanelBody")
        panel_layout = QVBoxLayout(self._panel_body)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(6)

        name_label = QLabel(self.tr("Dataset name"))
        name_label.setObjectName("MapSearchLabel")
        name_label.setFocusPolicy(Qt.NoFocus)
        self._name = QLineEdit()
        self._name.setObjectName("MapSearchName")
        self._name.setPlaceholderText(self.tr("Search by dataset name…"))
        self._name.setClearButtonEnabled(True)
        keyboard_focus(self._name)
        set_name(
            self._name,
            self.tr("Dataset name"),
            self.tr(
                "Search datasets by name. Name search ignores the map extent."
            ),
        )
        self._name.textChanged.connect(self._on_name_changed)
        self._name_model = QStringListModel(self)
        self._name_completer = QCompleter(self._name_model, self._name)
        self._name_completer.setCaseSensitivity(Qt.CaseInsensitive)
        try:
            self._name_completer.setFilterMode(Qt.MatchContains)
        except Exception:  # noqa: BLE001
            pass
        self._name_completer.setCompletionMode(QCompleter.PopupCompletion)
        self._name.setCompleter(self._name_completer)

        self._ignore_extent = QCheckBox(
            self.tr("Ignore map extent (name search)")
        )
        self._ignore_extent.setObjectName("MapSearchIgnoreExtent")
        self._ignore_extent.setChecked(False)
        keyboard_focus(self._ignore_extent)
        set_name(
            self._ignore_extent,
            self.tr("Ignore map extent"),
            self.tr(
                "When checked, search by dataset name without limiting "
                "results to the current map view."
            ),
        )
        self._ignore_extent.toggled.connect(self._on_ignore_extent_toggled)

        self._results = QListWidget()
        self._results.setObjectName("MapSearchResults")
        self._results.setFocusPolicy(Qt.StrongFocus)
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._results.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._results.setSelectionMode(QAbstractItemView.SingleSelection)
        self._results.setUniformItemSizes(False)
        # Fixed — never Expanding, or the overlay grows to the canvas height.
        self._results.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._configure_results_height(False)
        keyboard_focus(self._results)
        set_name(
            self._results,
            self.tr("Dataset results"),
            self.tr(
                "Top matching datasets. Click to highlight; double-click to zoom."
            ),
        )
        self._results.itemActivated.connect(self._on_result_activated)
        self._results.itemClicked.connect(self._on_result_clicked)
        self._results.hide()

        panel_layout.addWidget(name_label)
        panel_layout.addWidget(self._name)
        panel_layout.addWidget(self._ignore_extent)
        panel_layout.addWidget(self._results)
        find_layout.addWidget(self._panel_toggle)
        find_layout.addWidget(self._panel_body)

        self._meta = QLabel("")
        self._meta.setObjectName("MapSearchMeta")
        self._meta.setWordWrap(False)
        self._meta.setFocusPolicy(Qt.NoFocus)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        footer.addWidget(self._meta, 1, Qt.AlignVCenter)
        self._footer_nav = QWidget()
        self._footer_nav.setObjectName("MapSearchNav")
        nav_row = QHBoxLayout(self._footer_nav)
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(2)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons = {}
        nav_icon_px = dimensions.s(16)
        nav_defs = (
            (
                "zoom_in",
                _theme_or_tinted(
                    ["/mActionZoomIn.svg"],
                    "tool_zoom_in.svg",
                    colors.TEXT,
                    nav_icon_px,
                ),
                self.tr("Zoom in"),
                self.tr("Click the map to zoom in."),
                self._on_nav_zoom_in,
            ),
            (
                "zoom_out",
                _theme_or_tinted(
                    ["/mActionZoomOut.svg"],
                    "tool_zoom_out.svg",
                    colors.TEXT,
                    nav_icon_px,
                ),
                self.tr("Zoom out"),
                self.tr("Click the map to zoom out."),
                self._on_nav_zoom_out,
            ),
            (
                "pan",
                _theme_or_tinted(
                    ["/mActionPan.svg"],
                    "tool_pan.svg",
                    colors.TEXT,
                    nav_icon_px,
                ),
                self.tr("Pan"),
                self.tr("Drag the map to pan."),
                self._on_nav_pan,
            ),
        )
        for key, icon, label, desc, slot in nav_defs:
            btn = QToolButton(self._footer_nav)
            btn.setObjectName("MapSearchNavBtn")
            btn.setAutoRaise(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setCheckable(True)
            btn.setFixedSize(dimensions.s(28), dimensions.s(28))
            btn.setIcon(icon)
            btn.setIconSize(QSize(nav_icon_px, nav_icon_px))
            keyboard_focus(btn)
            set_name(btn, label, desc)
            btn.setToolTip(desc)
            btn.clicked.connect(slot)
            self._nav_buttons[key] = btn
            self._nav_group.addButton(btn)
            nav_row.addWidget(btn)
        footer.addWidget(self._footer_nav, 0, Qt.AlignVCenter)
        self._footer = QWidget()
        self._footer.setObjectName("MapSearchFooter")
        self._footer.setLayout(footer)
        # Footer (scale + nav) is visible in full mode; compact/small hide it.

        search_layout.addWidget(self._copy_block)
        search_layout.addWidget(filters)
        search_layout.addWidget(self._find_block)
        search_layout.addWidget(self._footer)

        body_layout.addWidget(self._search_section)

        root.addLayout(header)
        root.addWidget(self._body)
        # Do not use SetMinAndMaxSize — it locks a stale tall sizeHint when
        # results clear, leaving blank glass above the header on the canvas.

        self.setMinimumWidth(dimensions.s(360))
        self.setMaximumWidth(dimensions.s(460))
        # Maximum height policy — overlay must shrink to contents, never fill
        # the map canvas viewport it is parented to.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        for widget in (
            self._body,
            self._search_section,
            self._find_block,
            self._panel_body,
            filters,
            self._copy_block,
        ):
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._copy_block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_field_heights()
        self._apply_copy_block_heights()
        self._apply_panel_collapsed(adjust=False)
        self._apply_view_mode(adjust=False)

        self._busy_stripe = _BusyEdgeStripe(self)
        self._busy_stripe.set_active(False)

    def _apply_field_heights(self) -> None:
        """Keep combos/name at a standard control height after stylesheet refresh."""
        height = max(40, dimensions.s(dimensions.MAP_SEARCH_FIELD_HEIGHT))
        for field in (
            getattr(self, "_groups", None),
            getattr(self, "_status", None),
            getattr(self, "_name", None),
        ):
            if field is None:
                continue
            try:
                field.setMinimumHeight(height)
                field.setMaximumHeight(16777215)
                field.setFixedHeight(height)
            except Exception:  # noqa: BLE001
                pass

    def _apply_copy_block_heights(self) -> None:
        """Lock title/hint height so status text swaps do not shake the overlay."""
        title = getattr(self, "_title", None)
        hint = getattr(self, "_hint", None)
        block = getattr(self, "_copy_block", None)
        if title is None or hint is None or block is None:
            return
        # Title stays one line; hint reserves three wrapped lines (legend copy).
        title_fm = title.fontMetrics()
        hint_fm = hint.fontMetrics()
        title_h = max(dimensions.s(22), int(title_fm.lineSpacing()) + 2)
        hint_h = max(dimensions.s(48), int(hint_fm.lineSpacing() * 3) + 2)
        title.setFixedHeight(title_h)
        hint.setFixedHeight(hint_h)
        spacing = 2
        try:
            layout = block.layout()
            if layout is not None:
                layout.setSpacing(2)
                spacing = int(layout.spacing())
        except Exception:  # noqa: BLE001
            spacing = 2
        block.setFixedHeight(title_h + hint_h + max(0, spacing))

    def selected_project_group_id(self) -> str:
        """Return combo data: ``all``, ``myProjectGroups``, or a group UUID."""
        data = self._groups.currentData()
        return str(data or "").strip() or _MY_GROUPS_DATA

    def selected_status(self) -> str:
        data = self._status.currentData()
        value = str(data or "").strip()
        return value or _STATUS_ALL

    def _mode_button(self, icon_name, label, description, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("MapSearchModeBtn")
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.StrongFocus)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setCheckable(True)
        btn.setProperty("tdei_icon", icon_name)
        icon_px = dimensions.s(18)
        btn.setFixedSize(dimensions.s(30), dimensions.s(30))
        btn.setIconSize(QSize(icon_px, icon_px))
        self._paint_mode_button(btn, active=False)
        keyboard_focus(btn)
        set_name(btn, label, description)
        btn.setToolTip(description)
        btn.clicked.connect(slot)
        return btn

    def _paint_mode_button(self, btn: QToolButton, *, active: bool) -> None:
        icon_name = str(btn.property("tdei_icon") or "").strip()
        if not icon_name:
            return
        icon_px = dimensions.s(18)
        color = colors.PRIMARY if active else colors.TEXT_SECONDARY
        btn.setIcon(
            tinted_icon(
                icon_name,
                color,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(icon_px, icon_px))
        tip = btn.toolTip()
        if icon_name == "view_compact.svg":
            tip = (
                self.tr("Compact — hide dataset search section")
                if not active
                else self.tr("Show dataset search section")
            )
        elif icon_name == "view_small.svg":
            tip = (
                self.tr("Small — title only")
                if not active
                else self.tr("Expand map search")
            )
        if tip:
            btn.setToolTip(tip)

    def _paint_close_button(self, btn: QToolButton) -> None:
        """Solid chip + bold red X so close stays visible on glass panels."""
        icon_px = dimensions.s(16)
        btn.setIcon(
            tinted_icon(
                "action_close.svg",
                colors.ERROR,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(icon_px, icon_px))
        btn.setFixedSize(dimensions.s(30), dimensions.s(30))
        btn.setAutoRaise(False)
        btn.setVisible(True)
        btn.raise_()

    def set_view_mode(self, mode: str) -> None:
        mode = (mode or _VIEW_FULL).strip().lower()
        if mode not in (_VIEW_FULL, _VIEW_COMPACT, _VIEW_SMALL):
            mode = _VIEW_FULL
        if mode == self._view_mode:
            self._refresh_mode_buttons()
            return
        self._view_mode = mode
        self._apply_view_mode(adjust=True)

    def _on_brand_clicked(self, *_args) -> None:
        # Map icon / title: collapse to small, or expand from small to full.
        if self._view_mode == _VIEW_SMALL:
            self.set_view_mode(_VIEW_FULL)
        else:
            self.set_view_mode(_VIEW_SMALL)

    def _on_compact_clicked(self, *_args) -> None:
        if self._view_mode == _VIEW_COMPACT:
            self.set_view_mode(_VIEW_FULL)
        else:
            self.set_view_mode(_VIEW_COMPACT)

    def _on_small_clicked(self, *_args) -> None:
        if self._view_mode == _VIEW_SMALL:
            self.set_view_mode(_VIEW_FULL)
        else:
            self.set_view_mode(_VIEW_SMALL)

    def _apply_view_mode(self, *, adjust: bool) -> None:
        mode = self._view_mode
        is_small = mode == _VIEW_SMALL
        is_compact = mode == _VIEW_COMPACT
        # Clear fixed size so mode-specific min/max width can apply.
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        # Small/compact: header only (close stays). Full: header + search body.
        self._body.setVisible(not is_small and not is_compact)
        self._search_section.setVisible(True)
        self._find_block.setVisible(True)
        self._compact_btn.setVisible(not is_small)
        self._small_btn.setVisible(not is_small)
        self._close.setVisible(True)
        root = self.layout()
        if is_small:
            self.setMinimumWidth(dimensions.s(168))
            self.setMaximumWidth(dimensions.s(260))
            if root is not None:
                root.setContentsMargins(8, 6, 8, 6)
                root.setSpacing(0)
        elif is_compact:
            self.setMinimumWidth(dimensions.s(260))
            self.setMaximumWidth(dimensions.s(360))
            if root is not None:
                root.setContentsMargins(10, 8, 10, 8)
                root.setSpacing(0)
        else:
            host_w = 0
            try:
                host = self._canvas or self.parentWidget()
                if host is not None:
                    host_w = int(host.width())
            except Exception:  # noqa: BLE001
                host_w = 0
            # Full mode: scale with the map; leave room for chrome / map.
            max_w = max(
                dimensions.s(420),
                min(dimensions.s(560), int(host_w * 0.42) if host_w else dimensions.s(520)),
            )
            self.setMinimumWidth(dimensions.s(360))
            self.setMaximumWidth(max_w)
            if root is not None:
                root.setContentsMargins(16, 12, 16, 12)
                root.setSpacing(8)
            self._apply_panel_collapsed(adjust=False)
        self._refresh_mode_buttons()
        self._paint_close_button(self._close)
        if is_small or is_compact:
            self._footer.hide()
        else:
            self._footer.show()
        if adjust:
            self._relayout()

    def _relayout(self) -> None:
        """Shrink/grow cleanly after show/hide — avoids leftover empty space."""
        for widget in (
            self._results,
            self._panel_body,
            self._find_block,
            self._search_section,
            self._body,
            self,
        ):
            try:
                widget.updateGeometry()
                layout = widget.layout()
                if layout is not None:
                    layout.activate()
            except Exception:  # noqa: BLE001
                pass
        self._reposition()

    def _fit_height_to_contents(self) -> int:
        """Height of packed contents — never the parent canvas viewport."""
        # Drop any sticky fixed/min height left over from a taller results state.
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        layout = self.layout()
        if layout is not None:
            try:
                layout.activate()
                # Prefer sizeHint so stylesheet padding/borders are included;
                # totalMinimumSize alone under-sizes QComboBox rows and clips them.
                hint = layout.totalSizeHint()
                minimum = layout.totalMinimumSize()
                height = 0
                if hint.isValid():
                    height = max(height, int(hint.height()))
                if minimum.isValid():
                    height = max(height, int(minimum.height()))
                if height > 0:
                    return height
            except Exception:  # noqa: BLE001
                pass
        hint = self.minimumSizeHint()
        if hint.isValid() and hint.height() > 0:
            return int(hint.height())
        hint = self.sizeHint()
        if hint.isValid() and hint.height() > 0:
            return int(hint.height())
        return self.height() or 1

    def _refresh_mode_buttons(self) -> None:
        compact = self._view_mode == _VIEW_COMPACT
        small = self._view_mode == _VIEW_SMALL
        self._compact_btn.setChecked(compact)
        self._small_btn.setChecked(small)
        self._paint_mode_button(self._compact_btn, active=compact)
        self._paint_mode_button(self._small_btn, active=small)
        if self._view_mode == _VIEW_SMALL:
            tip = self.tr("Expand map search")
        else:
            tip = self.tr("Collapse to title only")
        self._brand.setToolTip(tip)
        set_name(self._brand, self.tr("Map search"), tip)

    def name_filter(self) -> str:
        return (self._name.text() or "").strip()

    def set_name_suggestions(self, names: Sequence[str]) -> None:
        """Fill autocomplete from locally cached dataset display names."""
        cleaned = []
        seen = set()
        for raw in names or ():
            title = str(raw or "").strip()
            if not title:
                continue
            folded = title.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            cleaned.append(title)
        cleaned.sort(key=lambda value: value.casefold())
        self._name_model.setStringList(cleaned)

    def ignore_map_extent(self) -> bool:
        """True when search should not filter by the current map bbox."""
        if self.name_filter():
            return True
        return bool(self._ignore_extent.isChecked())

    def set_project_groups(
        self,
        groups: Sequence,
        *,
        selected_id: str = "",
        admin_mode: bool = False,
    ) -> None:
        """Populate combo: All + My Project Groups + *groups*.

        *selected_id* may be ``all``, ``myProjectGroups``, a group UUID, or
        empty (defaults to **All**). *admin_mode* is kept for callers but no
        longer changes the default selection.
        """
        wanted = (selected_id or "").strip() or _ALL_GROUPS_DATA
        self._syncing_groups = True
        self._groups.blockSignals(True)
        self._groups.clear()
        self._groups.addItem(self.tr("All"), _ALL_GROUPS_DATA)
        self._groups.addItem(self.tr("My Project Groups"), _MY_GROUPS_DATA)
        for group in groups or ():
            group_id = str(getattr(group, "id", "") or "").strip()
            if not group_id:
                continue
            name = str(getattr(group, "name", "") or "").strip() or group_id
            self._groups.addItem(name, group_id)
        index = self._groups.findData(wanted)
        if index < 0:
            index = self._groups.findData(_ALL_GROUPS_DATA)
        if index < 0:
            index = 0
        self._groups.setCurrentIndex(index)
        self._groups.blockSignals(False)
        self._syncing_groups = False
        tip = self.tr(
            "Filter map search by project group. "
            "All applies no group filter. "
            "My Project Groups includes all of your groups."
        )
        try:
            self._groups.setToolTip(tip)
        except Exception:  # noqa: BLE001
            pass

    def set_results(self, datasets: Sequence) -> None:
        """Show up to 10 results: name, dataset id, area available indicator."""
        new_ids = []
        for dataset in datasets or ():
            if len(new_ids) >= _RESULT_LIMIT:
                break
            dataset_id = str(getattr(dataset, "id", "") or "").strip()
            if dataset_id:
                new_ids.append(dataset_id)

        previous_ids = []
        selected_id = ""
        scroll = 0
        try:
            scroll = int(self._results.verticalScrollBar().value())
            current = self._results.currentItem()
            if current is not None:
                selected_id = str(current.data(Qt.UserRole) or "").strip()
            for i in range(self._results.count()):
                item = self._results.item(i)
                if item is None:
                    continue
                previous_ids.append(str(item.data(Qt.UserRole) or "").strip())
        except Exception:  # noqa: BLE001
            previous_ids = []

        # Same result set — keep widgets and scroll; only sync selection.
        # Rebuild when area availability changed or ⋮ menu is missing (upgrade).
        if new_ids == previous_ids and self._results.count() == len(new_ids):
            area_changed = False
            missing_menu = False
            try:
                for i, dataset in enumerate(datasets or ()):
                    if i >= self._results.count():
                        break
                    item = self._results.item(i)
                    if item is None:
                        continue
                    prev = bool(item.data(_HAS_AREA_ROLE))
                    if prev != self._dataset_has_area(dataset):
                        area_changed = True
                        break
                    row = self._results.itemWidget(item)
                    if row is None or row.findChild(
                        QToolButton, "MapSearchMoreButton"
                    ) is None:
                        missing_menu = True
                        break
            except Exception:  # noqa: BLE001
                area_changed = True
            if not area_changed and not missing_menu:
                if selected_id:
                    self.select_result(selected_id, ensure_visible=False)
                # Still collapse list height on a repeated empty payload.
                if not new_ids:
                    self._configure_results_height(False)
                    if self._view_mode == _VIEW_FULL:
                        self._relayout()
                return

        self._results.clear()
        shown = 0
        for dataset in datasets or ():
            if shown >= _RESULT_LIMIT:
                break
            dataset_id = str(getattr(dataset, "id", "") or "").strip()
            if not dataset_id:
                continue
            name = str(getattr(dataset, "name", "") or "").strip() or dataset_id
            status = str(getattr(dataset, "status", "") or "").strip()
            has_area = self._dataset_has_area(dataset)
            item = QListWidgetItem(self._results)
            item.setData(Qt.UserRole, dataset_id)
            item.setData(_HAS_AREA_ROLE, bool(has_area))
            item.setData(_STATUS_ROLE, status)
            item.setSizeHint(QSize(0, dimensions.s(48)))
            row = QWidget(self._results)
            row.setObjectName("MapSearchResultRow")
            outer = QHBoxLayout(row)
            outer.setContentsMargins(4, 4, 8, 4)
            outer.setSpacing(8)
            outer.addWidget(self._status_stripe(status), 0, Qt.AlignVCenter)
            outer.addWidget(
                self._area_indicator(has_area), 0, Qt.AlignVCenter
            )
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(1)
            title = QLabel(name)
            title.setObjectName("MapSearchResultName")
            title.setWordWrap(False)
            title.setFocusPolicy(Qt.NoFocus)
            title.setToolTip(name)
            sub = QLabel(dataset_id)
            sub.setObjectName("MapSearchResultId")
            sub.setWordWrap(False)
            sub.setFocusPolicy(Qt.NoFocus)
            sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
            sub.setToolTip(dataset_id)
            text_col.addWidget(title)
            text_col.addWidget(sub)
            outer.addLayout(text_col, 1)
            outer.addWidget(
                self._result_more_button(dataset_id, has_area),
                0,
                Qt.AlignVCenter,
            )
            self._results.addItem(item)
            self._results.setItemWidget(item, row)
            shown += 1
        previous = self._results_shown
        self._results_shown = shown
        self._configure_results_height(shown > 0 and not self._panel_collapsed)
        # Auto-expand once when the first results arrive.
        if shown > 0 and previous <= 0 and self._panel_collapsed:
            self.set_panel_collapsed(False)
        elif shown <= 0 and not self.name_filter() and not self._panel_collapsed:
            # Empty view: collapse the find panel so the bar doesn't keep a hole.
            self.set_panel_collapsed(True)
        else:
            self._refresh_panel_toggle()
            if self._view_mode == _VIEW_FULL:
                self._relayout()
            else:
                self.adjustSize()
        # Restore scroll + selection after rebuild.
        if selected_id and shown > 0:
            self.select_result(selected_id, ensure_visible=False)
            try:
                self._results.verticalScrollBar().setValue(scroll)
            except Exception:  # noqa: BLE001
                pass
        # Keep autocomplete fresh with names seen from the API.
        if shown > 0:
            existing = list(self._name_model.stringList() or [])
            merged = list(existing)
            seen = {item.casefold() for item in existing}
            for dataset in datasets or ():
                title = str(getattr(dataset, "name", "") or "").strip()
                if not title:
                    continue
                folded = title.casefold()
                if folded in seen:
                    continue
                seen.add(folded)
                merged.append(title)
            if len(merged) != len(existing):
                merged.sort(key=lambda value: value.casefold())
                self._name_model.setStringList(merged)

    def _configure_results_height(self, visible: bool) -> None:
        """Avoid leaving a blank hole when the results list is empty/hidden."""
        if visible:
            self._results.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Fixed
            )
            self._results.setMinimumHeight(dimensions.s(120))
            self._results.setMaximumHeight(dimensions.s(220))
            self._results.show()
        else:
            self._results.hide()
            self._results.setMinimumHeight(0)
            self._results.setMaximumHeight(0)
            self._results.setSizePolicy(
                QSizePolicy.Ignored, QSizePolicy.Ignored
            )

    def select_result(
        self, dataset_id: str, *, ensure_visible: bool = True
    ) -> None:
        """Highlight a result row without emitting dataset_selected."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            return
        self._results.blockSignals(True)
        try:
            match = None
            for i in range(self._results.count()):
                item = self._results.item(i)
                if item is None:
                    continue
                if str(item.data(Qt.UserRole) or "").strip() == dataset_id:
                    match = item
                    break
            if match is None:
                return
            self._results.setCurrentItem(match)
            if ensure_visible:
                self._results.scrollToItem(
                    match, QAbstractItemView.EnsureVisible
                )
        finally:
            self._results.blockSignals(False)

    @staticmethod
    def _dataset_has_area(dataset) -> bool:
        return raw_has_valid_dataset_area(getattr(dataset, "raw", None))

    def _status_stripe(self, status: str) -> QFrame:
        """Vertical status marker: purple = Publish, yellow = Pre-Release."""
        key = str(status or "").strip().casefold().replace("_", "-")
        if key in ("pre-release", "prerelease"):
            color = "#f5c518"
            tip = self.tr("Pre-Release")
        elif key == "publish":
            color = colors.PRIMARY
            tip = self.tr("Publish")
        else:
            color = colors.BORDER_STRONG
            tip = (status or "").strip() or self.tr("Unknown status")
        bar = QFrame(self)
        bar.setObjectName("MapSearchStatusStripe")
        bar.setFixedWidth(dimensions.s(4))
        bar.setMinimumHeight(dimensions.s(34))
        bar.setMaximumHeight(dimensions.s(40))
        bar.setFocusPolicy(Qt.NoFocus)
        bar.setToolTip(tip)
        bar.setAccessibleName(tip)
        bar.setStyleSheet(
            "QFrame#MapSearchStatusStripe {{"
            " background-color: {color};"
            " border: none;"
            " border-radius: 2px;"
            " }}".format(color=color)
        )
        return bar

    def _area_indicator(self, has_area: bool) -> QToolButton:
        """Green/red map icon — same language as the datasets table."""
        if has_area:
            tip = self.tr("Dataset area defined")
            color = colors.SUCCESS
            object_name = "MapSearchAreaOk"
        else:
            tip = self.tr("Dataset area not defined")
            color = colors.ERROR
            object_name = "MapSearchAreaWarning"
        btn = QToolButton(self)
        btn.setObjectName(object_name)
        btn.setCursor(Qt.ArrowCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAttribute(Qt.WA_MacShowFocusRect, False)
        btn.setAutoRaise(True)
        btn.setEnabled(False)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        size = dimensions.s(_AREA_ICON_SIZE)
        icon_px = dimensions.s(_AREA_ICON_PX)
        btn.setFixedSize(size, size)
        btn.setIcon(
            tinted_icon(
                "action_map.svg",
                color,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(btn),
            )
        )
        btn.setIconSize(QSize(icon_px, icon_px))
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

    def _result_more_button(
        self, dataset_id: str, has_area: bool
    ) -> QToolButton:
        """⋮ menu: download, and Add dataset area (only when area is missing)."""
        more = QToolButton(self)
        more.setObjectName("MapSearchMoreButton")
        more.setCursor(Qt.PointingHandCursor)
        more.setFocusPolicy(Qt.StrongFocus)
        more.setAttribute(Qt.WA_MacShowFocusRect, False)
        more.setAutoRaise(True)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setToolButtonStyle(Qt.ToolButtonIconOnly)
        size = dimensions.s(_MORE_BTN_SIZE)
        icon_px = dimensions.s(16)
        more.setFixedSize(size, size)
        more.setIcon(
            tinted_icon(
                "more_vert.svg",
                colors.TEXT_SECONDARY,
                size=icon_px,
                dpr=dimensions.device_pixel_ratio(more),
            )
        )
        more.setIconSize(QSize(icon_px, icon_px))
        more.setToolTip(self.tr("More actions"))
        set_name(
            more,
            self.tr("More actions"),
            self.tr(
                "Open actions for this dataset, such as download or add "
                "dataset area."
            ),
        )
        more.setStyleSheet(
            "QToolButton#MapSearchMoreButton {{"
            " background: {surface}; border: 1px solid {border};"
            " border-radius: 4px; padding: 0; }}"
            "QToolButton#MapSearchMoreButton:hover {{"
            " background: {alt}; border-color: {primary}; }}"
            "QToolButton#MapSearchMoreButton:focus {{"
            " border: 2px solid {focus}; }}"
            "QToolButton#MapSearchMoreButton::menu-indicator {{"
            " image: none; width: 0; }}".format(
                surface=colors.SURFACE,
                border=colors.BORDER,
                alt=colors.SURFACE_ALT,
                primary=colors.PRIMARY,
                focus=colors.FOCUS,
            )
        )
        menu = QMenu(more)
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(
            partial(self._fill_result_menu, menu, dataset_id, has_area)
        )
        self._fill_result_menu(menu, dataset_id, has_area)
        more.setMenu(menu)
        return more

    def set_download_state_provider(self, fn) -> None:
        """*fn(dataset_id)* → ``(label, enabled, tooltip)`` for the ⋮ menu."""
        self._download_state_fn = fn

    def _download_menu_state(self, dataset_id: str):
        fn = self._download_state_fn
        if callable(fn):
            try:
                label, enabled, tip = fn(dataset_id)
                return str(label), bool(enabled), str(tip or "")
            except Exception:  # noqa: BLE001
                pass
        return (
            self.tr("Download"),
            True,
            self.tr("Download OSW layers into the TDEI project group."),
        )

    def _fill_result_menu(self, menu: QMenu, dataset_id: str, has_area: bool) -> None:
        menu.clear()
        label, enabled, tip = self._download_menu_state(dataset_id)
        download = menu.addAction(label)
        download.setEnabled(enabled)
        if tip:
            download.setToolTip(tip)
        if enabled:
            download.triggered.connect(
                partial(self.download_requested.emit, dataset_id)
            )

        action = menu.addAction(self.tr("Add dataset area"))
        if has_area:
            action.setEnabled(False)
            action.setToolTip(
                self.tr("This dataset already has a dataset area.")
            )
        else:
            action.setToolTip(
                self.tr(
                    "Build a concave-hull dataset_area from local OSW layers, "
                    "update the metadata from the dataset API response, and "
                    "submit edit metadata."
                )
            )
            action.triggered.connect(
                partial(self.add_dataset_area_requested.emit, dataset_id)
            )

    def set_zoom_ok(self, ok: bool) -> None:
        self._zoom_ok = bool(ok)
        # Name / ignore-extent search stays usable when zoomed out.
        controls_ok = self._zoom_ok or self.ignore_map_extent()
        self.setStyleSheet(self._stylesheet(active=controls_ok))
        self._apply_field_heights()
        self._apply_copy_block_heights()
        self._paint_close_button(self._close)
        self._groups.setEnabled(True)
        self._status.setEnabled(True)
        self._name.setEnabled(True)
        self._ignore_extent.setEnabled(True)
        self._results.setEnabled(controls_ok or self._count > 0)
        self._refresh_copy()

    def set_busy(self, busy: bool, message: str = "") -> None:
        was_busy = self._busy
        self._busy = bool(busy)
        self._busy_message = str(message or "").strip() if self._busy else ""
        stripe = getattr(self, "_busy_stripe", None)
        if stripe is not None:
            stripe.set_active(self._busy)
        self._refresh_copy()
        # Text-only busy toggles must not relayout — height is locked in copy block.
        if was_busy != self._busy:
            stripe = getattr(self, "_busy_stripe", None)
            if stripe is not None:
                stripe.sync_to_parent()
                if self._busy:
                    stripe.raise_()

    def set_result_count(self, count: int) -> None:
        previous = self._count
        self._count = max(0, int(count))
        self._refresh_copy()
        # Empty ↔ non-empty copy changes wrap height; refit the overlay.
        if (previous > 0) != (self._count > 0) and self._view_mode == _VIEW_FULL:
            self._relayout()

    def set_scale_display(self, scale: float) -> None:
        if self._view_mode in (_VIEW_SMALL, _VIEW_COMPACT):
            self._footer.hide()
            return
        if scale and scale > 0:
            self._meta.setText(self.tr("Map scale 1:{:,.0f}").format(scale))
        else:
            self._meta.setText("")
        self._footer.show()

    def bind_iface(self, iface) -> None:
        """QGIS iface for zoom / pan map tools from the footer buttons."""
        self._iface = iface
        self._ensure_nav_tools()
        self._sync_nav_from_map_tool()

    def _map_canvas(self):
        if self._map_canvas_ref is not None:
            return self._map_canvas_ref
        iface = self._iface
        if iface is not None:
            try:
                return iface.mapCanvas()
            except Exception:  # noqa: BLE001
                pass
        return None

    def _ensure_nav_tools(self) -> None:
        """Keep owned map tools so QGIS does not GC them after setMapTool."""
        canvas = self._map_canvas()
        if canvas is None:
            return
        if getattr(self, "_nav_tools", None) is None:
            self._nav_tools = {}
        try:
            from qgis.gui import QgsMapToolPan, QgsMapToolZoom
        except Exception:  # noqa: BLE001
            return
        if "pan" not in self._nav_tools:
            self._nav_tools["pan"] = QgsMapToolPan(canvas)
        if "zoom_in" not in self._nav_tools:
            self._nav_tools["zoom_in"] = QgsMapToolZoom(canvas, False)
        if "zoom_out" not in self._nav_tools:
            self._nav_tools["zoom_out"] = QgsMapToolZoom(canvas, True)

    def _on_nav_zoom_in(self) -> None:
        if self._nav_syncing:
            return
        self._activate_nav_tool("zoom_in")

    def _on_nav_zoom_out(self) -> None:
        if self._nav_syncing:
            return
        self._activate_nav_tool("zoom_out")

    def _on_nav_pan(self) -> None:
        if self._nav_syncing:
            return
        self._activate_nav_tool("pan")

    def _activate_nav_tool(self, key: str) -> None:
        # Prefer QGIS's own actions (shared with the main toolbar).
        iface = self._iface
        action_name = {
            "zoom_in": "actionZoomIn",
            "zoom_out": "actionZoomOut",
            "pan": "actionPan",
        }.get(key)
        if iface is not None and action_name:
            try:
                getter = getattr(iface, action_name, None)
                if callable(getter):
                    action = getter()
                    if action is not None:
                        action.trigger()
                        self._set_nav_checked(key)
                        return
            except Exception:  # noqa: BLE001
                pass
        canvas = self._map_canvas()
        if canvas is None:
            return
        self._ensure_nav_tools()
        tool = (getattr(self, "_nav_tools", {}) or {}).get(key)
        if tool is None:
            return
        try:
            canvas.setMapTool(tool)
            self._set_nav_checked(key)
        except Exception:  # noqa: BLE001
            pass

    def _on_map_tool_set(self, *_args) -> None:
        self._sync_nav_from_map_tool()

    def _sync_nav_from_map_tool(self) -> None:
        canvas = self._map_canvas()
        if canvas is None:
            return
        try:
            tool = canvas.mapTool()
            if tool is None:
                self._clear_nav_checked()
                return
            owned = getattr(self, "_nav_tools", {}) or {}
            for key, owned_tool in owned.items():
                if tool is owned_tool:
                    self._set_nav_checked(key)
                    return

            # Prefer QGIS toolbar action checked state — reliable for Zoom Out
            # (native QgsMapToolZoom often does not expose mZoomOut to Python).
            iface = self._iface
            if iface is not None:
                try:
                    for key, getter_name in (
                        ("zoom_out", "actionZoomOut"),
                        ("zoom_in", "actionZoomIn"),
                        ("pan", "actionPan"),
                    ):
                        getter = getattr(iface, getter_name, None)
                        action = getter() if callable(getter) else None
                        if action is not None and action.isChecked():
                            self._set_nav_checked(key)
                            return
                except Exception:  # noqa: BLE001
                    pass

            name = type(tool).__name__.lower()
            if "pan" in name:
                self._set_nav_checked("pan")
                return
            if "zoom" in name:
                zoom_out = self._tool_is_zoom_out(tool)
                if zoom_out is None:
                    # Keep the last zoom direction instead of flipping to Zoom In.
                    last = getattr(self, "_nav_active_key", "") or ""
                    if last in ("zoom_in", "zoom_out"):
                        self._set_nav_checked(last)
                        return
                    zoom_out = False
                self._set_nav_checked("zoom_out" if zoom_out else "zoom_in")
                return
            self._clear_nav_checked()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _tool_is_zoom_out(tool) -> bool | None:
        """Return True/False when known, else None if direction is unavailable."""
        for attr in ("zoomOut", "mZoomOut", "isZoomOut", "m_zoomOut"):
            if not hasattr(tool, attr):
                continue
            try:
                val = getattr(tool, attr)
                return bool(val() if callable(val) else val)
            except Exception:  # noqa: BLE001
                continue
        # Some builds expose the ctor flag via property "zoomOutMode".
        try:
            if hasattr(tool, "property"):
                flagged = tool.property("zoomOut")
                if flagged is not None:
                    return bool(flagged)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _set_nav_checked(self, key: str) -> None:
        btn = self._nav_buttons.get(key)
        if btn is None:
            return
        self._nav_active_key = key
        self._nav_syncing = True
        try:
            btn.setChecked(True)
        finally:
            self._nav_syncing = False

    def _clear_nav_checked(self) -> None:
        self._nav_active_key = ""
        self._nav_syncing = True
        try:
            for btn in self._nav_buttons.values():
                btn.setChecked(False)
        finally:
            self._nav_syncing = False

    def _on_group_changed(self, *_args) -> None:
        if self._syncing_groups:
            return
        self.project_group_changed.emit(self.selected_project_group_id())

    def _on_status_changed(self, *_args) -> None:
        if self._syncing_status:
            return
        self.status_filter_changed.emit(self.selected_status())

    def _on_name_changed(self, *_args) -> None:
        name = self.name_filter()
        # Name search always ignores bbox — keep the checkbox in sync.
        # Clearing the name restores pan/bbox search (untick ignore extent).
        if name and not self._ignore_extent.isChecked():
            self._ignore_extent.blockSignals(True)
            self._ignore_extent.setChecked(True)
            self._ignore_extent.blockSignals(False)
        elif not name and self._ignore_extent.isChecked():
            self._ignore_extent.blockSignals(True)
            self._ignore_extent.setChecked(False)
            self._ignore_extent.blockSignals(False)
        if name and self._view_mode != _VIEW_FULL:
            self.set_view_mode(_VIEW_FULL)
        if name and self._panel_collapsed:
            self.set_panel_collapsed(False)
        else:
            self._refresh_panel_toggle()
        # Re-search after checkbox sync so empty name + unchecked = pan/bbox.
        self.name_filter_changed.emit(name)

    def _toggle_panel(self) -> None:
        self.set_panel_collapsed(not self._panel_collapsed)

    def set_panel_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        # Keep expanded while a name filter is active.
        if collapsed and self.name_filter():
            collapsed = False
        if collapsed == self._panel_collapsed:
            self._refresh_panel_toggle()
            return
        self._panel_collapsed = collapsed
        self._apply_panel_collapsed(adjust=True)

    def _apply_panel_collapsed(self, *, adjust: bool) -> None:
        collapsed = self._panel_collapsed
        self._panel_body.setVisible(not collapsed)
        # Zero height when collapsed so the layout does not leave a gap.
        if collapsed:
            self._panel_body.setMaximumHeight(0)
            self._panel_body.setMinimumHeight(0)
            self._configure_results_height(False)
        else:
            self._panel_body.setMaximumHeight(16777215)
            self._panel_body.setMinimumHeight(0)
            self._configure_results_height(self._results_shown > 0)
        try:
            find_layout = self._find_block.layout()
            if find_layout is not None:
                find_layout.setSpacing(0 if collapsed else 6)
            self._find_block.layout().activate()
            self._search_section.layout().activate()
        except Exception:  # noqa: BLE001
            pass
        self._refresh_panel_toggle()
        if adjust and self._view_mode == _VIEW_FULL:
            self._relayout()

    def _refresh_panel_toggle(self) -> None:
        name = self.name_filter()
        n = self._results_shown
        if self._panel_collapsed:
            if name and n > 0:
                label = self.tr("Find datasets · {q} ({n})").format(
                    q=name, n=n
                )
            elif name:
                label = self.tr("Find datasets · {q}").format(q=name)
            elif n > 0:
                label = self.tr("Find datasets ({n})").format(n=n)
            else:
                label = self.tr("Find datasets")
        else:
            label = (
                self.tr("Find datasets ({n})").format(n=n)
                if n > 0
                else self.tr("Find datasets")
            )
        self._paint_section_toggle(
            self._panel_toggle,
            collapsed=self._panel_collapsed,
            label=label,
            expand_tip=self.tr("Expand name search and results"),
            collapse_tip=self.tr("Collapse name search and results"),
        )

    def _paint_section_toggle(
        self,
        button: QToolButton,
        *,
        collapsed: bool,
        label: str,
        expand_tip: str,
        collapse_tip: str,
    ) -> None:
        dpr = dimensions.device_pixel_ratio(button)
        icon_px = dimensions.s(14)
        icon_name = (
            "sidebar_chevron_right.svg" if collapsed else "chevron_down.svg"
        )
        button.setIcon(
            tinted_icon(
                icon_name,
                colors.PRIMARY,
                size=icon_px,
                dpr=dpr,
            )
        )
        button.setIconSize(QSize(icon_px, icon_px))
        tip = expand_tip if collapsed else collapse_tip
        button.setText(label)
        button.setToolTip(tip)
        set_name(button, label, tip)

    def _on_ignore_extent_toggled(self, checked: bool) -> None:
        # Clearing the checkbox while a name is set is not allowed.
        if not checked and self.name_filter():
            self._ignore_extent.blockSignals(True)
            self._ignore_extent.setChecked(True)
            self._ignore_extent.blockSignals(False)
            return
        self.ignore_map_extent_changed.emit(bool(checked))
        self._refresh_copy()

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        """Single click — highlight the area on the map (no zoom)."""
        if item is None:
            return
        dataset_id = str(item.data(Qt.UserRole) or "").strip()
        if dataset_id:
            self.dataset_selected.emit(dataset_id)

    def _on_result_activated(self, item: QListWidgetItem) -> None:
        """Double-click / Enter — zoom the map to the dataset area."""
        if item is None:
            return
        dataset_id = str(item.data(Qt.UserRole) or "").strip()
        if dataset_id:
            self.dataset_zoom_requested.emit(dataset_id)

    def _refresh_copy(self) -> None:
        ignore = self.ignore_map_extent()
        if not self._zoom_ok and not ignore:
            self._title.setText(self.tr("Zoom in to search"))
            self._hint.setText(
                self.tr(
                    "Zoom closer (about 1:1.3M or larger) to search datasets "
                    "in this view, or check “Ignore map extent” / search by "
                    "name."
                )
            )
            return
        if self._busy:
            if self._busy_message:
                self._title.setText(self._busy_message)
                self._hint.setText(
                    self.tr("Please wait — this can take a little while.")
                )
            elif ignore:
                self._title.setText(self.tr("Searching by name…"))
                self._hint.setText(
                    self.tr(
                        "Fetching OSW datasets without limiting to the "
                        "map extent."
                    )
                )
            else:
                self._title.setText(self.tr("Searching this view…"))
                self._hint.setText(
                    self.tr(
                        "Fetching OSW datasets that overlap the map extent."
                    )
                )
            return
        if self._count <= 0:
            self._title.setText(
                self.tr("No datasets found")
                if ignore
                else self.tr("No datasets in this view")
            )
            self._hint.setText(
                self.tr(
                    "Try another name, or clear the name filter and use "
                    "the map view."
                )
                if ignore
                else self.tr(
                    "Try another name, pan, or zoom — results update when "
                    "the view settles."
                )
            )
            return
        self._title.setText(
            self.tr("{n} dataset(s) found").format(n=self._count)
            if ignore
            else self.tr("{n} dataset(s) in view").format(n=self._count)
        )
        self._hint.setText(
            self.tr(
                "Green map = area defined, red = missing. "
                "Use ⋮ to add a missing area. "
                "Click a result to highlight; double-click to zoom."
            )
        )

    def position_on_canvas(self, canvas: QWidget) -> None:
        """Attach to the map canvas viewport so the bar stays with the view."""
        if canvas is None:
            return
        scroll = 0
        try:
            scroll = int(self._results.verticalScrollBar().value())
        except Exception:  # noqa: BLE001
            scroll = 0
        # QgsMapCanvas is a QGraphicsView — overlay must live on the viewport.
        host = canvas
        try:
            viewport = canvas.viewport()
            if viewport is not None:
                host = viewport
        except Exception:  # noqa: BLE001
            host = canvas
        if self._canvas is not host:
            if self._canvas is not None:
                try:
                    self._canvas.removeEventFilter(self)
                except Exception:  # noqa: BLE001
                    pass
            self._canvas = host
            if self.parent() is not host:
                self.setParent(host)
            host.installEventFilter(self)
        if self._map_canvas_ref is not canvas:
            if self._map_canvas_ref is not None:
                try:
                    self._map_canvas_ref.mapToolSet.disconnect(
                        self._on_map_tool_set
                    )
                except Exception:  # noqa: BLE001
                    pass
            self._map_canvas_ref = canvas
            try:
                canvas.mapToolSet.connect(self._on_map_tool_set)
            except Exception:  # noqa: BLE001
                pass
        self._reposition()
        self.raise_()
        self.show()
        self._sync_nav_from_map_tool()
        try:
            self._results.verticalScrollBar().setValue(scroll)
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

    def _reposition(self) -> None:
        width = max(self.minimumWidth(), min(self.maximumWidth(), self.sizeHint().width()))
        height = self._fit_height_to_contents()
        # Fixed size so Expanding children cannot stretch us to the canvas.
        self.setFixedWidth(width)
        self.setFixedHeight(height)
        margin = dimensions.s(16)
        self.move(margin, margin)
        stripe = getattr(self, "_busy_stripe", None)
        if stripe is not None:
            stripe.sync_to_parent()
            if self._busy:
                stripe.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        stripe = getattr(self, "_busy_stripe", None)
        if stripe is not None:
            stripe.sync_to_parent()
            if self._busy:
                stripe.raise_()

    def eventFilter(self, obj, event) -> bool:
        from qgis.PyQt.QtCore import QEvent

        if obj is self._eyebrow and event is not None:
            if event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    self._on_brand_clicked()
                    return True
        if obj is self._canvas and event is not None:
            etype = event.type()
            if etype in (QEvent.Resize, QEvent.Show, QEvent.Move):
                self._reposition()
                self.raise_()
            # Wheel over the overlay must not zoom the map (nav tools / canvas).
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

    def hideEvent(self, event) -> None:
        # Do not detach here — setParent()/temporary hide clears hooks and
        # caused Python errors when reopening or clicking the map search bar.
        super().hideEvent(event)

    def detach_from_canvas(self) -> None:
        if self._canvas is not None:
            try:
                self._canvas.removeEventFilter(self)
            except Exception:  # noqa: BLE001
                pass
            self._canvas = None
        if self._map_canvas_ref is not None:
            try:
                self._map_canvas_ref.mapToolSet.disconnect(self._on_map_tool_set)
            except Exception:  # noqa: BLE001
                pass
            self._map_canvas_ref = None
        self._nav_tools = {}

    @staticmethod
    def _stylesheet(*, active: bool) -> str:
        accent = colors.PRIMARY if active else colors.TEXT_MUTED
        return """
            QFrame#MapSearchBar {{
                background-color: {glass};
                border: 1px solid {glass_border};
                border-left: 4px solid {accent};
                border-radius: {radius_lg}px;
            }}
            QLabel#MapSearchEyebrow {{
                color: {accent};
                font-size: {fs_xs}px;
                font-weight: {fw_semi};
                letter-spacing: 0.06em;
            }}
            QToolButton#MapSearchBrand {{
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QToolButton#MapSearchBrand:hover {{
                background-color: rgba(50, 0, 110, 0.08);
                border-radius: {radius_sm}px;
            }}
            QToolButton#MapSearchModeBtn {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: {radius_sm}px;
                padding: 2px;
            }}
            QToolButton#MapSearchModeBtn:hover {{
                background-color: rgba(50, 0, 110, 0.08);
            }}
            QToolButton#MapSearchModeBtn:checked {{
                background-color: rgba(50, 0, 110, 0.12);
                border: 1px solid {accent};
            }}
            QToolButton#MapSearchCloseBtn {{
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(198, 40, 40, 0.45);
                border-radius: {radius_sm}px;
                padding: 2px;
            }}
            QToolButton#MapSearchCloseBtn:hover {{
                background-color: rgba(198, 40, 40, 0.16);
                border-color: {error};
            }}
            QToolButton#MapSearchCloseBtn:pressed {{
                background-color: rgba(198, 40, 40, 0.24);
            }}
            QLabel#MapSearchTitle {{
                color: {text};
                font-size: {fs_md}px;
                font-weight: {fw_semi};
                margin: 0;
                padding: 0;
            }}
            QLabel#MapSearchHint {{
                color: {muted};
                font-size: {fs_sm}px;
                margin: 0;
                padding: 0;
            }}
            QLabel#MapSearchLabel {{
                color: {muted};
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
            }}
            QLabel#MapSearchMeta {{
                color: {secondary};
                font-size: {fs_sm}px;
                font-family: Menlo, Monaco, monospace;
            }}
            QToolButton#MapSearchNavBtn {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: {radius_sm}px;
                padding: 1px;
            }}
            QToolButton#MapSearchNavBtn:hover {{
                background-color: rgba(50, 0, 110, 0.08);
            }}
            QToolButton#MapSearchNavBtn:checked {{
                background-color: rgba(50, 0, 110, 0.12);
                border: 1px solid {accent};
            }}
            QLabel#MapSearchResultName {{
                color: {text};
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
                background: transparent;
                border: none;
            }}
            QLabel#MapSearchResultId {{
                color: {muted};
                font-size: {fs_xs}px;
                background: transparent;
                border: none;
            }}
            QLineEdit#MapSearchName {{
                min-height: {field_h}px;
                max-height: {field_h}px;
                padding: 0px 12px;
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
            }}
            QLineEdit#MapSearchName:disabled {{
                color: {muted};
                background-color: {bg};
            }}
            QLineEdit#MapSearchName:focus {{
                border: 2px solid {accent};
            }}
            QComboBox#MapSearchCombo {{
                min-height: {field_h}px;
                max-height: {field_h}px;
                min-width: 0;
                padding: 0px 12px;
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
            }}
            QComboBox#MapSearchCombo:disabled {{
                color: {muted};
                background-color: {bg};
            }}
            QComboBox#MapSearchCombo:focus {{
                border: 2px solid {accent};
            }}
            QComboBox#MapSearchCombo::drop-down {{
                border: none;
                width: 28px;
            }}
            QComboBox#MapSearchCombo::down-arrow {{
                width: 12px;
                height: 12px;
            }}
            QListWidget#MapSearchResults {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                outline: none;
                padding: 2px;
            }}
            QListWidget#MapSearchResults::item {{
                background: transparent;
                border-radius: {radius_sm}px;
                margin: 1px 0;
            }}
            QListWidget#MapSearchResults::item:selected {{
                background-color: rgba(50, 0, 110, 0.10);
            }}
            QListWidget#MapSearchResults::item:hover {{
                background-color: rgba(50, 0, 110, 0.06);
            }}
            QCheckBox#MapSearchIgnoreExtent {{
                color: {text};
                font-size: {fs_sm}px;
                spacing: 8px;
            }}
            QCheckBox#MapSearchIgnoreExtent::indicator {{
                width: 16px;
                height: 16px;
            }}
            QToolButton#MapSearchSectionToggle {{
                color: {accent};
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
                background: transparent;
                border: none;
                padding: 2px 0;
                text-align: left;
            }}
            QToolButton#MapSearchSectionToggle:hover {{
                color: {text};
            }}
            QToolButton#MapSearchSectionToggle:focus {{
                border: 1px solid {accent};
                border-radius: {radius_sm}px;
                padding: 2px 4px;
            }}
        """.format(
            glass=colors.GLASS_SURFACE,
            glass_border=colors.GLASS_BORDER_EDGE,
            surface=colors.GLASS_SURFACE_SOLID,
            bg=colors.GLASS_SURFACE_ALT,
            border=colors.GLASS_BORDER_EDGE,
            accent=accent,
            error=colors.ERROR,
            text=colors.TEXT if active else colors.TEXT_MUTED,
            muted=colors.TEXT_MUTED,
            secondary=colors.TEXT_SECONDARY,
            radius_lg=dimensions.RADIUS_LG,
            radius=dimensions.RADIUS_MD,
            radius_sm=dimensions.RADIUS_SM,
            ctrl=dimensions.s(dimensions.CONTROL_HEIGHT),
            field_h=max(40, dimensions.s(dimensions.MAP_SEARCH_FIELD_HEIGHT)),
            fs_xs=typography.FONT_SIZE_XS,
            fs_sm=typography.FONT_SIZE_SM,
            fs_md=typography.FONT_SIZE_MD,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
        )
