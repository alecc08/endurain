"""Domain constants for the profile import job."""

from enum import StrEnum

#: Domain-owned storage area holding an uploaded archive until the import job has read it.
IMPORT_STAGING_AREA = "profile_import_staging"

#: How long an import's claim and state last. It must exceed the longest legitimate import, and
#: every recorded progress renews the claim, so only a dead worker's claim runs out.
IMPORT_STATE_TTL_SECONDS = 4 * 60 * 60

#: A staged archive older than this is no import's input any more, so the sweep removes it.
IMPORT_STAGED_MAX_AGE_SECONDS = 24 * 60 * 60

#: Who asked for the import, as recorded on the event.
IMPORT_SOURCE_API = "api:profile_import"


class ImportStatus(StrEnum):
    """Where a profile import is.

    ``RUNNING`` is the database part, which is one transaction, so a worker that dies there has
    imported nothing. ``WRITING_FILES`` starts once those rows are committed.
    """

    QUEUED = "queued"
    RUNNING = "running"
    WRITING_FILES = "writing_files"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportFailure(StrEnum):
    """Stable, sanitized reasons an import can fail.

    A closed set: the underlying exception text can carry file names and parser internals, so the
    client gets a code it can translate.
    """

    INVALID_FILE = "invalid_file"
    TOO_LARGE = "too_large"
    TOO_MANY_ACTIVITIES = "too_many_activities"
    TIMED_OUT = "timed_out"
    FILES_INCOMPLETE = "files_incomplete"
    PROCESSING_FAILED = "processing_failed"
