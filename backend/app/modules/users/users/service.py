"""Application logic for users.

Decides who may change what on an account, orchestrates the account lifecycle across
the packages that hang rows off a user, and owns the commit for the unit it runs.
Profile photo storage is :mod:`modules.users.users.photo_service`; what other modules
may consume lives in :mod:`modules.users.users.integration_service`.
"""

from datetime import date as datetime_date
from typing import TYPE_CHECKING

import jasil.providers as platform_providers
from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.logger as core_logger
import core.timezone as core_timezone
import modules.activities.activity.integration_service as activity_integration
import modules.health.health_targets.integration_service as health_targets_integration
import modules.health.health_weight.integration_service as health_weight_integration
import modules.server_settings.integration_service as server_settings_integration
import modules.server_settings.schema as server_settings_schema
import modules.users.users.constants as users_constants
import modules.users.users.crud as users_crud
import modules.users.users.photo_service as users_photo_service
import modules.users.users.schema as users_schema
import modules.users.users_default_gear.integration_service as users_default_gear_integration
import modules.users.users_integrations.integration_service as user_integrations_integration
import modules.users.users_privacy_settings.integration_service as users_privacy_settings_integration

if TYPE_CHECKING:
    import modules.auth.identity_service as auth_identity_service

logger = core_logger.get_logger(__name__)


def get_user(user_id: int, db: Session) -> users_schema.UsersRead | None:
    """Return a user by id.

    Args:
        user_id: The user to look up.
        db: Database session.

    Returns:
        The user, or None if there is none.
    """
    return users_crud.get_user_by_id(user_id, db)


def require_user(user_id: int, db: Session) -> users_schema.UsersRead:
    """Return a user by id, which must exist.

    Args:
        user_id: The user to look up.
        db: Database session.

    Returns:
        The user.

    Raises:
        NotFoundError: If the user does not exist.
    """
    user = users_crud.get_user_by_id(user_id, db)
    if user is None:
        raise core_exceptions.NotFoundError("User not found")

    return user


def require_active_user(user: users_schema.UsersRead) -> None:
    """Require a user to be active.

    Args:
        user: The user to check.

    Raises:
        PermissionDeniedError: If the user is not active.
    """
    if not user.active:
        logger.warning("Refused an inactive user", extra=core_logger.context(user_id=user.id))
        raise core_exceptions.PermissionDeniedError("Inactive user")


def require_admin_users(db: Session) -> list[users_schema.UsersRead]:
    """Return every admin user, of which there must be at least one.

    Args:
        db: Database session.

    Returns:
        The admin users.

    Raises:
        NotFoundError: If there are no admin users.
    """
    admins = users_crud.get_users_admin(db)
    if not admins:
        raise core_exceptions.NotFoundError("No admin users found")

    return admins


def get_public_user(user_id: int, db: Session) -> users_schema.UsersRead | None:
    """Return a user for an unauthenticated viewer, when public sharing allows it.

    Args:
        user_id: The user to look up.
        db: Database session.

    Returns:
        The user, or None if there is none or public user info is not shared.
    """
    server_settings = server_settings_integration.get_server_settings(db)
    if not server_settings.public_shareable_links or not server_settings.public_shareable_links_user_info:
        return None

    return users_crud.get_user_by_id(user_id, db)


def get_user_by_username(username: str, db: Session) -> users_schema.UsersRead | None:
    """Return a user by exact username.

    Args:
        username: Username to search for.
        db: Database session.

    Returns:
        The user, or None if there is none.
    """
    return users_crud.get_user_by_username(username, db)


def search_users_by_username(username: str, db: Session) -> list[users_schema.UsersRead]:
    """Return the users whose username contains the search term.

    Args:
        username: The partial username to search for.
        db: Database session.

    Returns:
        The matching users.
    """
    return users_crud.search_users_by_username(username, db)


def get_user_by_email(email: str, db: Session) -> users_schema.UsersRead | None:
    """Return a user by email address.

    Args:
        email: Email address to search for.
        db: Database session.

    Returns:
        The user, or None if there is none.
    """
    return users_crud.get_user_by_email(email, db)


