# -*- coding: utf-8 -*-
"""Environment resolution for API endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Tuple

from .defaults import DEFAULT_ENVIRONMENT, ENVIRONMENTS

if TYPE_CHECKING:
    from .settings import SettingsManager

# Standard selectable environments (Settings tabs + status-bar switcher).
STANDARD_ENVIRONMENTS: Tuple[str, ...] = ("development", "staging", "production")

_SHORT_LABELS = {
    "development": "Development",
    "staging": "Staging",
    "production": "Production",
}


@dataclass(frozen=True)
class EnvironmentConfig:
    """Resolved runtime environment endpoints."""

    key: str
    label: str
    api_base_url: str
    user_management_api_base_url: str
    auth_url: str
    portal_url: str

    @property
    def short_label(self) -> str:
        return _SHORT_LABELS.get(self.key, self.label)


def env_url_setting_key(env_key: str, field: str) -> str:
    """QSettings key for a per-environment URL override."""
    return "env.{}.{}".format(env_key, field)


def standard_environment_keys() -> Iterable[str]:
    return STANDARD_ENVIRONMENTS


def get_environment_urls(
    settings: "SettingsManager", env_key: str
) -> Tuple[str, str]:
    """Return (gateway, user-management) URLs for an environment.

    Non-empty stored overrides win; otherwise built-in presets are used.
    """
    if env_key not in ENVIRONMENTS:
        env_key = DEFAULT_ENVIRONMENT
    preset = ENVIRONMENTS[env_key]
    api = (
        str(
            settings.get(env_url_setting_key(env_key, "api_base_url"), "") or ""
        ).strip()
        or preset["api_base_url"]
    )
    um = (
        str(
            settings.get(
                env_url_setting_key(env_key, "user_management_api_base_url"),
                "",
            )
            or ""
        ).strip()
        or preset["user_management_api_base_url"]
    )
    return api.rstrip("/"), um.rstrip("/")


def set_environment_urls(
    settings: "SettingsManager",
    env_key: str,
    api_base_url: str,
    user_management_api_base_url: str,
) -> None:
    """Persist URL overrides for a standard environment."""
    if env_key not in ENVIRONMENTS:
        return
    settings.set(
        env_url_setting_key(env_key, "api_base_url"),
        (api_base_url or "").strip().rstrip("/"),
    )
    settings.set(
        env_url_setting_key(env_key, "user_management_api_base_url"),
        (user_management_api_base_url or "").strip().rstrip("/"),
    )


def resolve_environment(settings: "SettingsManager") -> EnvironmentConfig:
    """Build endpoint config from settings (dev / staging / prod / custom)."""
    key = settings.get("environment", DEFAULT_ENVIRONMENT)
    if key == "custom":
        base = (settings.get("custom_api_base_url") or "").rstrip("/")
        um_base = (
            settings.get("custom_user_management_api_base_url") or ""
        ).rstrip("/")
        if not base:
            key = DEFAULT_ENVIRONMENT
            base, um_base = get_environment_urls(settings, key)
            preset = ENVIRONMENTS[key]
            label = preset["label"]
            portal = preset["portal_url"]
            auth_path = preset["auth_path"]
        else:
            label = "Custom"
            portal = settings.get("custom_portal_url", "")
            auth_path = "/authenticate"
            if not um_base:
                um_base = base
    else:
        if key not in ENVIRONMENTS:
            key = DEFAULT_ENVIRONMENT
        preset = ENVIRONMENTS[key]
        base, um_base = get_environment_urls(settings, key)
        label = preset["label"]
        portal = preset["portal_url"]
        auth_path = preset["auth_path"]

    auth_url = "{}{}".format(base.rstrip("/"), auth_path)
    return EnvironmentConfig(
        key=key,
        label=label,
        api_base_url=base.rstrip("/"),
        user_management_api_base_url=um_base.rstrip("/"),
        auth_url=auth_url,
        portal_url=portal,
    )
