"""Application logic for the authenticated user's profile.

Assembles the profile from the packages that own its parts, applies the user's own edits and
runs the profile export and import. Authentication concerns (sessions, MFA, identity provider
links) stay behind the auth boundary and are called straight from the router.
"""

import asyncio
import os
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import jasil.providers as platform_providers
from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.logger as core_logger
import modules.users.users.integration_service as users_integration
import modules.users.users.schema as users_schema
import modules.users.users_integrations.integration_service as user_integrations_integration
import modules.users.users_privacy_settings.integration_service as users_privacy_settings_integration
import modules.users.users_privacy_settings.schema as users_privacy_settings_schema
import modules.users.users_profile.exceptions as profile_exceptions
import modules.users.users_profile.export_service as profile_export_service
import modules.users.users_profile.import_service as profile_import_service
import modules.users.users_profile.utils as profile_utils

if TYPE_CHECKING:
    import modules.auth.dependencies as auth_dependencies
    import modules.auth.identity_service as auth_identity_service

logger = core_logger.get_logger(__name__)

#: Server-managed secrets and privileged attributes that never leave in an export.
_NON_EXPORTED_USER_FIELDS = (
    "password",
    "mfa_secret",
    "access_type",
    "active",
    "mfa_enabled",
    "email_verified",
    "pending_admin_approval",
)

#: Import failures caused by the file the user supplied, which are reported as a refusal.
_REJECTED_FILE_ERRORS = (
    profile_exceptions.ImportValidationError,
    profile_exceptions.FileFormatError,
    profile_exceptions.FileSizeError,
    profile_exceptions.ActivityLimitError,
    profile_exceptions.ZipStructureError,
    profile_exceptions.JSONParseError,
    profile_exceptions.SchemaValidationError,
)


def get_profile(
    user_id: int,
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
) -> users_schema.UsersMe:
    """Assemble the authenticated user's profile.

    Args:
        user_id: The authenticated user.
        identity_service: Identity service that answers the authentication status.
        db: Database session.

    Returns:
        The user with their integration links, privacy settings and authentication status.

    Raises:
        NotFoundError: If the user, their integrations or their privacy settings are missing.
    """
    user = users_integration.require_user(user_id, db)

    user_integrations = user_integrations_integration.get_user_integrations(user.id, db)
    if user_integrations is None:
        raise core_exceptions.NotFoundError("User integrations not found")

    privacy_settings = users_privacy_settings_integration.get_privacy_settings(user.id, db)
    if privacy_settings is None:
        raise core_exceptions.NotFoundError("User privacy settings not found")

    return users_schema.UsersMe.model_validate(user).model_copy(
        update={
            "is_strava_linked": 1 if user_integrations.strava_token else 0,
            "is_garminconnect_linked": 1 if user_integrations.garminconnect_token else 0,
            "default_activity_visibility": privacy_settings.default_activity_visibility,
            "hide_activity_start_time": privacy_settings.hide_activity_start_time,
            "hide_activity_location": privacy_settings.hide_activity_location,
            "hide_activity_map": privacy_settings.hide_activity_map,
            "hide_activity_hr": privacy_settings.hide_activity_hr,
            "hide_activity_power": privacy_settings.hide_activity_power,
            "hide_activity_cadence": privacy_settings.hide_activity_cadence,
            "hide_activity_elevation": privacy_settings.hide_activity_elevation,
            "hide_activity_speed": privacy_settings.hide_activity_speed,
            "hide_activity_pace": privacy_settings.hide_activity_pace,
            "hide_activity_laps": privacy_settings.hide_activity_laps,
            "hide_activity_workout_sets_steps": privacy_settings.hide_activity_workout_sets_steps,
            "hide_activity_gear": privacy_settings.hide_activity_gear,
            # Lets the frontend tell SSO-only accounts from accounts with a local password, so
            # step-up prompts can hide the password field. Both flags are auth-owned and come
            # through the auth boundary, so the hash never leaves it.
            "has_local_password": identity_service.has_local_password(user_id),
            "mfa_enabled": identity_service.get_mfa_status(user_id).mfa_enabled,
        }
    )


