"""Queue account deletions so they never run on an API thread.

The request revokes the user's sessions and deactivates the account, so nobody can act as the user
while the data is erased, then answers 202. On the durable profile (``JOBS_ENABLED``) it stages a
``users.deletion_requested`` event and a worker runs it, surviving a restart. Otherwise the same body
runs on a small in-process pool that is not the request threadpool. Either way the state in the shared
state store is what an administrator polls, and its claim stops a user being queued twice.

The job erases the activities a batch per transaction, so no transaction holds the whole account, then
deletes the user row, which removes everything else through the database cascade. Every step can be
repeated, so a job a worker died in is simply run again.
"""

from typing import TYPE_CHECKING

import jasil.providers as platform_providers
from sqlalchemy.orm import Session

import core.config as core_config
import core.database as core_database
import core.exceptions as core_exceptions
import core.local_pool as core_local_pool
import core.logger as core_logger
import modules.users.contributor_registry as users_contributor_registry
import modules.users.users.constants as users_constants
import modules.users.users.crud as users_crud
import modules.users.users.deletion_state_store as users_deletion_state_store
import modules.users.users.event_publishers as users_event_publishers
import modules.users.users.events as users_events
import modules.users.users.photo_service as users_photo_service
import modules.users.users.schema as users_schema
import modules.users.users.service as users_service

if TYPE_CHECKING:
    import modules.auth.identity_service as auth_identity_service

logger = core_logger.get_logger(__name__)

_Status = users_constants.DeletionStatus
_Kind = users_constants.DeletionKind

# Deletions are long and rare, so they get a pool of their own rather than the subscriber pool, where
# they would hold the threads that deliver notifications and thumbnails.
_deletion_pool = core_local_pool.BoundedPool(
    "user-deletion",
    workers=users_constants.DELETION_POOL_WORKERS,
    max_pending=users_constants.DELETION_POOL_MAX_PENDING,
)


def shutdown_deletion_pool(*, wait: bool = False) -> None:
    """Stop accepting deletions and release the pool thread.

    Args:
        wait: Whether to wait for a deletion still running.
    """
    _deletion_pool.shutdown(wait=wait)


