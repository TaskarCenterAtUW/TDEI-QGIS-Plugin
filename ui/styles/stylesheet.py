# -*- coding: utf-8 -*-
"""Compiled Qt stylesheets from theme tokens."""

from __future__ import annotations

from pathlib import Path

from . import colors, dimensions, typography

_ICONS = Path(__file__).resolve().parents[1] / "icons"


def _icon_url(name: str) -> str:
    path = (_ICONS / name).resolve().as_posix()
    return 'url("{}")'.format(path)


def application_stylesheet() -> str:
    return """
        QWidget#TdeiMainWindow {{
            background-color: {glass_bg};
            color: {text};
            font-family: {font};
            font-size: {fs}px;
        }}
        QWidget#AppHeader {{
            background-color: rgba(50, 0, 110, 0.88);
            min-height: {header}px;
            max-height: {header}px;
        }}
        QLabel#HeaderTitle {{
            color: {on_primary};
            font-size: {fs_xl}px;
            font-weight: {fw_semi};
            letter-spacing: 0.3px;
        }}
        QLabel#HeaderLogo {{
            background: transparent;
            border: none;
        }}
        QLabel#HeaderUser {{
            color: rgba(255, 255, 255, 0.88);
            font-size: {fs_sm}px;
        }}
        QPushButton#HeaderLogout,
        QPushButton#HeaderSync,
        QPushButton#HeaderMinimize {{
            min-height: 32px;
            max-height: 32px;
            min-width: 32px;
            max-width: 32px;
            padding: 0;
            color: {on_primary};
            background: transparent;
            border: 1px solid rgba(255,255,255,0.45);
            border-radius: 6px;
        }}
        QPushButton#HeaderLogout:hover,
        QPushButton#HeaderSync:hover,
        QPushButton#HeaderMinimize:hover {{
            background: rgba(255,255,255,0.14);
            border-color: rgba(255,255,255,0.7);
        }}
        QPushButton#HeaderSync:disabled {{
            opacity: 0.45;
        }}
        QWidget#Sidebar {{
            background-color: {glass_surface};
            border-right: 1px solid {glass_border};
        }}
        QLabel#SidebarSection {{
            color: {muted};
            font-size: {fs_xs}px;
            font-weight: {fw_semi};
            letter-spacing: 0.6px;
            padding: 2px 8px 8px 8px;
        }}
        QToolButton#SidebarHandle {{
            background: {glass_surface_solid};
            border: 1px solid {glass_border};
            border-right: none;
            border-top-left-radius: 8px;
            border-bottom-left-radius: 8px;
            border-top-right-radius: 0;
            border-bottom-right-radius: 0;
            padding: 0;
            min-width: 16px;
            max-width: 16px;
        }}
        QToolButton#SidebarHandle:hover {{
            background: {surface_alt};
            border-color: {border_strong};
        }}
        QFrame#SidebarDivider {{
            background: {border};
            max-height: 1px;
            border: none;
            margin: 6px 4px;
        }}
        QWidget#NavItem {{
            background: transparent;
            border: none;
            border-radius: 8px;
            min-height: {nav_row}px;
            max-height: {nav_row}px;
        }}
        QWidget#NavItem[hover="true"] {{
            background: {surface_alt};
        }}
        QWidget#NavItem[active="true"] {{
            background-color: {primary};
        }}
        QWidget#NavItem[active="true"][hover="true"] {{
            background-color: {primary_hover};
        }}
        QLabel#NavItemLabel {{
            color: {text};
            font-size: {fs_md}px;
            font-weight: {fw_medium};
            background: transparent;
            border: none;
        }}
        QLabel#NavItemLabel[active="true"] {{
            color: {on_primary};
            font-weight: {fw_semi};
        }}
        QLabel#NavItemIcon {{
            background: transparent;
            border: none;
        }}
        QWidget#PageContainer {{
            background-color: {glass_bg};
        }}
        QLabel#PageTitle {{
            color: {text};
            font-size: {fs_xl}px;
            font-weight: {fw_semi};
        }}
        QLabel#PageSubtitle {{
            color: {muted};
            font-size: {fs_md}px;
        }}
        QPushButton#PrimaryButton {{
            min-height: {ctrl}px;
            max-height: {ctrl}px;
            padding: 4px 14px;
            color: {on_primary};
            background-color: {primary};
            border: 1px solid {primary};
            border-radius: {radius}px;
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
        }}
        QPushButton#PrimaryButton:hover {{
            background-color: {primary_hover};
            border-color: {primary_hover};
        }}
        QPushButton#PrimaryButton:focus {{
            border: 2px solid {primary_light};
        }}
        QPushButton#PrimaryButton:disabled {{
            background-color: {disabled};
            border-color: {disabled};
            color: {disabled_text};
        }}
        QPushButton#SecondaryButton {{
            min-height: {ctrl}px;
            max-height: {ctrl}px;
            padding: 4px 14px;
            color: {primary};
            background-color: {surface};
            border: 1px solid {border_strong};
            border-radius: {radius}px;
            font-size: {fs_sm}px;
            font-weight: {fw_medium};
        }}
        QPushButton#SecondaryButton:hover {{
            background-color: {surface_alt};
            border-color: {primary};
        }}
        QPushButton#SecondaryButton:focus {{
            border: 2px solid {focus};
        }}
        QPushButton#IconButton {{
            min-height: 32px;
            max-height: 32px;
            min-width: 32px;
            max-width: 32px;
            padding: 0;
            color: {primary};
            background-color: {surface};
            border: 1px solid {border_strong};
            border-radius: 6px;
        }}
        QPushButton#IconButton:hover {{
            background-color: {surface_alt};
            border-color: {primary};
        }}
        QPushButton#IconButton:focus {{
            border: 2px solid {focus};
        }}
        QPushButton#IconButton:disabled {{
            background-color: {surface_alt};
            border-color: {border};
        }}
        QPushButton#DangerButton {{
            min-height: {ctrl}px;
            max-height: {ctrl}px;
            padding: 4px 14px;
            color: #ffffff;
            background-color: {error};
            border: 1px solid {error};
            border-radius: {radius}px;
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
        }}
        QPushButton#DangerButton:hover {{
            background-color: #a61f1f;
            border-color: #a61f1f;
        }}
        QPushButton#DangerButton:focus {{
            border: 2px solid {text};
        }}
        QWidget#NavItem[focus="true"] {{
            border: 2px solid {focus};
            border-radius: {radius}px;
        }}
        QToolButton#SidebarHandle:focus {{
            border: 2px solid {focus};
            border-radius: 4px;
        }}
        QPushButton#SegmentTab:focus {{
            border: 2px solid {focus};
        }}
        QFrame#EmptyState, QFrame#ErrorState {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: {radius_lg}px;
            padding: 28px;
        }}
        QLabel#EmptyTitle, QLabel#ErrorTitle {{
            font-size: {fs_xl}px;
            font-weight: {fw_semi};
            color: {text};
        }}
        QLabel#ErrorTitle {{
            color: {error};
        }}
        QLabel#EmptyBody, QLabel#ErrorBody {{
            color: {muted};
            font-size: {fs_md}px;
        }}
        QStatusBar {{
            background: {glass_surface};
            color: {muted};
            border-top: 1px solid {glass_border};
            font-size: {fs_sm}px;
            min-height: 24px;
            padding-left: 8px;
        }}
        QToolButton#StatusEnv {{
            color: {primary};
            font-size: {fs_xs}px;
            font-weight: {fw_semi};
            padding: 2px 10px;
            margin-right: 8px;
            background: {glass_surface_alt};
            border: none;
            border-radius: 10px;
        }}
        QToolButton#StatusEnv:hover {{
            background: {border};
        }}
        QToolButton#StatusEnv::menu-indicator {{
            image: none;
            width: 0;
        }}
        QProgressBar#StatusProgress {{
            background: {surface_alt};
            border: 1px solid {border};
            border-radius: 4px;
            margin: 2px 8px 2px 0;
            min-width: 120px;
            max-height: 16px;
        }}
        QProgressBar#StatusProgress::chunk {{
            background-color: {primary};
            border-radius: 3px;
        }}
        QTableWidget {{
            background: {surface};
            border: 1px solid {border};
            border-radius: {radius}px;
            gridline-color: {border};
            font-size: {fs_md}px;
            selection-background-color: rgba(50, 0, 110, 0.08);
            selection-color: {text};
        }}
        QHeaderView::section {{
            background: {surface_alt};
            padding: 6px 10px;
            border: none;
            border-bottom: 1px solid {border};
            border-right: 1px solid {border};
            font-weight: {fw_semi};
            color: {text_secondary};
            font-size: {fs_sm}px;
        }}
        QLineEdit, QComboBox, QSpinBox {{
            min-height: {ctrl}px;
            max-height: {ctrl}px;
            padding: 2px 10px;
            border: 1px solid {border_strong};
            border-radius: {radius}px;
            background: {surface};
            color: {text};
            font-size: {fs_sm}px;
            selection-background-color: rgba(50, 0, 110, 0.18);
            selection-color: {text};
        }}
        QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
            border-color: {primary_light};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border: 2px solid {focus};
            background: #ffffff;
        }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
            background: {surface_alt};
            color: {muted};
            border-color: {border};
        }}
        QComboBox {{
            padding-right: 6px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 26px;
            border: none;
            border-left: 1px solid {border};
            border-top-right-radius: {radius}px;
            border-bottom-right-radius: {radius}px;
            background: {surface_alt};
        }}
        QComboBox::drop-down:hover {{
            background: #e8eaf0;
        }}
        QComboBox::down-arrow {{
            image: {chevron};
            width: 12px;
            height: 12px;
        }}
        QComboBox QAbstractItemView {{
            background: {surface};
            border: 1px solid {border_strong};
            border-radius: {radius}px;
            padding: 4px;
            outline: 0;
            selection-background-color: rgba(50, 0, 110, 0.12);
            selection-color: {text};
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 24px;
            padding: 2px 10px;
        }}
        QSpinBox {{
            padding-right: 4px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 22px;
            border: none;
            background: {surface_alt};
        }}
        QSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            border-top-right-radius: {radius}px;
            border-bottom: 1px solid {border};
        }}
        QSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            border-bottom-right-radius: {radius}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background: #e8eaf0;
        }}
        QSpinBox::up-arrow {{
            image: {spin_up};
            width: 10px;
            height: 10px;
        }}
        QSpinBox::down-arrow {{
            image: {spin_down};
            width: 10px;
            height: 10px;
        }}
        QCheckBox {{
            color: {text};
            font-size: {fs_md}px;
            spacing: 10px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {border_strong};
            border-radius: 4px;
            background: {surface};
        }}
        QCheckBox::indicator:hover {{
            border-color: {primary};
        }}
        QCheckBox::indicator:checked {{
            background-color: {primary};
            border-color: {primary};
            image: {check};
        }}
        QCheckBox#MappedTableCheck {{
            spacing: 0;
            background: transparent;
            border: none;
            padding: 0;
        }}
        QCheckBox#MappedTableCheck::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {text_secondary};
            border-radius: 3px;
            background: #ffffff;
        }}
        QCheckBox#MappedTableCheck::indicator:hover {{
            border-color: {primary};
        }}
        QCheckBox#MappedTableCheck::indicator:checked {{
            background: #ffffff;
            border-color: {primary};
            image: {check_dark};
        }}
        QCheckBox#MappedTableCheck::indicator:disabled {{
            border-color: {border};
            background: {surface_alt};
        }}
        QWidget#MappedToolbar {{
            min-height: 40px;
        }}
        QLineEdit#MappedSearch {{
            min-height: {ctrl}px;
            max-height: {ctrl}px;
            padding: 2px 10px;
            border: 1px solid {border_strong};
            border-radius: {radius}px;
            background: {surface};
            color: {text};
        }}
        QLineEdit#MappedSearch:focus {{
            border: 2px solid {focus};
        }}
        QFrame#TagChip {{
            background: #f2ecf9;
            border: 1px solid #d2c0e8;
            border-radius: 10px;
        }}
        QLabel#TagChipLabel {{
            color: {primary};
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
            background: transparent;
        }}
        QToolButton#TagChipClose {{
            color: {primary};
            background: transparent;
            border: none;
            font-size: 13px;
            font-weight: 700;
            padding: 0;
        }}
        QToolButton#TagChipClose:hover {{
            color: {error};
        }}
        QLineEdit#TagAddInput {{
            min-height: 24px;
            max-height: 24px;
            padding: 0 8px;
            border: 1px dashed {border_strong};
            border-radius: 10px;
            background: {surface};
            color: {text};
            font-size: {fs_sm}px;
        }}
        QLineEdit#TagAddInput:focus {{
            border: 1px solid {focus};
        }}
        QScrollArea#PageScroll {{
            background: transparent;
            border: none;
        }}
        QScrollArea#PageScroll > QWidget > QWidget {{
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 4px 2px 4px 0;
        }}
        QScrollBar::handle:vertical {{
            background: {border_strong};
            border-radius: 4px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {muted};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            height: 0;
            background: none;
        }}
        QWidget#DatasetFilters {{
            background: {surface};
            border: 1px solid {border};
            border-radius: {radius_lg}px;
        }}
        QWidget#SegmentTabs {{
            background: {surface_alt};
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QWidget#SettingsEnvTabs {{
            background: {primary_light};
            border: 1px solid {primary};
            border-radius: 8px;
        }}
        QWidget#SettingsEnvTabs QToolButton#SegmentTab {{
            color: {on_primary};
            padding: 6px 14px;
            min-height: 30px;
            max-height: 30px;
        }}
        QWidget#SettingsEnvTabs QToolButton#SegmentTab:checked {{
            background: {surface};
            color: {primary};
            border: 1px solid {surface};
        }}
        QWidget#SettingsEnvTabs QToolButton#SegmentTab:hover:!checked {{
            color: {on_primary};
            background: rgba(255, 255, 255, 0.12);
        }}
        QFrame#SettingsEnvPanel {{
            background: {surface_alt};
            border: 1px solid {border};
            border-radius: {radius_lg}px;
        }}
        QLineEdit#SettingsEnvUrl {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 6px 10px;
            min-height: 28px;
            selection-background-color: {primary};
            selection-color: {on_primary};
        }}
        QLineEdit#SettingsEnvUrl:focus {{
            border: 2px solid {focus};
        }}
        QToolButton#SegmentTab {{
            background: transparent;
            color: {muted};
            border: none;
            border-radius: 4px;
            padding: 4px 12px 4px 8px;
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
            min-height: 28px;
            max-height: 28px;
            spacing: 6px;
        }}
        QToolButton#SegmentTab:checked {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
        }}
        QToolButton#SegmentTab:hover:!checked {{
            color: {text};
        }}
        QToolButton#SegmentTab::menu-indicator {{
            image: none;
            width: 0;
        }}
        QPushButton#SegmentTab {{
            background: transparent;
            color: {muted};
            border: none;
            border-radius: 4px;
            padding: 4px 12px;
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
            min-height: 24px;
            max-height: 24px;
        }}
        QPushButton#SegmentTab:checked {{
            background: {surface};
            color: {text};
            border: 1px solid {border};
        }}
        QPushButton#SegmentTab:hover:!checked {{
            color: {text};
        }}
        QLabel#FilterFieldLabel {{
            color: {text};
            font-size: {fs_sm}px;
            font-weight: {fw_semi};
        }}
        QPushButton#FilterClear {{
            color: {primary};
            background: transparent;
            border: none;
            padding: 0;
            font-size: {fs_sm}px;
            font-weight: {fw_medium};
            min-height: 0;
        }}
        QPushButton#FilterClear:hover {{
            color: {primary_hover};
            text-decoration: underline;
        }}
        QPushButton#FilterClear:disabled {{
            color: {muted};
        }}
    """.format(
        bg=colors.BACKGROUND,
        glass_bg=colors.GLASS_BG,
        glass_surface=colors.GLASS_SURFACE,
        glass_surface_solid=colors.GLASS_SURFACE_SOLID,
        glass_surface_alt=colors.GLASS_SURFACE_ALT,
        glass_border=colors.GLASS_BORDER_EDGE,
        text=colors.TEXT,
        text_secondary=colors.TEXT_SECONDARY,
        muted=colors.TEXT_MUTED,
        font=typography.FONT_FAMILY,
        fs=dimensions.s(typography.FONT_SIZE_MD),
        fs_xs=dimensions.s(typography.FONT_SIZE_XS),
        fs_sm=dimensions.s(typography.FONT_SIZE_SM),
        fs_md=dimensions.s(typography.FONT_SIZE_MD),
        fs_xl=dimensions.s(typography.FONT_SIZE_XL),
        fw_medium=typography.FONT_WEIGHT_MEDIUM,
        fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
        primary=colors.PRIMARY,
        primary_hover=colors.PRIMARY_HOVER,
        primary_light=colors.PRIMARY_LIGHT,
        on_primary=colors.TEXT_ON_PRIMARY,
        surface=colors.SURFACE,
        surface_alt=colors.SURFACE_ALT,
        border=colors.BORDER,
        border_strong=colors.BORDER_STRONG,
        header=dimensions.s(dimensions.HEADER_HEIGHT),
        sidebar=dimensions.s(dimensions.SIDEBAR_WIDTH),
        radius=dimensions.s(dimensions.RADIUS_MD),
        radius_lg=dimensions.s(dimensions.RADIUS_LG),
        ctrl=dimensions.s(dimensions.CONTROL_HEIGHT),
        nav_row=dimensions.s(dimensions.NAV_ROW),
        disabled=colors.DISABLED_BG,
        disabled_text=colors.DISABLED_TEXT,
        error=colors.ERROR,
        focus=colors.FOCUS,
        chevron=_icon_url("chevron_down.svg"),
        check=_icon_url("check.svg"),
        check_dark=_icon_url("check_dark.svg"),
        spin_up=_icon_url("spin_up.svg"),
        spin_down=_icon_url("spin_down.svg"),
    )