def edit_profile(user_id: int, profile: users_schema.ProfileUpdate, db: Session) -> None:
    """Apply the user's own profile edits and commit.

    Args:
        user_id: The authenticated user.
        profile: The allow-listed profile fields to change.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    users_integration.edit_profile(user_id, profile, db)
    db.commit()
    logger.info("Profile updated", extra=core_logger.context(user_id=user_id))


def change_email(
    user_id: int,
    change: users_schema.EmailChange,
    identity_service: "auth_identity_service.IdentityService",
    step_up_store: "auth_dependencies.StepUpStore",
    db: Session,
) -> None:
    """Change the authenticated user's email after step-up verification, and ask them to verify it.

    The address is where password resets go, so a stolen access token alone must not be able to
    redirect it. The new address starts unverified; a verification link is emailed to it when the
    server can send mail.

    Args:
        user_id: The authenticated user.
        change: The new address with the step-up credentials.
        identity_service: Identity service that verifies the step-up and queues the email.
        step_up_store: Step-up lockout store.
        db: Database session.

    Raises:
        HTTPException: If step-up verification fails.
        NotFoundError: If the user does not exist.
        ConflictError: If the email is already taken.
    """
    identity_service.verify_step_up(
        users_schema.StepUpVerification(**change.model_dump(exclude={"email"})), user_id, step_up_store
    )
    try:
        users_integration.stage_email_change(user_id, change.email, db)
    except core_exceptions.ConflictError:
        db.rollback()
        raise
    db.commit()
    logger.info("Email changed", extra=core_logger.context(user_id=user_id))

    if not identity_service.request_email_reverification(user_id):
        logger.warning(
            "Email changed but cannot be verified: outgoing email is not configured",
            extra=core_logger.context(user_id=user_id),
        )


def edit_privacy_settings(
    user_id: int,
    privacy_settings: users_privacy_settings_schema.UsersPrivacySettingsUpdate,
    db: Session,
) -> None:
    """Apply the user's own privacy settings and commit.

    Args:
        user_id: The authenticated user.
        privacy_settings: The privacy fields to change.
        db: Database session.

    Raises:
        NotFoundError: If the user has no privacy settings.
    """
    users_privacy_settings_integration.edit_privacy_settings(user_id, privacy_settings, db)
    db.commit()
    logger.info("Privacy settings updated", extra=core_logger.context(user_id=user_id))


def delete_account(
    user_id: int,
    step_up: users_schema.StepUpVerification,
    identity_service: "auth_identity_service.IdentityService",
    step_up_store: "auth_dependencies.StepUpStore",
    storage: platform_providers.StorageProvider,
    db: Session,
) -> None:
    """Delete the authenticated user's account and all of their data.

    The right to erasure: the user, their activities and stored files, health records, gear, goals,
    integrations, privacy settings, sessions and every other row that references them are removed. The
    caller must prove their identity again first, so a stolen access token cannot erase an account.

    Args:
        user_id: The authenticated user.
        step_up: Step-up verification payload (password, and an MFA code when MFA is enabled).
        identity_service: Identity service that verifies the step-up.
        step_up_store: Step-up lockout store.
        storage: The platform storage provider.
        db: Database session.

    Raises:
        HTTPException: If step-up verification fails.
        ConflictError: If the user is the only administrator.
    """
    identity_service.verify_step_up(step_up, user_id, step_up_store)
    users_integration.delete_user(user_id, storage, db)
    logger.info("Account deleted by its owner", extra=core_logger.context(user_id=user_id))


def export_profile(
    user_id: int, storage: platform_providers.StorageProvider, db: Session
) -> tuple[Generator[bytes], int]:
    """Build the export of the user's profile data as a ZIP archive and prepare it for streaming.

    The archive is complete before this returns, so every failure surfaces as an error response
    rather than as a download that stops half way.

    Args:
        user_id: The authenticated user.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The archive, produced chunk by chunk, and its size in bytes.

    Raises:
        NotFoundError: If the user does not exist.
        DomainError: If the archive cannot be built.
    """
    user = users_integration.require_user(user_id, db)

    user_dict = profile_utils.sqlalchemy_obj_to_dict(user)
    for field in _NON_EXPORTED_USER_FIELDS:
        user_dict.pop(field, None)

    exporter = profile_export_service.ExportService(user_id, storage, db)
    try:
        archive = exporter.build_export_archive(user_dict)
    except profile_exceptions.ProfileOperationError as err:
        logger.error("Profile export failed", exc_info=err, extra=core_logger.context(user_id=user_id))
        raise profile_exceptions.to_domain_error(err, "profile data export") from err

    size = archive.seek(0, os.SEEK_END)
    archive.seek(0)
    logger.info("Profile data exported", extra=core_logger.context(user_id=user_id, size_bytes=size))
    return profile_export_service.stream_archive(archive), size


def import_profile(
    user_id: int,
    zip_data: bytes,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> dict[str, Any]:
    """Import profile data from a ZIP archive.

    Args:
        user_id: The authenticated user.
        zip_data: The validated archive.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The import result with the counts of imported items.

    Raises:
        DomainError: If the archive is rejected or the import fails.
    """
    importer = profile_import_service.ImportService(user_id, storage, db)
    try:
        # The importer awaits file validation, so it needs a loop; this runs on a worker thread
        # with none, and the importer shares no loop-bound resources.
        result = asyncio.run(importer.import_from_zip_data(zip_data))
    except _REJECTED_FILE_ERRORS as err:
        logger.warning(
            "Profile import rejected the archive",
            extra=core_logger.context(user_id=user_id, reason=type(err).__name__),
        )
        raise profile_exceptions.to_domain_error(err, "profile data import") from err
    except ValueError as err:
        logger.warning(
            "Profile import rejected the archive", extra=core_logger.context(user_id=user_id, reason=str(err))
        )
        raise core_exceptions.InvalidInputError(str(err)) from err
    except (profile_exceptions.ProfileOperationError, MemoryError) as err:
        logger.error("Profile import failed", exc_info=err, extra=core_logger.context(user_id=user_id))
        raise profile_exceptions.to_domain_error(err, "profile data import") from err
    except Exception as err:
        logger.error("Profile import failed unexpectedly", exc_info=err, extra=core_logger.context(user_id=user_id))
        raise core_exceptions.ProcessingError(
            "Import failed due to an internal error. Please try again or contact support."
        ) from err

    logger.info("Profile data imported", extra=core_logger.context(user_id=user_id, imported=result["imported"]))
    return result
