"""The storage sweeps run under the scheduler's distributed lock, one replica at a time."""

import modules.activities.activity_file_storage.scheduled_jobs as file_jobs
import modules.activities.activity_media.scheduled_jobs as media_jobs
import modules.activities.activity_thumbnail.scheduled_jobs as thumbnail_jobs


def test_each_sweep_declares_its_lock():
    assert [job.lock_name for job in media_jobs.recurring_jobs()] == [media_jobs.SWEEP_LOCK_NAME]
    assert [job.lock_name for job in file_jobs.recurring_jobs()] == [file_jobs.SWEEP_LOCK_NAME]
    sweep = next(job for job in thumbnail_jobs.recurring_jobs() if job.func is thumbnail_jobs.sweep_orphaned_thumbnails)
    assert sweep.lock_name == thumbnail_jobs.SWEEP_LOCK_NAME
