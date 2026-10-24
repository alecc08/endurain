"""The users surface other modules may call.

A consumer asks the owning module a question; it never reaches into this module's CRUD, ORM or
helpers. Everything here returns schemas or primitives: no ORM row and no internal type crosses
the boundary. Writes stage and the caller commits, except the listed units of work.
"""

from datetime import date
from typing import TYPE_CHECKING

import jasil.providers as platform_providers
from fastapi import UploadFile
from sqlalchemy.orm import Session

import modules.server_settings.schema as server_settings_schema
import modules.users.users.crud as users_crud
import modules.users.users.photo_service as users_photo_service
import modules.users.users.schema as users_schema
import modules.users.users.service as users_service

if TYPE_CHECKING:
    import modules.auth.identity_service as auth_identity_service


def get_user(user_id: int, db: Session) -> users_schema.UsersRead | None:
    """Return a user by id, or ``None`` when there is no such user.

    Args:
        user_id: The user to look up.
        db: Database session.

    Returns:
        The user record, or ``None``.
    """
    return users_crud.get_user_by_id(user_id, db)


def require_user(user_id: int, db: Session) -> users_schema.UsersRead:
    """Return a user by id, which must exist.

    Args:
        user_id: The user to look up.
        db: Database session.

    Returns:
        The user record.

    Raises:
        NotFoundError: If the user does not exist.
    """
    return users_service.require_user(user_id, db)


def require_active_user(user: users_schema.UsersRead) -> None:
    """Require a user to be active.

    Args:
        user: The user to check.

    Raises:
        PermissionDeniedError: If the user is not active.
    """
    users_service.require_active_user(user)


def get_user_by_email(email: str, db: Session) -> users_schema.UsersRead | None:
    """Return a user by email address, or ``None`` when no user has it.

    Args:
        email: The email address (case-insensitive).
        db: Database session.

    Returns:
        The user record, or ``None``.
    """
    return users_crud.get_user_by_email(email, db)


def get_user_by_username(username: str, db: Session) -> users_schema.UsersRead | None:
    """Return a user by exact username, or ``None`` when no user has it.

    Args:
        username: The username.
        db: Database session.

    Returns:
        The user record, or ``None``.
    """
    return users_crud.get_user_by_username(username, db)


def list_admin_users(db: Session) -> list[users_schema.UsersRead]:
    """Return every admin user.

    Args:
        db: Database session.

    Returns:
        The admin users, empty when there are none.
    """
    return users_crud.get_users_admin(db)


def require_admin_users(db: Session) -> list[users_schema.UsersRead]:
    """Return every admin user, of which there must be at least one.

    Args:
        db: Database session.

    Returns:
        The admin users.

    Raises:
        NotFoundError: If there are no admin users.
    """
    return users_service.require_admin_users(db)


def create_signup_user(
    user: users_schema.UsersSignup,
    server_settings: server_settings_schema.ServerSettingsRead,
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
    persist_credential: bool = True,
) -> users_schema.UsersRead:
    """Create a user through sign-up or SSO, with their default data, and commit.

    Args:
        user: User sign-up data.
        server_settings: Server config for sign-up requirements.
        identity_service: Identity service that hashes and stores the password.
        db: Database session.
        persist_credential: When True, validate the supplied password and store its hash.
            SSO-created accounts pass False so they stay SSO-only.

    Returns:
        The created user.

    Raises:
        ConflictError: If the username or email is already taken.
    """
    return users_service.create_signup_user(user, server_settings, identity_service, db, persist_credential)


def stage_email_verification(
    user_id: int,
    server_settings: server_settings_schema.ServerSettingsRead,
    db: Session,
) -> None:
    """Stage a user's email as verified, activating them unless admin approval is pending.

    Args:
        user_id: The user to verify.
        server_settings: Server config that decides whether approval is still required.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    users_service.stage_email_verification(user_id, server_settings, db)


def edit_user(user_id: int, user: users_schema.UsersRead, db: Session) -> users_schema.UsersRead:
    """Stage an administrative edit of a user.

    Args:
        user_id: The user to update.
        user: The user data to apply.
        db: Database session.

    Returns:
        The updated user.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    return users_service.stage_user_edit(user_id, user, db)


def edit_profile(user_id: int, profile: users_schema.ProfileUpdate, db: Session) -> users_schema.UsersRead:
    """Stage a self-service profile update, keeping only the allow-listed fields.

    Args:
        user_id: The authenticated user.
        profile: The validated self-service payload.
        db: Database session.

    Returns:
        The updated user.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    return users_service.stage_profile_edit(user_id, profile, db)


async def upload_user_photo(
    user_id: int,
    file: UploadFile,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> str:
    """Validate and store a user's photo, record its key and commit.

    Args:
        user_id: The user whose photo is being saved.
        file: The uploaded image.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The storage key of the saved photo.

    Raises:
        NotFoundError: If the user does not exist.
        InvalidInputError: If the upload has no filename.
        UnsupportedMediaTypeError: If the extension is not an allowed image type.
    """
    return await users_photo_service.upload_photo(user_id, file, storage, db)


def delete_user_photo(user_id: int, storage: platform_providers.StorageProvider, db: Session) -> None:
    """Clear a user's photo reference, commit, then delete the stored blobs.

    Args:
        user_id: The user whose photo to delete.
        storage: The platform storage provider.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    users_photo_service.delete_photo(user_id, storage, db)


def local_today(user_id: int, db: Session) -> date:
    """Return today's calendar date in the user's own timezone.

    "Which day is it?" is a local question the server cannot answer from its own clock, and
    the answer belongs to the users module because the timezone does. Consumers that bucket by
    day (activity summaries, week/month stats) resolve it here rather than reading
    ``users.timezone`` themselves.

    Args:
        user_id: The user whose "today" to resolve.
        db: Database session.

    Returns:
        The user's current calendar date.
    """
    return users_service.user_local_today(user_id, db)


def resolve_timezone(user_id: int, db: Session) -> str:
    """Return the user's IANA timezone, falling back to the server default.

    Consumers that bucket timestamps into calendar days (health entries) resolve the zone here
    instead of reading ``users.timezone`` themselves.

    Args:
        user_id: The user whose timezone to resolve.
        db: Database session.

    Returns:
        An IANA timezone name.
    """
    return users_service.resolve_user_timezone(user_id, db)


def timezone_or_default(timezone: str | None) -> str:
    """Return the given IANA timezone, or the server default when it is unset.

    ``users.timezone`` is nullable, so a consumer holding a user record still has to resolve the
    fallback; doing it here keeps the fallback rule in one place.

    Args:
        timezone: An IANA timezone name, or ``None``.

    Returns:
        An IANA timezone name.
    """
    return users_service.timezone_or_default(timezone)
