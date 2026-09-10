# -*- coding: utf-8 -*-
"""Project group listing via /project-group-roles/{user_id}."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional
from urllib.parse import quote

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ...api.v1.project_groups import parse_project_groups
from ...auth.jwt_util import jwt_sub
from ...core.exceptions import ValidationError
from ...core.models import ProjectGroup
from ...logging.logger import get_logger

if TYPE_CHECKING:
    from ...api.client import ApiClient
    from ...auth.session_manager import SessionManager
    from ...auth.token_manager import TokenManager
    from ...config.settings import SettingsManager

LOG = get_logger(__name__)

_SETTING_ID = "ui.selected_project_group_id"
_SETTING_NAME = "ui.selected_project_group_name"
_PAGE_SIZE = 10


class ProjectGroupService(QObject):
    """Loads groups the user can access and persists the active selection."""

    selection_changed = pyqtSignal(object)  # ProjectGroup | None

    def __init__(
        self,
        api_client: "ApiClient",
        settings: "SettingsManager",
        session: "SessionManager",
        tokens: "TokenManager",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._settings = settings
        self._session = session
        self._tokens = tokens
        self._cache: List[ProjectGroup] = []

    def selected(self) -> Optional[ProjectGroup]:
        group_id = str(self._settings.get(_SETTING_ID, "") or "").strip()
        if not group_id:
            return None
        name = str(self._settings.get(_SETTING_NAME, "") or "").strip() or group_id
        for group in self._cache:
            if group.id == group_id:
                return group
        return ProjectGroup(id=group_id, name=name)

    def select(self, group: Optional[ProjectGroup]) -> None:
        if group is None:
            self._settings.set(_SETTING_ID, "")
            self._settings.set(_SETTING_NAME, "")
            self.selection_changed.emit(None)
            return
        self._settings.set(_SETTING_ID, group.id)
        self._settings.set(_SETTING_NAME, group.name)
        self.selection_changed.emit(group)

    def list_project_groups(
        self, *, search: str = "", use_cache: bool = False
    ) -> List[ProjectGroup]:
        if use_cache and self._cache and not search:
            return list(self._cache)

        user_id = self._user_id_from_jwt()
        if not user_id:
            raise ValidationError(
                "Could not read user id (JWT sub) from the access token."
            )

        groups = self._fetch_roles(user_id=user_id, search=search)
        if not search:
            self._cache = groups
        LOG.info("Loaded %s project groups for user", len(groups))
        return list(groups)

    def invalidate_cache(self) -> None:
        self._cache = []

    def clear_session_state(self) -> None:
        """Drop cached groups and persisted selection (call on logout/login)."""
        self.invalidate_cache()
        self.select(None)

    def ensure_default_selection(
        self, groups: List[ProjectGroup]
    ) -> Optional[ProjectGroup]:
        """Pick a valid selection on the UI thread after groups load."""
        current = self.selected()
        if current is not None:
            for group in groups:
                if group.id == current.id:
                    if group.name != current.name:
                        self.select(group)
                        return group
                    return current
        if groups:
            self.select(groups[0])
            return groups[0]
        return current

    def _user_id_from_jwt(self) -> str:
        return jwt_sub(self._tokens.get_access_token())

    def _fetch_roles(self, *, user_id: str, search: str = "") -> List[ProjectGroup]:
        """GET /project-group-roles/{user_id}?page_no=&page_size=10"""
        path = "project-group-roles/{}".format(quote(str(user_id), safe="-_.~"))
        collected: List[ProjectGroup] = []
        page_no = 1
        while page_no <= 50:
            params = {
                "page_no": page_no,
                "page_size": _PAGE_SIZE,
            }
            if search.strip():
                params["searchText"] = search.strip()
            payload = self._api.get_user_management(path, params=params)
            page = parse_project_groups(payload)
            collected.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            page_no += 1
        return collected
