# -*- coding: utf-8 -*-
"""Tag chips, inline editor, and mapped-list search with tag suggestions."""

from __future__ import annotations

from typing import List, Sequence

from qgis.PyQt.QtCore import (
    QPoint,
    QRect,
    QSize,
    QStringListModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ...features.mapped_tags.logic import MAX_TAGS_PER_ITEM, normalize_tag
from ..a11y import keyboard_focus, set_name


class FlowLayout(QLayout):
    """Left-to-right wrapping layout for tag chips."""

    def __init__(self, parent=None, *, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space
                next_x = x + hint.width() + space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class TagChip(QFrame):
    """Compact removable / clickable tag pill."""

    clicked = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(
        self,
        text: str,
        parent=None,
        *,
        removable: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TagChip")
        self._text = text
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4 if removable else 8, 2)
        row.setSpacing(2)
        label = QLabel(text)
        label.setObjectName("TagChipLabel")
        label.setFocusPolicy(Qt.NoFocus)
        row.addWidget(label)
        if removable:
            close = QToolButton()
            close.setObjectName("TagChipClose")
            close.setAutoRaise(True)
            close.setCursor(Qt.PointingHandCursor)
            close.setText("×")
            close.setFixedSize(16, 16)
            close.setToolTip("Remove tag")
            close.setAccessibleName("Remove {}".format(text))
            keyboard_focus(close)
            close.clicked.connect(lambda: self.removed.emit(self._text))
            row.addWidget(close)
        self.setToolTip(text)
        set_name(self, "Tag {}".format(text), "Filter or edit this tag.")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.pos())
            if child is None or not isinstance(child, QToolButton):
                self.clicked.emit(self._text)
        super().mousePressEvent(event)


class TagEditor(QWidget):
    """Inline chips + typeahead field for tags on a mapped row."""

    tags_changed = pyqtSignal(list)
    tag_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TagEditor")
        self._tags: List[str] = []
        self._catalog: List[str] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(4)

        self._chips = QWidget()
        self._flow = FlowLayout(self._chips, spacing=4)
        self._chips.setLayout(self._flow)
        self._chips.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addWidget(self._chips, 1)

        self._input = QLineEdit()
        self._input.setObjectName("TagAddInput")
        self._input.setPlaceholderText("Add tag")
        self._input.setFixedWidth(108)
        self._input.setClearButtonEnabled(False)
        keyboard_focus(self._input)
        set_name(
            self._input,
            "Add tag",
            "Type a tag. Suggestions appear from tags already in use.",
        )
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        try:
            self._completer.setFilterMode(Qt.MatchContains)
        except Exception:
            pass
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._input.setCompleter(self._completer)
        self._input.returnPressed.connect(self._commit)
        try:
            self._completer.activated[str].connect(self._accept_completion)
        except (TypeError, KeyError, AttributeError):
            self._completer.activated.connect(self._accept_completion)
        layout.addWidget(self._input, 0, Qt.AlignTop)

    def tags(self) -> List[str]:
        return list(self._tags)

    def set_tags(self, tags: Sequence[str]) -> None:
        self._tags = list(tags)
        self._rebuild()
        self._refresh_completer()

    def set_catalog(self, tags: Sequence[str]) -> None:
        self._catalog = list(tags)
        self._refresh_completer()

    def _rebuild(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for tag in self._tags:
            chip = TagChip(tag)
            chip.clicked.connect(self.tag_clicked.emit)
            chip.removed.connect(self._remove)
            self._flow.addWidget(chip)
        full = len(self._tags) >= MAX_TAGS_PER_ITEM
        self._input.setVisible(not full)
        self._input.setEnabled(not full)
        self.updateGeometry()

    def _refresh_completer(self) -> None:
        used = {tag.casefold() for tag in self._tags}
        suggestions = [
            tag for tag in self._catalog if tag.casefold() not in used
        ]
        self._model.setStringList(suggestions)

    def _accept_completion(self, text: str) -> None:
        self._input.setText(text)
        self._commit()

    def _commit(self) -> None:
        tag = normalize_tag(self._input.text())
        self._input.clear()
        if not tag:
            return
        lowered = tag.casefold()
        if any(existing.casefold() == lowered for existing in self._tags):
            return
        if len(self._tags) >= MAX_TAGS_PER_ITEM:
            return
        self._tags.append(tag)
        self._rebuild()
        self._refresh_completer()
        self.tags_changed.emit(self.tags())

    def _remove(self, tag: str) -> None:
        self._tags = [
            item for item in self._tags if item.casefold() != tag.casefold()
        ]
        self._rebuild()
        self._refresh_completer()
        self.tags_changed.emit(self.tags())


class MappedFilterBar(QWidget):
    """Search mapped rows by name, id, or tags, with used-tag suggestions."""

    query_changed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MappedFilterBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setObjectName("MappedSearch")
        self._edit.setPlaceholderText("Search name, ID, or tags")
        self._edit.setClearButtonEnabled(True)
        keyboard_focus(self._edit)
        set_name(
            self._edit,
            "Search mapped items",
            "Filter by name, identifier, or tags. "
            "Use #tag to match tags only. Suggestions appear as you type.",
        )
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        try:
            self._completer.setFilterMode(Qt.MatchContains)
        except Exception:
            pass
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._edit.setCompleter(self._completer)
        try:
            self._completer.activated[str].connect(self._on_tag_chosen)
        except (TypeError, KeyError, AttributeError):
            self._completer.activated.connect(self._on_tag_chosen)
        self._edit.textChanged.connect(self.query_changed.emit)
        row.addWidget(self._edit, 1)

    def query(self) -> str:
        return self._edit.text().strip()

    def set_query(self, text: str) -> None:
        if self._edit.text() == text:
            self.query_changed.emit(text)
            return
        self._edit.setText(text)

    def set_suggestions(self, tags: Sequence[str]) -> None:
        self._model.setStringList(list(tags))

    def _on_tag_chosen(self, tag: str) -> None:
        self._edit.setText(tag)
        self._edit.setFocus()
