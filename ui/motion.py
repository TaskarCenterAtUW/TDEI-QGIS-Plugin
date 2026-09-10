# -*- coding: utf-8 -*-
"""Lightweight UI motion helpers (opt-out, short, non-blocking)."""

from __future__ import annotations

import os
from typing import Optional

from qgis.PyQt.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
)
from qgis.PyQt.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

# Keep transitions snappy so navigation never feels sluggish.
PAGE_MS = 180
TAB_MS = 160
SIDEBAR_MS = 200


def motion_enabled(settings=None) -> bool:
    """Honor plugin setting and common reduce-motion env overrides."""
    flag = str(os.environ.get("TDEI_REDUCE_MOTION", "")).strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return False
    qt_flag = str(os.environ.get("QT_ANIMATION_SPEED", "")).strip()
    if qt_flag == "0":
        return False
    if settings is None:
        try:
            from ..config.settings import SettingsManager

            settings = SettingsManager()
        except Exception:
            settings = None
    if settings is not None:
        try:
            return bool(settings.bool("ui.motion", True))
        except Exception:
            pass
    return True


def fade_in(
    widget: QWidget,
    *,
    duration_ms: int = PAGE_MS,
    parent: Optional[QWidget] = None,
) -> None:
    """Fade a widget from transparent to opaque, then clear the effect."""
    if widget is None or not motion_enabled():
        return
    # Drop any prior effect so rapid switches stay clean.
    widget.setGraphicsEffect(None)
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    anim = QPropertyAnimation(effect, b"opacity", parent or widget)
    anim.setDuration(max(1, int(duration_ms)))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def _clear() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    anim.finished.connect(_clear)
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    # Keep a reference on the widget so GC does not stop the animation.
    widget.setProperty("_tdei_fade_anim", anim)


def animate_width(
    widget: QWidget,
    target: int,
    *,
    duration_ms: int = SIDEBAR_MS,
    on_value=None,
    on_finished=None,
) -> Optional[QParallelAnimationGroup]:
    """Animate min/max width together, then pin with setFixedWidth."""
    target = int(target)
    start = int(widget.width())
    if start == target or not motion_enabled():
        widget.setFixedWidth(target)
        if on_finished is not None:
            on_finished()
        return None

    widget.setMinimumWidth(start)
    widget.setMaximumWidth(start)
    group = QParallelAnimationGroup(widget)
    for prop in (b"minimumWidth", b"maximumWidth"):
        anim = QPropertyAnimation(widget, prop)
        anim.setDuration(max(1, int(duration_ms)))
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        group.addAnimation(anim)

    if on_value is not None:
        # Drive layout ticks from one of the twin animations.
        first = group.animationAt(0)
        if first is not None:
            first.valueChanged.connect(on_value)

    def _done() -> None:
        widget.setFixedWidth(target)
        if on_finished is not None:
            on_finished()

    group.finished.connect(_done)
    group.start(QAbstractAnimation.DeleteWhenStopped)
    widget.setProperty("_tdei_width_anim", group)
    return group


class FadeStackedWidget(QStackedWidget):
    """QStackedWidget with optional fade-in on intentional transitions."""

    def fade_to_index(self, index: int, *, duration_ms: int = TAB_MS) -> None:
        if index < 0 or index >= self.count():
            return
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)
        widget = self.currentWidget()
        if widget is not None:
            fade_in(widget, duration_ms=duration_ms, parent=self)

    def fade_to_widget(
        self, widget: QWidget, *, duration_ms: int = TAB_MS
    ) -> None:
        if widget is None:
            return
        if self.indexOf(widget) < 0:
            self.addWidget(widget)
        if widget is self.currentWidget():
            return
        self.setCurrentWidget(widget)
        fade_in(widget, duration_ms=duration_ms, parent=self)
