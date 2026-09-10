# -*- coding: utf-8 -*-
"""Dynamic Qt form generated from an OpenAPI job operation."""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class JobFormDialog(QDialog):
    """One widget per OpenAPI field for the selected job."""

    def __init__(self, job, fields, parent=None):
        super(JobFormDialog, self).__init__(parent)
        self.setWindowTitle(job.get('title') or 'TDEI Job')
        self.resize(480, 220)
        self._fields = fields
        self._widgets = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(job.get('title') or ''))
        form = QFormLayout()
        for field in fields:
            form.addRow(self._label(field), self._make_widget(field))
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        result = {}
        for field in self._fields:
            result[field['name']] = self._read(field)
        return result

    def _label(self, field):
        text = field['name'].replace('_', ' ')
        if field['required']:
            text += ' *'
        return text

    def _make_widget(self, field):
        if field.get('format') == 'binary':
            widget = _FileRow(self)
            if field.get('value'):
                widget.set_path(field['value'])
        elif field.get('enum'):
            widget = QComboBox(self)
            if not field['required']:
                widget.addItem('', '')
            for item in field['enum']:
                widget.addItem(str(item), item)
        elif field['type'] == 'boolean':
            widget = QCheckBox(self)
        else:
            widget = QLineEdit(self)
            placeholder = field.get('description') or ''
            if field['name'] == 'bbox':
                placeholder = 'west,south,east,north'
            elif field['type'] == 'array':
                placeholder = placeholder or 'comma-separated values'
            if placeholder:
                widget.setPlaceholderText(placeholder[:120])
        if field.get('value') not in (None, '') and not isinstance(widget, _FileRow):
            self._set_value(widget, field, field['value'])
        if field.get('description'):
            widget.setToolTip(field['description'])
        self._widgets[field['name']] = widget
        return widget

    @staticmethod
    def _set_value(widget, field, value):
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
                widget.setText(','.join(str(item) for item in value))
            else:
                widget.setText(str(value))

    def _read(self, field):
        widget = self._widgets[field['name']]
        if isinstance(widget, _FileRow):
            return widget.path()
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentText()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return widget.text().strip()

    def accept(self):
        missing = []
        for field in self._fields:
            value = self._read(field)
            if field['required'] and value in (None, ''):
                missing.append(field['name'])
        if missing:
            QMessageBox.warning(
                self,
                'TDEI Job',
                'Required: {}'.format(', '.join(missing)))
            return
        super(JobFormDialog, self).accept()


class _FileRow(QWidget):
    def __init__(self, parent=None):
        super(_FileRow, self).__init__(parent)
        self._edit = QLineEdit(self)
        browse = QPushButton('Browse…', self)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._edit)
        row.addWidget(browse)

    def path(self):
        return self._edit.text().strip()

    def set_path(self, path):
        self._edit.setText(path or '')

    def _browse(self):
        chosen, _filter = QFileDialog.getOpenFileName(self, 'Select file')
        if chosen:
            self._edit.setText(chosen)
