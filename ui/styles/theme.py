# -*- coding: utf-8 -*-
"""Central theme facade."""

from __future__ import annotations

from . import colors, dimensions, stylesheet, typography


class Theme:
    primary_color = colors.PRIMARY
    secondary_color = colors.SECONDARY
    background_color = colors.BACKGROUND
    surface_color = colors.SURFACE
    text_color = colors.TEXT
    text_secondary = colors.TEXT_SECONDARY
    text_muted = colors.TEXT_MUTED
    error_color = colors.ERROR
    success_color = colors.SUCCESS
    warning_color = colors.WARNING
    info_color = colors.INFO
    spacing_medium = dimensions.SPACING_MD
    spacing_large = dimensions.SPACING_LG
    font_family = typography.FONT_FAMILY

    @staticmethod
    def application_stylesheet() -> str:
        return stylesheet.application_stylesheet()

    @staticmethod
    def login_stylesheet() -> str:
        return stylesheet.login_stylesheet()


theme = Theme()
