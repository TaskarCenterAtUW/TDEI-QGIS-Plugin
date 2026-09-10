# -*- coding: utf-8 -*-
"""UI helper to run a TDEI job against a dataset id (form → submit → Jobs)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from ...core.compatibility.qt_compat import DialogAccepted
from ...core.exceptions import TdeiError
from ...core.models import JobDefinition
from ...features.jobs.service import PENDING_OSW_ZIP
from ...features.osw.naming import (
    SUPPORTED_OSW_GEOJSON_LABELS,
    supported_osw_geojson_types_text,
)
from ...logging.logger import get_logger
from ..dialogs.confirmation_dialog import ConfirmationDialog
from ..dialogs.job_form_dialog import JobFormDialog
from ..dialogs.job_progress_dialog import JobProgressDialog

if TYPE_CHECKING:
    from ...core.services.container import ServiceContainer

LOG = get_logger(__name__)

# One in-flight UI submit at a time (layer menu + dataset row share this).
_busy = False


def _confirm_osw_upload_layers(
    container: "ServiceContainer",
    dataset_id: str,
    parent: Optional[QWidget],
) -> bool:
    """Validate OSW GeoJSON naming; return False if the user should abort."""
    layers = container.layers
    accepted, rejected = layers.classify_osw_upload_layers(dataset_id)
    if not accepted:
        supported = "\n".join(
            "  • {}".format(label) for label in SUPPORTED_OSW_GEOJSON_LABELS
        )
        QMessageBox.warning(
            parent,
            "TDEI",
            "GeoJSON files are not in a valid OSW naming convention.\n\n"
            "Supported types:\n{}".format(supported),
        )
        return False
    if not rejected:
        return True

    accepted_names = [
        layers.osw_geojson_basename(layer) for layer in accepted
    ]
    rejected_names = [
        layers.osw_geojson_basename(layer) for layer in rejected
    ]
    accepted_list = "\n".join(
        "  • {}".format(name) for name in accepted_names
    )
    rejected_list = "\n".join(
        "  • {}".format(name) for name in rejected_names
    )
    message = (
        "{n_ok} file(s) selected for upload:\n{accepted}\n\n"
        "{n_skip} file(s) not selected due to naming convention:\n"
        "{rejected}\n\n"
        "Supported types: {types}\n\n"
        "Proceed with the selected file(s) only?"
    ).format(
        n_ok=len(accepted_names),
        accepted=accepted_list,
        n_skip=len(rejected_names),
        rejected=rejected_list,
        types=supported_osw_geojson_types_text(),
    )
    return ConfirmationDialog.ask(
        parent,
        "OSW file naming",
        message,
        confirm_text="Proceed",
        destructive=False,
    )


def run_dataset_job(
    container: "ServiceContainer",
    job: JobDefinition,
    dataset_id: str,
    parent: Optional[QWidget] = None,
) -> None:
    """Show the job form (e.g. proximity), then submit and open Jobs."""
    global _busy
    if _busy:
        return

    parent = parent or (
        container.iface.mainWindow() if container.iface else None
    )
    if not container.auth.is_authenticated():
        QMessageBox.information(
            parent,
            "TDEI",
            "Sign in first, then run the job.",
        )
        open_fn = getattr(container, "open_main_window", None)
        if callable(open_fn):
            open_fn()
        return

    fields = container.jobs.form_fields(job, dataset_id=dataset_id)
    needs_package = any(
        container.jobs.is_osw_package_field(field) for field in fields
    )
    if needs_package and not _confirm_osw_upload_layers(
        container, dataset_id, parent
    ):
        return

    for field in fields:
        if container.jobs.is_osw_package_field(field):
            field.value = PENDING_OSW_ZIP

    dialog = JobFormDialog(job, fields, parent=parent)
    if dialog.exec_() != DialogAccepted:
        return

    values = dialog.values()
    progress = JobProgressDialog(
        title="Running {}…".format(job.title or "job"),
        parent=parent,
    )
    progress.set_status("Preparing…")
    progress.show()
    status = getattr(container, "status", None)
    if status is not None:
        try:
            status.busy("Submitting {}…".format(job.title or "job"))
        except Exception:  # noqa: BLE001
            pass

    _busy = True
    holder = {"worker": None}

    def work():
        def on_progress(percent, message):
            worker = holder["worker"]
            if worker is not None:
                worker.signals.progress.emit(int(percent), str(message))

        return container.jobs.submit_from_layer(
            job,
            fields,
            values,
            dataset_id,
            progress=on_progress,
        )

    worker = container.workers.submit(work)
    holder["worker"] = worker

    def on_progress(percent, message):
        progress.set_status(message, percent)
        if status is not None:
            try:
                if percent is not None and int(percent) >= 0:
                    status.progress(int(percent), str(message))
                else:
                    status.busy(str(message))
            except Exception:  # noqa: BLE001
                pass

    def on_result(result):
        global _busy
        _busy = False
        progress.accept()
        if status is not None:
            try:
                status.ready("Job submitted.")
            except Exception:  # noqa: BLE001
                pass
        job_id = getattr(result, "job_id", "") or ""
        open_jobs = getattr(container, "open_jobs", None)
        if callable(open_jobs) and job_id:
            open_jobs(job_id)
            container.notifications.success(
                "Job {} submitted.".format(job_id)
            )
        elif job_id:
            container.notifications.success(
                "Job submitted successfully. Job ID: {}".format(job_id)
            )
        else:
            container.notifications.success("Job submitted successfully.")

    def on_error(exc):
        global _busy
        _busy = False
        progress.reject()
        message = (
            str(exc)
            if isinstance(exc, (TdeiError, ValueError, OSError))
            else "Could not submit job: {}".format(exc)
        )
        if status is not None:
            try:
                status.ready(message)
            except Exception:  # noqa: BLE001
                pass
        container.notifications.error(message)
        LOG.exception("Dataset job submit failed")

    worker.signals.progress.connect(on_progress)
    worker.signals.result.connect(on_result)
    worker.signals.error.connect(on_error)
