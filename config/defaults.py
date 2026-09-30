# -*- coding: utf-8 -*-
"""Default configuration values (non-secret)."""

from __future__ import annotations

from typing import Any, Dict

CONFIG_VERSION = 2

ENVIRONMENTS: Dict[str, Dict[str, Any]] = {
    "development": {
        "label": "TDEI Development",
        "api_base_url": "https://api-dev.tdei.us/api/v1",
        "user_management_api_base_url": "https://portal-api-dev.tdei.us/api/v1",
        "auth_path": "/authenticate",
        "portal_url": "https://portal-dev.tdei.us",
    },
    "staging": {
        "label": "TDEI Staging",
        "api_base_url": "https://api-stage.tdei.us/api/v1",
        "user_management_api_base_url": "https://portal-api-stage.tdei.us/api/v1",
        "auth_path": "/authenticate",
        "portal_url": "https://portal-stage.tdei.us",
    },
    "production": {
        "label": "TDEI Production",
        "api_base_url": "https://api.tdei.us/api/v1",
        "user_management_api_base_url": "https://portal-api.tdei.us/api/v1",
        "auth_path": "/authenticate",
        "portal_url": "https://portal.tdei.us",
    },
}

DEFAULT_ENVIRONMENT = "development"

DEFAULTS: Dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "environment": DEFAULT_ENVIRONMENT,
    # Per-environment URL overrides (empty → use ENVIRONMENTS presets).
    "env.development.api_base_url": "",
    "env.development.user_management_api_base_url": "",
    "env.staging.api_base_url": "",
    "env.staging.user_management_api_base_url": "",
    "env.production.api_base_url": "",
    "env.production.user_management_api_base_url": "",
    "custom_api_base_url": "",
    "custom_user_management_api_base_url": "",
    "request_timeout_seconds": 30,
    "download_timeout_seconds": 180,
    "job_timeout_seconds": 60,
    "log_level": "INFO",
    "token_refresh_skew_seconds": 60,
    "feature.dataset_load": True,
    "feature.dataset_refresh": True,
    "feature.jobs": True,
    "feature.experimental_map": False,
    "ui.show_toasts": True,
    "ui.toast_duration_ms": 4000,
    # Default open shortcut; users can remap in QGIS Settings → Keyboard Shortcuts.
    "ui.open_shortcut": "Ctrl+Shift+T",
    "ui.sidebar_collapsed": False,
    # Short UI transitions (page / tabs / sidebar). Override with TDEI_REDUCE_MOTION=1.
    "ui.motion": True,
    "ui.mapped_tag_catalog": "[]",
    "remember_username": True,
    "ui.selected_project_group_id": "",
    "ui.selected_project_group_name": "",
    "ui.dataset_scope": "all",
    "ui.jobs_project_group_id": "",
    # XYZ basemap streamed by QGIS (default OSM). Options: openstreetmap,
    # google_roadmap, google_satellite, none
    "basemap.provider": "openstreetmap",
}
