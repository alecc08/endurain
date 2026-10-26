"""Domain constants for users."""

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
