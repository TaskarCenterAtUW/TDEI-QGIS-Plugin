# -*- coding: utf-8 -*-
"""Domain models — independent of Qt and QGIS UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AuthState(str, Enum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    REFRESHING = "refreshing"


@dataclass
class UserSession:
    username: str
    display_name: str = ""
    first_name: str = ""
    last_name: str = ""

    @property
    def full_name(self) -> str:
        parts = [
            (self.first_name or "").strip(),
            (self.last_name or "").strip(),
        ]
        name = " ".join(part for part in parts if part)
        return name or (self.display_name or "").strip() or self.username


@dataclass
class ProjectGroup:
    id: str
    name: str
    roles: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None  # epoch seconds
    token_type: str = "Bearer"


class DatasetLocalState(str, Enum):
    """Local availability relative to QGIS / disk cache."""

    REMOTE = "remote"  # needs download
    CACHED = "cached"  # zip/geojson on disk, not in map
    LOADED = "loaded"  # already in the QGIS project


JOB_MAP_PREFIX = "job-"


@dataclass
class MappedItem:
    """A TDEI layer group currently present in the QGIS project."""

    key: str
    display_name: str = ""
    kind: str = "dataset"  # dataset | job

    tags: List[str] = field(default_factory=list)

    @property
    def subtitle(self) -> str:
        if self.kind == "job" and self.key.startswith(JOB_MAP_PREFIX):
            return self.key[len(JOB_MAP_PREFIX) :]
        return self.key


class DatasetScope(str, Enum):
    """Matches TDEI portal dataset scope filter."""

    ALL = "all"
    CURRENT_PROJECT_GROUP = "currentProjectGroup"
    MY_PROJECT_GROUPS = "myProjectGroups"


@dataclass
class Dataset:
    id: str
    name: str
    version: str = ""
    uploaded_timestamp: str = ""
    status: str = ""
    # PMTiles / dataset-viewer gates from the datasets list API.
    data_viewer_allowed: bool = False
    project_group_data_viewer_allowed: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name or self.id

    @property
    def display_version(self) -> str:
        return (self.version or "").strip() or "—"

    @property
    def display_status(self) -> str:
        return (self.status or "").strip() or "—"


@dataclass
class DatasetLoadResult:
    dataset_id: str
    layer_count: int = 0
    source: str = "download"  # already_loaded | cache | download


@dataclass
class JobDefinition:
    title: str
    path: str
    method: str
    operation: Dict[str, Any]


@dataclass
class JobField:
    name: str
    location: str
    required: bool
    type: str = "string"
    format: Optional[str] = None
    enum: Optional[List[Any]] = None
    description: str = ""
    value: Any = ""


@dataclass
class JobSubmissionResult:
    job_id: str = ""
    location: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRecord:
    """A job history row from GET /jobs."""

    id: str
    job_type: str
    status: str
    download_url: str = ""
    message: str = ""
    project_group_id: str = ""
    project_group_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def map_key(self) -> str:
        """Layer-group / cache key (avoids colliding with dataset UUIDs)."""
        return "{}{}".format(JOB_MAP_PREFIX, self.id)

    @property
    def has_download(self) -> bool:
        return bool(self.download_url and str(self.download_url).strip())

    @property
    def display_type(self) -> str:
        return self.job_type or "Job {}".format(self.id)


@dataclass
class JobLoadResult:
    job_id: str
    layer_count: int = 0
    source: str = "download"  # already_loaded | cache | download


@dataclass
class AppState:
    auth_state: AuthState = AuthState.ANONYMOUS
    current_user: Optional[UserSession] = None
    selected_dataset_id: Optional[str] = None
    loading: bool = False
