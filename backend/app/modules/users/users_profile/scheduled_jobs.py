"""Scheduled work owned by the profile import."""

import jasil.runtime as platform_runtime

import core.scheduler as core_scheduler
import modules.users.users_profile.constants as profile_constants
import modules.users.users_profile.import_job_service as profile_import_job_service

STAGED_IMPORT_SWEEP_LOCK = "profile_import_staging_sweep"


def sweep_staged_imports() -> None:
    """Delete staged import archives that no import will read any more.

    Scheduler-invoked, with no request to carry the provider, so this entry point resolves it.
    """
    storage = platform_runtime.get_active_platform().storage
    profile_import_job_service.sweep_staged_imports(storage, profile_constants.IMPORT_STAGED_MAX_AGE_SECONDS)


def recurring_jobs() -> tuple[core_scheduler.ScheduledJob, ...]:
    """Return the profile import's recurring scheduled jobs.

    Returns:
        The module's scheduled jobs, for the composition root to register.
    """
    return (
        core_scheduler.ScheduledJob(
            sweep_staged_imports,
            360,
            "remove staged profile import archives that were never consumed",
            lock_name=STAGED_IMPORT_SWEEP_LOCK,
        ),
    )
