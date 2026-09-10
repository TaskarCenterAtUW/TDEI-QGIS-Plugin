# -*- coding: utf-8 -*-
"""Themed job form dialog for layer-menu operations."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.models import JobDefinition, JobField
from ...features.jobs.service import PENDING_OSW_ZIP
from ..a11y import keyboard_focus
from ..components import PrimaryButton, SecondaryButton
from ..styles import colors, dimensions, typography
from ..styles.theme import theme

# OpenAPI descriptions often append job-tracking boilerplate after this.
_TRACKING_MARKERS = (
    "The response includes a job_id",
    "The convert request has been accepted",
    "The validate request has been accepted",
    "To check the request status",
)


def _clean_openapi_text(text: str) -> str:
    """Make OpenAPI summary/description readable in the UI."""
    if not text:
        return ""
    cleaned = text.replace("`", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Spec sometimes omits space after sentence end: "converted.Supported"
    cleaned = re.sub(r"\.([A-Z])", r". \1", cleaned)
    cleaned = re.sub(r",([^\s])", r", \1", cleaned)
    return cleaned.strip()


def _user_facing_operation_description(operation: Optional[Dict[str, Any]]) -> str:
    """First user-facing paragraph from the OpenAPI operation description."""
    raw = _clean_openapi_text((operation or {}).get("description") or "")
    if not raw:
        return ""
    lower = raw.lower()
    cut = len(raw)
    for marker in _TRACKING_MARKERS:
        idx = lower.find(marker.lower())
        if idx >= 0:
            cut = min(cut, idx)
    text = raw[:cut].strip(" .")
    return (text + ".") if text else ""


def _field_label_text(field: JobField) -> str:
    return field.name.replace("_", " ")


class JobFormDialog(QDialog):
    """Grid-based form: label | field | optional action — a11y-friendly."""

    LABEL_COL = 0
    FIELD_COL = 1
    ACTION_COL = 2

    def __init__(
        self,
        job: JobDefinition,
        fields: List[JobField],
        parent=None,
        *,
        subtitle: str = "",
    ) -> None:
        super().__init__(parent)
        title = job.title or self.tr("TDEI Job")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(dimensions.s(560))
        self.resize(dimensions.s(620), dimensions.s(420))
        self.setStyleSheet(theme.application_stylesheet() + self._dialog_extra())
        self._fields = fields
        self._widgets: Dict[str, Any] = {}
        self._file_rows: Dict[str, _FileField] = {}
        self._focus_chain: List[QWidget] = []
        self._first_focus: Optional[QWidget] = None

        operation = job.operation or {}
        summary = _clean_openapi_text(
            subtitle or operation.get("summary") or ""
        )
        description = _user_facing_operation_description(operation)
        dialog_help = " ".join(
            part for part in (summary, description) if part
        ).strip()

        self.setAccessibleName(title)
        if dialog_help:
            self.setAccessibleDescription(dialog_help)
            self.setWhatsThis(dialog_help)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(0)

        heading = QLabel(title)
        heading.setObjectName("JobFormTitle")
        heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        heading.setFocusPolicy(Qt.NoFocus)
        heading.setAccessibleName(title)
        root.addWidget(heading)

        if summary and summary.lower() != title.lower():
            summary_label = QLabel(summary)
            summary_label.setObjectName("JobFormSubtitle")
            summary_label.setWordWrap(True)
            summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            summary_label.setFocusPolicy(Qt.NoFocus)
            summary_label.setAccessibleName(self.tr("Summary"))
            summary_label.setAccessibleDescription(summary)
            root.addSpacing(4)
            root.addWidget(summary_label)

        if description and description.lower() != summary.lower():
            desc_label = QLabel(description)
            desc_label.setObjectName("JobFormDescription")
            desc_label.setWordWrap(True)
            desc_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            desc_label.setFocusPolicy(Qt.NoFocus)
            desc_label.setAccessibleName(self.tr("Description"))
            desc_label.setAccessibleDescription(description)
            root.addSpacing(6)
            root.addWidget(desc_label)

        root.addSpacing(16)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(self.LABEL_COL, dimensions.s(120))
        grid.setColumnStretch(self.FIELD_COL, 1)
        grid.setColumnMinimumWidth(self.ACTION_COL, dimensions.s(96))

        row = 0
        for field in fields:
            row = self._add_field_row(grid, row, field)

        root.addLayout(grid)
        root.addSpacing(20)
        root.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel = SecondaryButton(self.tr("Cancel"))
        cancel.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
        cancel.setMinimumWidth(dimensions.s(100))
        cancel.setAccessibleName(self.tr("Cancel"))
        cancel.setAccessibleDescription(
            self.tr("Close this dialog without running the job.")
        )
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)

        submit = PrimaryButton(self.tr("Run job"))
        submit.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
        submit.setMinimumWidth(dimensions.s(110))
        submit.setAccessibleName(self.tr("Run job"))
        submit.setAccessibleDescription(
            self.tr("Submit the form and start the {} job.").format(title)
        )
        submit.setDefault(True)
        submit.clicked.connect(self.accept)

        actions.addWidget(cancel)
        actions.addWidget(submit)
        root.addLayout(actions)

        self._focus_chain.extend([cancel, submit])
        self._apply_tab_order()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        target = self._first_focus
        if target is not None and target.isEnabled():
            target.setFocus(Qt.OtherFocusReason)

    def _apply_tab_order(self) -> None:
        chain = [w for w in self._focus_chain if w is not None]
        for prev, nxt in zip(chain, chain[1:]):
            QWidget.setTabOrder(prev, nxt)
        if chain:
            self._first_focus = chain[0]

    def _accessible_field_name(self, field: JobField) -> str:
        name = _field_label_text(field)
        if field.required:
            return self.tr("{} (required)").format(name)
        return name

    def _add_field_row(self, grid: QGridLayout, row: int, field: JobField) -> int:
        label = self._label(field)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setContentsMargins(0, 8, 0, 0)
        grid.addWidget(label, row, self.LABEL_COL, Qt.AlignLeft | Qt.AlignTop)

        a11y_name = self._accessible_field_name(field)
        hint_text = self._field_hint(field)

        if field.format == "binary":
            file_field = _FileField(self)
            if field.value == PENDING_OSW_ZIP:
                file_field.set_pending_package("osw_upload.zip")
            elif field.value:
                file_field.set_path(str(field.value))
            tip = _clean_openapi_text(field.description or "")
            if tip:
                file_field.setToolTip(tip)
            file_field.apply_accessibility(a11y_name, hint_text)
            label.setBuddy(file_field.name_edit)
            self._widgets[field.name] = file_field
            self._file_rows[field.name] = file_field

            grid.addWidget(file_field.name_edit, row, self.FIELD_COL)
            grid.addWidget(file_field.browse_btn, row, self.ACTION_COL)
            self._focus_chain.extend(
                [file_field.name_edit, file_field.browse_btn]
            )
        else:
            widget = self._make_simple_widget(field, a11y_name, hint_text)
            label.setBuddy(widget)
            self._widgets[field.name] = widget
            grid.addWidget(widget, row, self.FIELD_COL, 1, 2)
            self._focus_chain.append(widget)

        if hint_text:
            hint = QLabel(hint_text)
            hint.setObjectName("JobFormHint")
            hint.setWordWrap(True)
            hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
            hint.setFocusPolicy(Qt.NoFocus)
            hint.setAccessibleName(
                self.tr("Help for {}").format(_field_label_text(field))
            )
            hint.setAccessibleDescription(hint_text)
            grid.addWidget(hint, row + 1, self.FIELD_COL, 1, 2)
            return row + 2
        return row + 1

    def _field_hint(self, field: JobField) -> str:
        parts: List[str] = []
        desc = _clean_openapi_text(field.description or "")
        if desc:
            parts.append(desc)
        if field.format == "binary" and field.value == PENDING_OSW_ZIP:
            parts.append(
                self.tr(
                    "Selected file(s) will be zipped and uploaded as part of "
                    "the request."
                )
            )
        return "\n".join(parts)

    def _label(self, field: JobField) -> QLabel:
        visible = _field_label_text(field)
        if field.required:
            visible += " *"
        label = QLabel(visible)
        label.setObjectName("JobFormLabel")
        label.setFocusPolicy(Qt.NoFocus)
        tip = _clean_openapi_text(field.description or "")
        if tip:
            label.setToolTip(tip)
        # Screen readers use the buddy control's name; label stays visual.
        label.setAccessibleName(_field_label_text(field))
        if field.required:
            label.setAccessibleDescription(self.tr("Required field"))
        return label

    def _make_simple_widget(
        self, field: JobField, a11y_name: str, hint_text: str
    ) -> QWidget:
        if field.enum:
            widget = QComboBox(self)
            widget.setObjectName("JobFormInput")
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            widget.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
            keyboard_focus(widget)
            if not field.required:
                widget.addItem("", "")
            for item in field.enum:
                widget.addItem(str(item), item)
        elif field.type == "boolean":
            widget = QCheckBox(self)
            keyboard_focus(widget)
        else:
            widget = QLineEdit(self)
            widget.setObjectName("JobFormInput")
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            widget.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
            keyboard_focus(widget)
            if field.name == "bbox":
                widget.setPlaceholderText("west,south,east,north")
            elif field.type == "array":
                widget.setPlaceholderText("comma-separated values")
            elif field.type in ("number", "integer"):
                widget.setPlaceholderText(str(field.type))
        if field.value not in (None, "", PENDING_OSW_ZIP):
            self._set_value(widget, field, field.value)

        widget.setAccessibleName(a11y_name)
        if hint_text:
            widget.setAccessibleDescription(hint_text)
            widget.setToolTip(hint_text)
            widget.setWhatsThis(hint_text)
        return widget

    @staticmethod
    def _set_value(widget, field: JobField, value) -> None:
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index < 0:
                index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QLineEdit):
            if isinstance(value, list):
                widget.setText(",".join(str(item) for item in value))
            else:
                widget.setText(str(value))

    def values(self) -> Dict[str, Any]:
        return {field.name: self._read(field) for field in self._fields}

    def _read(self, field: JobField):
        widget = self._widgets[field.name]
        if isinstance(widget, _FileField):
            return widget.value()
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentText()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return widget.text().strip()

    def accept(self) -> None:
        missing = [
            field.name
            for field in self._fields
            if field.required and self._read(field) in (None, "")
        ]
        if missing:
            QMessageBox.warning(
                self,
                self.tr("TDEI Job"),
                self.tr(
                    "Required fields are missing: {}. "
                    "Fill them in, then run the job again."
                ).format(", ".join(missing)),
            )
            # Move focus to the first missing control.
            for field in self._fields:
                if field.name in missing:
                    widget = self._widgets.get(field.name)
                    target = (
                        widget.name_edit
                        if isinstance(widget, _FileField)
                        else widget
                    )
                    if target is not None:
                        target.setFocus(Qt.OtherFocusReason)
                    break
            return
        super().accept()

    @staticmethod
    def _dialog_extra() -> str:
        return """
            QDialog {{
                background-color: {surface};
            }}
            QLabel#JobFormTitle {{
                color: {text};
                font-size: {fs_lg}px;
                font-weight: {fw_semi};
            }}
            QLabel#JobFormSubtitle {{
                color: {text};
                font-size: {fs_sm}px;
                font-weight: {fw_medium};
            }}
            QLabel#JobFormDescription {{
                color: {text_secondary};
                font-size: {fs_sm}px;
            }}
            QLabel#JobFormLabel {{
                color: {text};
                font-size: {fs_sm}px;
                font-weight: {fw_semi};
            }}
            QLabel#JobFormHint {{
                color: {text_secondary};
                font-size: {fs_sm}px;
                padding-top: 0px;
                padding-bottom: 4px;
            }}
            QLineEdit#JobFormInput:focus, QComboBox#JobFormInput:focus {{
                border: 2px solid {focus};
            }}
            QPushButton#JobBrowseButton {{
                min-height: {ctrl}px;
                max-height: {ctrl}px;
                min-width: 88px;
                padding: 0 12px;
                color: {primary};
                background-color: {surface};
                border: 1px solid {border_strong};
                border-radius: {radius}px;
                font-size: {fs_sm}px;
                font-weight: {fw_medium};
            }}
            QPushButton#JobBrowseButton:hover {{
                background-color: {surface_alt};
                border-color: {primary};
            }}
            QPushButton#JobBrowseButton:focus {{
                border: 2px solid {focus};
            }}
            QPushButton#PrimaryButton:focus {{
                border: 2px solid {primary_light};
            }}
            QPushButton#SecondaryButton:focus {{
                border: 2px solid {focus};
            }}
        """.format(
            surface=colors.SURFACE,
            surface_alt=colors.SURFACE_ALT,
            text=colors.TEXT,
            text_secondary=colors.TEXT_SECONDARY,
            primary=colors.PRIMARY,
            primary_light=colors.PRIMARY_LIGHT,
            border_strong=colors.BORDER_STRONG,
            focus=colors.FOCUS,
            fs_sm=typography.FONT_SIZE_SM,
            fs_lg=typography.FONT_SIZE_LG,
            fw_medium=typography.FONT_WEIGHT_MEDIUM,
            fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
            ctrl=dimensions.s(dimensions.CONTROL_HEIGHT),
            radius=dimensions.s(dimensions.RADIUS_MD),
        )


class _FileField(object):
    """Path state plus grid-placed name edit and browse button."""

    def __init__(self, parent: QWidget) -> None:
        self._pending = False
        self._path = ""
        self._field_name = "file"

        self.name_edit = QLineEdit(parent)
        self.name_edit.setObjectName("JobFormInput")
        self.name_edit.setReadOnly(True)
        self.name_edit.setPlaceholderText("osw_upload.zip")
        self.name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.name_edit.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
        keyboard_focus(self.name_edit)

        self.browse_btn = QPushButton(parent.tr("Browse…"), parent)
        self.browse_btn.setObjectName("JobBrowseButton")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setFixedHeight(dimensions.s(dimensions.CONTROL_HEIGHT))
        self.browse_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        keyboard_focus(self.browse_btn)
        self.browse_btn.setAutoDefault(False)
        self.browse_btn.clicked.connect(self._browse)

    def apply_accessibility(self, field_name: str, hint_text: str) -> None:
        self._field_name = field_name
        self.name_edit.setAccessibleName(field_name)
        if hint_text:
            self.name_edit.setAccessibleDescription(hint_text)
            self.name_edit.setWhatsThis(hint_text)
        self.browse_btn.setAccessibleName(
            self.browse_btn.tr("Browse for {}").format(field_name)
        )
        self.browse_btn.setAccessibleDescription(
            self.browse_btn.tr(
                "Choose a package file to upload instead of the default."
            )
        )

    def setToolTip(self, text: str) -> None:
        self.name_edit.setToolTip(text or "")

    def set_pending_package(self, display_name: str) -> None:
        self._pending = True
        self._path = ""
        self.name_edit.setText(display_name or "osw_upload.zip")
        tip = (
            "Package will be created from the mapped layers when you run "
            "the job. Browse to use a different zip instead."
        )
        self.name_edit.setToolTip(tip)
        self.name_edit.setAccessibleDescription(tip)

    def set_path(self, path: str) -> None:
        self._pending = False
        self._path = path or ""
        basename = os.path.basename(self._path) if self._path else ""
        self.name_edit.setText(basename)
        self.name_edit.setToolTip(self._path)
        if self._path:
            self.name_edit.setAccessibleDescription(
                "Selected file: {}".format(self._path)
            )

    def value(self) -> str:
        if self._pending and not self._path:
            return PENDING_OSW_ZIP
        return self._path

    def _browse(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self.name_edit.window(),
            self.browse_btn.tr("Select package for {}").format(
                self._field_name
            ),
            "",
            "Packages (*.zip *.pbf *.osm *.xml);;All files (*)",
        )
        if chosen:
            self.set_path(chosen)
            self.name_edit.setFocus(Qt.OtherFocusReason)