def list_users(
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
    *,
    page_number: int | None = None,
    num_records: int | None = None,
    show_inactive: bool | None = None,
    show_email_unverified: bool | None = None,
    show_pending_approval: bool | None = None,
    show_external_auth: bool | None = None,
    show_local_auth: bool | None = None,
) -> users_schema.UsersListResponse:
    """List a page of users with their authentication status.

    The external/local filters are applied after the page is read, so a page may hold fewer
    records than ``num_records``.

    Args:
        identity_service: Identity service that answers the authentication status.
        db: Database session.
        page_number: Optional page number.
        num_records: Optional number of records per page.
        show_inactive: If False, excludes inactive users.
        show_email_unverified: If False, excludes users with unverified emails.
        show_pending_approval: If False, excludes users pending admin approval.
        show_external_auth: If False, excludes users with a linked identity provider.
        show_local_auth: If False, excludes users with no linked identity provider.

    Returns:
        The page of users and the total matching the first three filters.
    """
    total = users_crud.get_users_number(db, show_inactive, show_email_unverified, show_pending_approval)
    users = users_crud.get_users_with_pagination(
        db, page_number, num_records, show_inactive, show_email_unverified, show_pending_approval
    )

    user_ids = [user.id for user in users]
    idp_counts = identity_service.get_identity_link_counts_for_users(user_ids)
    mfa_enabled_map = identity_service.get_mfa_enabled_for_users(user_ids)

    records: list[users_schema.UsersRead] = []
    for user in users:
        idp_count = idp_counts.get(user.id, 0)
        user.external_auth_count = idp_count
        user.mfa_enabled = mfa_enabled_map.get(user.id, False)

        if idp_count > 0 and show_external_auth is False:
            continue
        if idp_count == 0 and show_local_auth is False:
            continue

        records.append(user)

    return users_schema.UsersListResponse(
        total=total,
        num_records=num_records,
        page_number=page_number,
        records=records,
    )


def _stage_default_data(user_id: int, identity_service: "auth_identity_service.IdentityService", db: Session) -> None:
    """Stage the rows every new account starts with and commit them.

    Args:
        user_id: ID of the new user.
        identity_service: Identity service that creates the auth-owned MFA row.
        db: Database session.
    """
    user_integrations_integration.create_integrations(user_id, db)
    users_privacy_settings_integration.create_privacy_settings(user_id, db)
    health_targets_integration.create_health_targets(user_id, db)
    users_default_gear_integration.create_default_gear(user_id, db)
    db.commit()
    logger.info("Default rows created for a new user", extra=core_logger.context(user_id=user_id))

    # Created through the auth boundary, which owns that table and its transaction.
    identity_service.initialize_user_mfa(user_id)


def create_user(
    user: users_schema.UsersCreate,
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
) -> users_schema.UsersRead:
    """Create a user as an administrator, with their password and default data.

    Args:
        user: User creation data with a plain text password.
        identity_service: Identity service that hashes and stores the password.
        db: Database session.

    Returns:
        The created user.

    Raises:
        ConflictError: If the username or email is already taken.
        HTTPException: If the password fails the configured policy.
    """
    server_settings = server_settings_integration.get_server_settings(db)
    access_type = users_schema.normalize_access_type(user.access_type)
    hashed_password = identity_service.validate_and_hash_password_for_user(server_settings, access_type, user.password)

    fields = user.model_dump(exclude={"password", "access_type", "mfa_enabled"})
    fields.update(username=user.username.lower(), email=user.email.lower(), access_type=access_type)
    try:
        created = users_crud.create_user(fields, db)
    except core_exceptions.ConflictError:
        db.rollback()
        raise
    db.commit()
    logger.info("User created", extra=core_logger.context(user_id=created.id))

    identity_service.set_local_password_hash(created.id, hashed_password)
    _stage_default_data(created.id, identity_service, db)
    return created


