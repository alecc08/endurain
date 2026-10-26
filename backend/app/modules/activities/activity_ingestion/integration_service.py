"""The ingestion surface consumed by provider modules.

A provider (Strava, Garmin) fetches files from its API or an export and hands
them to ingestion. Providers import this one module and get the entry point plus
the source types they need to describe where a file came from, including the
:class:`BulkImportSource` base a provider export subclasses.
"""

from collections.abc import Callable, Iterable
from datetime import datetime

import jasil.providers as platform_providers
import jasil.runtime as platform_runtime
from sqlalchemy.orm import Session

import modules.activities.activity.schema as activity_schema
import modules.activities.activity_ingestion.background as activity_ingestion_background
import modules.activities.activity_ingestion.contracts as activity_ingestion_contracts
import modules.activities.activity_ingestion.provider_entry_service as activity_ingestion_provider_entry_service
import modules.activities.activity_ingestion.provider_registry as activity_ingestion_provider_registry
import modules.activities.activity_ingestion.schema as activity_ingestion_schema
import modules.activities.activity_ingestion.service as activity_ingestion_service
import modules.activities.activity_ingestion.window_service as activity_ingestion_window_service

#: Where a file came from, and the metadata that source carries. Re-exported so a
#: provider names one module rather than reaching for the package internals.
UploadSource = activity_ingestion_contracts.UploadSource
GarminSource = activity_ingestion_contracts.GarminSource
BulkImportSource = activity_ingestion_contracts.BulkImportSource
BulkImportFormat = activity_ingestion_contracts.BulkImportFormat
ArchiveMemberReader = activity_ingestion_contracts.ArchiveMemberReader
IngestionSource = activity_ingestion_contracts.IngestionSource
WindowStoppedError = activity_ingestion_contracts.WindowStoppedError
build_import_record = activity_ingestion_contracts.build_import_record


def ingest_activity_file(
    user_id: int,
    file_path: str,
    db: Session,
    *,
    source: activity_ingestion_contracts.IngestionSource,
) -> list[activity_schema.ActivityRead] | None:
    """Validate one on-disk activity file and persist the activities it yields.

    The background entry point: it never raises to its caller. A failure is
    logged and returned as ``None`` so the provider's sync moves on to the next
    activity.

    Must be called from a worker thread with no running event loop (a Starlette
    threadpool, the bulk-import executor, or ``asyncio.to_thread``), because the
    file validation inside it runs a private event loop.

    Args:
        user_id: The owner the activities are stored against.
        file_path: Absolute path to the activity file.
        db: Database session.
        source: Where the file came from, and any source-specific metadata.

    Returns:
        The stored activities, or ``None`` when the file could not be parsed or
        persisted.
    """
    return activity_ingestion_provider_entry_service.store_activity_file(
        user_id, file_path, platform_runtime.get_active_platform().storage, db, source=source
    )


def register_activity_provider(
    name: str,
    fetch_window: activity_ingestion_contracts.FetchWindow,
    linked_user_ids: activity_ingestion_contracts.LinkedUserIds,
) -> None:
    """Register an external provider's activity-fetch implementation.

    Args:
        name: Stable provider identifier.
        fetch_window: Fetches and stores one user's window; synchronous and
            session-less, opening its own short sessions.
        linked_user_ids: Pages through the users who have linked the provider.
    """
    activity_ingestion_provider_registry.register(
        activity_ingestion_provider_registry.ActivityProvider(name, fetch_window, linked_user_ids)
    )


def run_provider_window[ItemT, ResultT](
    items: Iterable[ItemT],
    process: Callable[[ItemT], ResultT],
    *,
    provider: str,
    user_id: int,
    describe: Callable[[ItemT], dict[str, object]],
    propagate: tuple[type[BaseException], ...] = (),
) -> list[ResultT]:
    """Process each activity of a provider's window, raising the first failure once the window is done.

    An activity that cannot be processed is logged and skipped so the rest of the window is stored; the
    refresh job then fails and is retried, resuming past what is already stored.

    Args:
        items: The provider's activities for the window.
        process: Handles one activity and returns what it produced. It may raise ``WindowStoppedError`` to end
            the window early.
        provider: The provider's name, for the log.
        user_id: The user whose window it is, for the log.
        describe: Names an activity for the log, such as its provider id.
        propagate: Failures that end the window at once and are raised as they are.

    Returns:
        What ``process`` returned for each activity it handled.

    Raises:
        BaseException: Whatever ``propagate`` names, as soon as it is raised.
        Exception: The first failure of an activity, after the rest of the window was processed.
    """
    return activity_ingestion_window_service.run_window(
        items, process, provider=provider, user_id=user_id, describe=describe, propagate=propagate
    )


def request_provider_sync(
    user_id: int,
    provider: str,
    window_start: datetime,
    window_end: datetime,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> activity_ingestion_schema.ActivityIngestionJobRead:
    """Queue a sync of one provider over an explicit window and return its handle.

    The provider's own "retrieve activities" endpoints use this so a long date
    range runs as a job rather than on an API worker thread.

    Args:
        user_id: The user whose account to sync.
        provider: The registered provider name.
        window_start: Start of the window.
        window_end: End of the window.
        storage: The blob-storage provider.
        db: Database session.

    Returns:
        The accepted refresh job.
    """
    return activity_ingestion_service.accept_refresh(
        user_id, storage, db, provider=provider, window_start=window_start, window_end=window_end
    )


def register_bulk_import_format(bulk_format: activity_ingestion_contracts.BulkImportFormat) -> None:
    """Register how a provider's bulk-import archive is laid out and interpreted.

    Args:
        bulk_format: The format; its ``name`` is the ``source`` clients select.
    """
    activity_ingestion_provider_registry.register_bulk_format(bulk_format)


def shutdown_background_ingestion(*, wait: bool = False) -> None:
    """Shut down the non-durable ingestion fallback executor.

    Args:
        wait: Whether to wait for running ingestion tasks.
    """
    activity_ingestion_background.shutdown(wait=wait)
