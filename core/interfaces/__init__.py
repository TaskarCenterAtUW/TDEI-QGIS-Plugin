# -*- coding: utf-8 -*-
"""Small replaceable protocols for DI / testing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..models import Dataset, JobDefinition, JobSubmissionResult, TokenPair


@runtime_checkable
class TokenProvider(Protocol):
    def get_access_token(self) -> Optional[str]:
        ...

    def clear(self) -> None:
        ...


@runtime_checkable
class AuthProvider(Protocol):
    def login(self, username: str, password: str) -> TokenPair:
        ...

    def logout(self) -> None:
        ...

    def is_authenticated(self) -> bool:
        ...


@runtime_checkable
class DatasetRepository(Protocol):
    def list_datasets(self) -> List[Dataset]:
        ...

    def download_osw(self, dataset_id: str, dest_path: str) -> str:
        ...


@runtime_checkable
class JobRepository(Protocol):
    def list_jobs(self) -> List[JobDefinition]:
        ...

    def submit(
        self,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, str]] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> JobSubmissionResult:
        ...


@runtime_checkable
class NotificationSink(Protocol):
    def success(self, message: str) -> None:
        ...

    def info(self, message: str) -> None:
        ...

    def warning(self, message: str) -> None:
        ...

    def error(self, message: str) -> None:
        ...