def create_signup_user(
    user: users_schema.UsersSignup,
    server_settings: server_settings_schema.ServerSettingsRead,
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
    persist_credential: bool = True,
) -> users_schema.UsersRead:
    """Create a user through sign-up or SSO, with their default data.

    The account's state follows the server's sign-up policy: it starts inactive when email
    verification or admin approval is required.

    Args:
        user: User sign-up data.
        server_settings: Server config for sign-up requirements.
        identity_service: Identity service that hashes and stores the password.
        db: Database session.
        persist_credential: When True, validate the supplied password and store its hash.
            SSO-created accounts pass False so they get no local credential and stay SSO-only.

    Returns:
        The created user.

    Raises:
        ConflictError: If the username or email is already taken.
        HTTPException: If the password fails the configured policy.
    """
    needs_verification = server_settings.signup_require_email_verification
    needs_approval = server_settings.signup_require_admin_approval

    fields = user.model_dump(
        exclude={"username", "email", "access_type", "active", "email_verified", "pending_admin_approval", "password"}
    )
    fields.update(
        username=user.username.lower(),
        email=user.email.lower(),
        access_type=users_schema.UserAccessType.REGULAR.value,
        active=not (needs_verification or needs_approval),
        email_verified=not (needs_verification or needs_approval),
        pending_admin_approval=needs_approval,
    )

    hashed_password: str | None = None
    if persist_credential:
        hashed_password = identity_service.validate_and_hash_password_for_user(
            server_settings, users_schema.UserAccessType.REGULAR.value, user.password
        )

    try:
        created = users_crud.create_user(fields, db)
    except core_exceptions.ConflictError as err:
        db.rollback()
        # Abstract message to reduce information leakage.
        raise core_exceptions.ConflictError("Unable to create user.") from err
    db.commit()
    logger.info("User signed up", extra=core_logger.context(user_id=created.id))

    if hashed_password is not None:
        identity_service.set_local_password_hash(created.id, hashed_password)
    _stage_default_data(created.id, identity_service, db)
    return created


def _recalculate_bmi_if_height_changed(
    before: users_schema.UsersRead, after: users_schema.UsersRead, db: Session
) -> None:
    """Stage a BMI recalculation of the user's weight records when their height changed.

    Args:
        before: The user before the edit.
        after: The user after the edit.
        db: Database session.
    """
    if before.height != after.height:
        health_weight_integration.recalculate_bmi_for_user(
            after.id, float(after.height) if after.height is not None else None, db
        )


def stage_user_edit(user_id: int, user: users_schema.UsersRead, db: Session) -> users_schema.UsersRead:
    """Stage an administrative edit of a user.

    Intended for admin endpoints that legitimately set fields like ``access_type``, ``active``
    or ``pending_admin_approval``. Self-service updates go through :func:`stage_profile_edit`,
    whose allow-list prevents privilege escalation through mass assignment.

    Args:
        user_id: ID of the user to update.
        user: The user data to apply.
        db: Database session.

    Returns:
        The updated user.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    existing = require_user(user_id, db)

    # ``photo_path`` is excluded because the read schema exposes a resolved, signed URL while
    # the column stores a storage key: echoing the read model back would overwrite the key
    # with its own URL. The photo is owned solely by the upload and delete operations.
    changes = user.model_dump(
        exclude_unset=True,
        exclude={"password", "external_auth_count", "mfa_enabled", "photo_path"},
    )
    changes["username"] = user.username.lower()

    updated = users_crud.update_user(user_id, changes, db)
    _recalculate_bmi_if_height_changed(existing, updated, db)
    return updated


def edit_user(
    user_id: int,
    user: users_schema.UsersRead,
    identity_service: "auth_identity_service.IdentityService",
    db: Session,
) -> users_schema.UsersRead:
    """Edit a user as an administrator, commit, and add their authentication status.

    Args:
        user_id: ID of the user to update.
        user: The user data to apply.
        identity_service: Identity service that answers the authentication status.
        db: Database session.

    Returns:
        The updated user, with its identity provider count and MFA status.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    try:
        updated = stage_user_edit(user_id, user, db)
    except core_exceptions.ConflictError:
        db.rollback()
        raise
    db.commit()
    logger.info("User edited by an administrator", extra=core_logger.context(user_id=user_id))

    updated.external_auth_count = identity_service.get_identity_link_counts_for_users([updated.id]).get(updated.id, 0)
    updated.mfa_enabled = identity_service.get_mfa_enabled_for_users([updated.id]).get(updated.id, False)
    return updated


