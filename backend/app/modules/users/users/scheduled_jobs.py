"""Scheduled work owned by users."""

import jasil.runtime as platform_runtime

import core.scheduler as core_scheduler
import modules.users.users.constants as users_constants
import modules.users.users.deletion_job_service as users_deletion_job_service
import modules.users.users.deletion_state_store as users_deletion_state_store

DELETION_SWEEP_LOCK_NAME = "users_deletion_sweep"


def requeue_stalled_deletions() -> None:
    """Queue again the account deletions that never finished.

    Scheduler-invoked, with no request to carry the providers, so this entry point resolves them; the
    scheduler's lock keeps it to one replica.
    """
    platform = platform_runtime.get_active_platform()
    users_deletion_job_service.requeue_stalled_deletions(
        users_deletion_state_store.UserDeletionStateStore(platform.state), platform.storage, platform.clock
    )


def recurring_jobs() -> tuple[core_scheduler.ScheduledJob, ...]:
    """Return the account deletion sweep.

    Returns:
        The jobs to schedule.
    """
    return (
        core_scheduler.ScheduledJob(
            requeue_stalled_deletions,
            users_constants.DELETION_SWEEP_INTERVAL_MINUTES,
            "queue again account deletions that never finished",
            lock_name=DELETION_SWEEP_LOCK_NAME,
        ),
    )