def request_deletion(
    user_id: int,
    identity_service: "auth_identity_service.IdentityService",
    states: users_deletion_state_store.UserDeletionStateStore,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> users_schema.UserDeletionStatus:
    """Queue the erasure of a user's account and data.

    Signs the user out everywhere and deactivates the account before answering, so a deletion that
    is still running cannot be used. This is a unit of work: it commits.

    Args:
        user_id: The user to delete.
        identity_service: Identity service that revokes the user's sessions.
        states: Shared store of the deletion's state.
        storage: The platform storage provider, for the in-process pool.
        db: Database session.

    Returns:
        The deletion's initial status.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the user is the only administrator, or a deletion is already pending.
        PoolFullError: When there is no durable worker and the in-process pool is full.
    """
    users_service.require_deletable_user(user_id, db)
    if not core_config.settings.JOBS_ENABLED:
        _deletion_pool.require_capacity()
    if not states.begin(user_id, _Kind.ACCOUNT):
        logger.warning(
            "Refused a second account deletion while one is pending", extra=core_logger.context(user_id=user_id)
        )
        raise core_exceptions.ConflictError("An account deletion is already in progress")

    payload = users_events.DeletionRequestedPayload(user_id=user_id)
    try:
        identity_service.delete_all_user_sessions(user_id)
        users_crud.update_user(user_id, {"active": False}, db)
        if core_config.settings.JOBS_ENABLED:
            users_event_publishers.publish_deletion_requested(user_id, db, commit=db.commit)
        else:
            db.commit()
            _deletion_pool.submit(run_deletion, payload, states, storage)
    except BaseException:
        # The deletion never started, so nothing else would finish its claim.
        states.set_status(user_id, _Kind.ACCOUNT, _Status.FAILED)
        raise

    logger.info("Account deletion queued", extra=core_logger.context(user_id=user_id))
    return users_schema.UserDeletionStatus(status=_Status.QUEUED)


def get_deletion_status(
    user_id: int, states: users_deletion_state_store.UserDeletionStateStore
) -> users_schema.UserDeletionStatus:
    """Report where a user's account deletion is.

    Args:
        user_id: The user being deleted.
        states: Shared store of the deletion's state.

    Returns:
        The deletion's status.

    Raises:
        NotFoundError: When no deletion is recorded or it has expired.
    """
    state = states.get(user_id, _Kind.ACCOUNT)
    if state is None:
        raise core_exceptions.NotFoundError("No account deletion recorded")
    return users_schema.UserDeletionStatus(status=state.status)


def run_deletion(
    payload: users_events.DeletionRequestedPayload,
    states: users_deletion_state_store.UserDeletionStateStore,
    storage: platform_providers.StorageProvider,
    *,
    will_retry: bool = False,
) -> None:
    """Erase one account and record the outcome. Blocking; call it from a worker, never a request.

    A deletion that raised and will be retried by a durable worker stays ``QUEUED`` with its claim held:
    releasing the claim would let a second deletion start beside the retry. One nothing will retry,
    because there is no worker or this was the last attempt, is ``FAILED`` and its claim is released;
    the account stays deactivated and an administrator deletes it again.

    Args:
        payload: Whose account to erase.
        states: Shared store of the deletion's state.
        storage: The platform storage provider.
        will_retry: Whether a durable worker runs this again if it raises.

    Raises:
        Exception: Whatever the deletion raised, when ``will_retry``, so the worker runs it again.
    """
    user_id = payload.user_id
    state = states.get(user_id, _Kind.ACCOUNT)
    if state is None or state.status not in (_Status.QUEUED, _Status.RUNNING):
        logger.debug("Skipped an account deletion that is not pending", extra=core_logger.context(user_id=user_id))
        return

    states.set_status(user_id, _Kind.ACCOUNT, _Status.RUNNING)
    try:
        activities = _erase_activities(user_id)
        _delete_user_row(user_id)
    except Exception as err:
        if will_retry:
            logger.warning(
                "Account deletion failed; it will be retried", exc_info=err, extra=core_logger.context(user_id=user_id)
            )
            states.set_status(user_id, _Kind.ACCOUNT, _Status.QUEUED)
            raise
        logger.error("Account deletion failed", exc_info=err, extra=core_logger.context(user_id=user_id))
        states.set_status(user_id, _Kind.ACCOUNT, _Status.FAILED)
        return

    users_photo_service.delete_photo_files(user_id, storage)
    users_contributor_registry.erasers().delete_staged_files(user_id, storage)
    states.set_status(user_id, _Kind.ACCOUNT, _Status.COMPLETED)
    logger.info("User deleted", extra=core_logger.context(user_id=user_id, activities=activities))


def _erase_activities(user_id: int) -> int:
    """Delete a user's activities one batch per transaction.

    Args:
        user_id: The user whose activities to delete.

    Returns:
        How many activities were deleted.
    """
    delete_batch = users_contributor_registry.erasers().delete_activities
    total = 0
    while True:
        with core_database.SessionLocal() as db:
            deleted = delete_batch(user_id, users_constants.DELETION_BATCH_SIZE, db)
            db.commit()
        if not deleted:
            return total
        total += deleted
        logger.debug(
            "Erased a batch of a user's activities",
            extra=core_logger.context(user_id=user_id, batch=deleted, total=total),
        )


def _delete_user_row(user_id: int) -> None:
    """Delete the user row, which removes everything else that references it through the database cascade.

    A row that is already gone means an earlier attempt committed it, so there is nothing to do.

    Args:
        user_id: The user to delete.
    """
    with core_database.SessionLocal() as db:
        if users_crud.get_user_by_id(user_id, db) is None:
            logger.debug("The user row was already deleted", extra=core_logger.context(user_id=user_id))
            return
        users_crud.delete_user(user_id, db)
        db.commit()
    logger.debug("Deleted the user row", extra=core_logger.context(user_id=user_id))


def close_dead_lettered_deletion(
    payload: users_events.DeletionRequestedPayload, states: users_deletion_state_store.UserDeletionStateStore
) -> None:
    """Close a deletion the runner gave up on, so an administrator can queue it again.

    Runs however the last attempt ended, including a lease that expired or a worker that died, where
    :func:`run_deletion` never got to record it. A deletion that already finished, or whose state has
    expired, is left as it is.

    Args:
        payload: Whose account was to be erased.
        states: Shared store of the deletion's state.
    """
    if states.close_pending(payload.user_id, _Kind.ACCOUNT):
        logger.error("An account deletion was dead-lettered", extra=core_logger.context(user_id=payload.user_id))