def stage_profile_edit(user_id: int, profile: users_schema.ProfileUpdate, db: Session) -> users_schema.UsersRead:
    """Stage a self-service profile update, keeping only the allow-listed fields.

    Administrative attributes such as ``access_type``, ``active``, ``email_verified`` and
    ``pending_admin_approval`` are never written from this path, even if a payload smuggles
    them through validation.

    Args:
        user_id: ID of the authenticated user.
        profile: The validated self-service payload.
        db: Database session.

    Returns:
        The updated user.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    existing = require_user(user_id, db)

    provided = profile.model_dump(exclude_unset=True)
    changes = {key: value for key, value in provided.items() if key in users_constants.PROFILE_SELF_SERVICE_FIELDS}
    for key in ("username", "email"):
        if isinstance(changes.get(key), str):
            changes[key] = changes[key].lower()

    updated = users_crud.update_user(user_id, changes, db)
    if "height" in changes:
        _recalculate_bmi_if_height_changed(existing, updated, db)
    return updated


def edit_profile(user_id: int, profile: users_schema.ProfileUpdate, db: Session) -> users_schema.UsersRead:
    """Apply a self-service profile update and commit.

    Args:
        user_id: ID of the authenticated user.
        profile: The validated self-service payload.
        db: Database session.

    Returns:
        The updated user.

    Raises:
        NotFoundError: If the user does not exist.
        ConflictError: If the username or email is already taken.
    """
    try:
        updated = stage_profile_edit(user_id, profile, db)
    except core_exceptions.ConflictError:
        db.rollback()
        raise
    db.commit()
    logger.info("User profile edited", extra=core_logger.context(user_id=user_id))
    return updated


def approve_user(user_id: int, db: Session) -> None:
    """Approve a pending user by activating them, and commit.

    Args:
        user_id: ID of the user to approve.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
        InvalidInputError: If the user's email is not verified.
    """
    if not require_user(user_id, db).email_verified:
        logger.warning("Refused to approve a user with an unverified email", extra=core_logger.context(user_id=user_id))
        raise core_exceptions.InvalidInputError("User email is not verified")

    users_crud.update_user(user_id, {"pending_admin_approval": False, "active": True}, db)
    db.commit()
    logger.info("User approved", extra=core_logger.context(user_id=user_id))


def stage_email_verification(
    user_id: int,
    server_settings: server_settings_schema.ServerSettingsRead,
    db: Session,
) -> None:
    """Stage a user's email as verified, activating them unless admin approval is pending.

    Args:
        user_id: ID of the user to verify.
        server_settings: Server config that decides whether approval is still required.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    changes: dict[str, bool] = {"email_verified": True}
    if not server_settings.signup_require_admin_approval:
        changes.update(pending_admin_approval=False, active=True)

    users_crud.update_user(user_id, changes, db)


def delete_user(user_id: int, storage: platform_providers.StorageProvider, db: Session) -> None:
    """Delete a user, their activities and their stored photo.

    The activities are removed explicitly instead of through the database cascade: the cascade
    tells nobody, so every thumbnail and stored source file the user produced would be orphaned
    in storage. Deleting through the activities surface publishes one ``activity.deleted`` per
    row, and the cleanup subscribers reclaim the blobs.

    Args:
        user_id: ID of the user to delete.
        storage: The platform storage provider.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    require_user(user_id, db)
    activity_integration.delete_all_activities_for_user(user_id, db)
    users_crud.delete_user(user_id, db)
    db.commit()
    logger.info("User deleted", extra=core_logger.context(user_id=user_id))

    users_photo_service.delete_photo_files(user_id, storage)


def timezone_or_default(timezone: str | None) -> str:
    """Return the given IANA timezone, or the server default when it is unset.

    ``users.timezone`` is nullable: accounts that predate the setting have none, in which case
    the server default is the only answer available.

    Args:
        timezone: An IANA timezone name, or None.

    Returns:
        An IANA timezone name.
    """
    return core_timezone.or_default(timezone)


def resolve_user_timezone(user_id: int, db: Session) -> str:
    """Return the athlete's IANA timezone, falling back to the server's.

    Args:
        user_id: The user whose timezone to resolve.
        db: Database session.

    Returns:
        An IANA timezone name.
    """
    user = users_crud.get_user_by_id(user_id, db)
    return timezone_or_default(user.timezone if user is not None else None)


def user_local_today(user_id: int, db: Session) -> datetime_date:
    """Return today's calendar date in the athlete's own timezone.

    Everything that answers "what did I do *today*?" must use this rather than ``date.today()``
    (the container's zone) or ``datetime.now(UTC).date()``: both put an athlete in UTC+13 a day
    behind for 13 hours out of every 24, and one in UTC-11 a day ahead for 11.

    Args:
        user_id: The user whose "today" to resolve.
        db: Database session.

    Returns:
        The user's current calendar date.
    """
    return core_timezone.today_in(resolve_user_timezone(user_id, db))
