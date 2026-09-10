# -*- coding: utf-8 -*-
"""Centralized exception → user notification bridge."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..compatibility import qgis_compat
from ..exceptions import TdeiError
from ...logging.logger import get_logger

if TYPE_CHECKING:
    from qgis.gui import QgsInterface

LOG = get_logger(__name__)


class ExceptionHandler:
    @staticmethod
    def handle(
        exc: BaseException,
        *,
        iface: Optional["QgsInterface"] = None,
        user_message: Optional[str] = None,
        notification_service=None,
    ) -> None:
        LOG.exception("Unhandled plugin error: %s", type(exc).__name__)
        message = user_message or ExceptionHandler.user_message_for(exc)
        if notification_service is not None:
            notification_service.error(message)
            return
        if iface is not None:
            iface.messageBar().pushMessage(
                "TDEI",
                message,
                level=qgis_compat.message_level_critical(),
                duration=8,
            )

    @staticmethod
    def user_message_for(exc: BaseException) -> str:
        if isinstance(exc, TdeiError):
            return str(exc)
        return "An unexpected error occurred. Please try again."
