# -*- coding: utf-8 -*-
"""Small Qt accessibility helpers shared by TDEI screens."""

from __future__ import annotations

from typing import Iterable, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel, QWidget


def keyboard_focus(widget: QWidget) -> QWidget:
    """Allow Tab focus without macOS's native inner focus-rect outline."""
    widget.setFocusPolicy(Qt.StrongFocus)
    # Keep our stylesheet :focus ring; hide the OS aqua text outline.
    widget.setAttribute(Qt.WA_MacShowFocusRect, False)
    return widget


def set_name(
    widget: QWidget,
    name: str,
    description: str = "",
) -> QWidget:
    """Set accessible name/description used by screen readers."""
    if name:
        widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget


def set_page(
    widget: QWidget,
    title: str,
    description: str = "",
) -> QWidget:
    """Mark a top-level page for assistive tech."""
    set_name(widget, title, description)
    if description:
        widget.setWhatsThis(description)
    return widget


def label_for(
    label: QLabel,
    control: QWidget,
    *,
    name: str = "",
    description: str = "",
) -> None:
    """Associate a visible label with its control (buddy + a11y name)."""
    label.setBuddy(control)
    label.setFocusPolicy(Qt.NoFocus)
    accessible = name or label.text().replace(" *", "").strip()
    set_name(control, accessible, description)
    if description:
        control.setToolTip(description)
        control.setWhatsThis(description)


def set_tab_order(widgets: Iterable[Optional[QWidget]]) -> None:
    """Apply an explicit keyboard tab order across controls."""
    chain = [w for w in widgets if w is not None]
    for prev, nxt in zip(chain, chain[1:]):
        QWidget.setTabOrder(prev, nxt)


def live_status(label: QLabel, message: str, *, error: bool = False) -> None:
    """Update a status label so assistive tech can announce it."""
    text = message or ""
    label.setText(text)
    if text:
        kind = "Error" if error else "Status"
        label.setAccessibleName(kind)
        label.setAccessibleDescription(text)
    else:
        label.setAccessibleName("")
        label.setAccessibleDescription("")