def login_stylesheet() -> str:
    return """
        QWidget#LoginPage {{
            font-family: {font};
        }}
        QWidget#loginHeader {{
            background-color: {primary};
        }}
        QLabel#lblHeaderLogo {{
            background-color: #ffffff;
            border-radius: {radius_sm}px;
            padding: 4px 8px;
        }}
        QLabel#lblHeaderBrand {{
            color: {on_primary};
            font-size: {fs_lg}px;
            font-weight: {fw_semi};
            letter-spacing: 0.4px;
            padding-left: 8px;
        }}
        QFrame#loginCard {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: {radius_lg}px;
        }}
        QLabel#lblLogo {{
            margin: 0px;
            padding: 0px;
        }}
        QLabel#lblTitle {{
            color: {text};
            font-size: {fs_display}px;
            font-weight: {fw_light};
            padding: 0px;
            margin: 0px;
        }}
        QLabel#lblSubtitle {{
            color: {muted};
            font-size: {fs_md}px;
            font-weight: {fw_regular};
            padding: 0px;
            margin: 0px;
        }}
        QLabel#lblUsername, QLabel#lblPassword {{
            color: {text_secondary};
            font-size: {fs_md}px;
            font-weight: {fw_medium};
            padding: 0px;
            margin: 0px;
        }}
        QLineEdit#txtUsername, QLineEdit#txtPassword {{
            min-height: {field_h}px;
            max-height: {field_h}px;
            padding: 0px 12px;
            color: {text};
            background-color: {surface};
            border: 1px solid {border_strong};
            border-radius: {radius_md}px;
            font-size: {fs_lg}px;
            selection-background-color: rgba(50, 0, 110, 0.2);
        }}
        QLineEdit#txtPassword {{
            border-top-right-radius: 0px;
            border-bottom-right-radius: 0px;
            border-right: none;
        }}
        QLineEdit#txtUsername:focus, QLineEdit#txtPassword:focus {{
            border: 1px solid {primary};
        }}
        QLineEdit#txtPassword:focus {{
            border-right: none;
        }}
        QFrame#passwordField {{
            background-color: {surface};
            border: 1px solid {border_strong};
            border-radius: {radius_md}px;
            min-height: {field_h}px;
            max-height: {field_h}px;
        }}
        QFrame#passwordField[focused="true"] {{
            border: 1px solid {primary};
        }}
        QLineEdit#txtPasswordEmbedded {{
            min-height: {field_h}px;
            max-height: {field_h}px;
            padding: 0px 12px;
            color: {text};
            background: transparent;
            border: none;
            font-size: {fs_lg}px;
            selection-background-color: rgba(50, 0, 110, 0.2);
        }}
        QToolButton#btnShowPassword {{
            background: transparent;
            border: none;
            min-width: {eye_w}px;
            max-width: {eye_w}px;
            min-height: {field_h}px;
            max-height: {field_h}px;
            padding: 0px;
            margin: 0px;
        }}
        QToolButton#btnShowPassword:hover {{
            background-color: {surface_alt};
        }}
        QPushButton#btnLogin {{
            min-height: {field_h}px;
            max-height: {field_h}px;
            padding: 0px 12px;
            color: {on_primary};
            background-color: {primary};
            border: 1px solid {primary};
            border-radius: {radius_sm}px;
            font-size: {fs_lg}px;
            font-weight: {fw_semi};
        }}
        QPushButton#btnLogin:hover {{
            background-color: {primary_hover};
            border-color: {primary_hover};
        }}
        QPushButton#btnLogin:disabled {{
            background-color: {disabled};
            border-color: {disabled};
            color: #ffffff;
        }}
        QLabel#lblStatus {{
            color: {muted};
            font-size: {fs_md}px;
            min-height: 20px;
            padding: 0px;
            margin: 0px;
        }}
        QLabel#lblStatus[error="true"] {{
            color: {error};
        }}
        QLabel#lblVersion {{
            color: {muted};
            font-size: {fs_xs}px;
            padding: 0px;
            margin: 0px;
        }}
    """.format(
        font=typography.FONT_FAMILY,
        primary=colors.PRIMARY,
        primary_hover=colors.PRIMARY_HOVER,
        on_primary=colors.TEXT_ON_PRIMARY,
        surface=colors.SURFACE,
        surface_alt=colors.SURFACE_ALT,
        border=colors.BORDER,
        border_strong=colors.BORDER_STRONG,
        text=colors.TEXT,
        text_secondary=colors.TEXT_SECONDARY,
        muted=colors.TEXT_MUTED,
        error=colors.ERROR,
        disabled=colors.DISABLED_BG,
        fs_xs=dimensions.s(typography.FONT_SIZE_XS),
        fs_md=dimensions.s(typography.FONT_SIZE_MD),
        fs_lg=dimensions.s(typography.FONT_SIZE_LG),
        fs_display=dimensions.s(typography.FONT_SIZE_DISPLAY),
        fw_light=typography.FONT_WEIGHT_LIGHT,
        fw_regular=typography.FONT_WEIGHT_REGULAR,
        fw_medium=typography.FONT_WEIGHT_MEDIUM,
        fw_semi=typography.FONT_WEIGHT_SEMIBOLD,
        radius_sm=dimensions.s(dimensions.RADIUS_SM),
        radius_md=dimensions.s(dimensions.RADIUS_MD),
        radius_lg=dimensions.s(dimensions.RADIUS_LG),
        field_h=dimensions.s(dimensions.LOGIN_FIELD_HEIGHT),
        eye_w=dimensions.s(dimensions.LOGIN_EYE_WIDTH),
    )
