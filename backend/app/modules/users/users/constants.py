"""Domain constants for users."""

from enum import StrEnum

import core.attempt_state as core_attempt_state

#: Domain-owned storage namespace for profile photos. For the ``local`` backend this maps to
#: ``{DATA_DIR}/user_images`` — the directory the photos already live in — so an existing
#: install needs no data migration; for S3 it is the object key prefix.
USER_IMAGE_STORAGE_AREA = "user_images"

#: Fields a user may change on their own account through the self-service profile endpoint.
#: Any field not in this set is dropped before persistence, so a payload cannot escalate
#: privilege through mass assignment (for example setting ``access_type`` to ``admin``).
PROFILE_SELF_SERVICE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "username",
        "city",
        "birthdate",
        "preferred_language",
        "gender",
        "units",
        "height",
        "max_heart_rate",
        "first_day_of_week",
        "currency",
        "timezone",
    }
)

#: Photo extensions accepted on upload.
ALLOWED_USER_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})

#: Most users a username search returns to a non-admin caller.
USER_SEARCH_LIMIT = 25

#: Lifetime of a queued deletion's claim and state: longer than any deletion takes, shorter than a stuck claim
#: should block an administrator from queueing it again.
DELETION_STATE_TTL_SECONDS = 2 * 60 * 60

#: Activities erased per transaction by an account deletion. Each carries streams, laps and media rows through
#: the database cascade, so a batch is small enough to hold its row locks briefly.
DELETION_BATCH_SIZE = 100

#: Deletions the in-process pool runs at once when no durable worker does.
DELETION_POOL_WORKERS = 1

#: Deletions the in-process pool holds, running and queued, before a new request is refused.
DELETION_POOL_MAX_PENDING = 5

#: Who asked for the deletion, as recorded on the event.
DELETION_SOURCE_API = "api:delete_user"


#: Where a queued deletion is; shared by every queued job's state.
DeletionStatus = core_attempt_state.SyncStatus


class DeletionKind(StrEnum):
    """What a queued deletion state tracks; one, but the shared sync state is keyed by kind."""

    ACCOUNT = "account"
