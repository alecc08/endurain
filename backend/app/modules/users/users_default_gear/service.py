"""Application logic for user default gear.

Decides who may edit which settings and which gears they may point at, and owns the
commit for the user's own requests. What other modules may consume lives in
:mod:`modules.users.users_default_gear.integration_service`.
"""

from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.logger as core_logger
import modules.gears.gear.integration_service as gears_integration
import modules.users.users_default_gear.crud as users_default_gear_crud
import modules.users.users_default_gear.schema as users_default_gear_schema

logger = core_logger.get_logger(__name__)


def get_default_gear(user_id: int, db: Session) -> users_default_gear_schema.UsersDefaultGearRead | None:
    """Return a user's default gear settings.

    Args:
        user_id: The user to read settings for.
        db: Database session.

    Returns:
        The default gear settings, or None if the user has none.
    """
    return users_default_gear_crud.get_user_default_gear_by_user_id(user_id, db)


def stage_default_gear_edit(
    user_default_gear: users_default_gear_schema.UsersDefaultGearUpdate,
    user_id: int,
    db: Session,
) -> users_default_gear_schema.UsersDefaultGearRead:
    """Stage an update of a user's default gear after checking the edit is allowed.

    Args:
        user_default_gear: The fields to change.
        user_id: The user whose settings are edited.
        db: Database session.

    Returns:
        The updated default gear settings.

    Raises:
        PermissionDeniedError: If the update names another user.
        NotFoundError: If a gear is not the user's, or the user has no settings.
    """
    if user_default_gear.user_id != user_id:
        logger.warning(
            "Refused an edit of another user's default gear",
            extra=core_logger.context(user_id=user_id, target_user_id=user_default_gear.user_id),
        )
        raise core_exceptions.PermissionDeniedError("Cannot edit default gear for another user.")

    changes = user_default_gear.model_dump(exclude_unset=True, exclude={"user_id", "id"})
    gears_integration.require_owned_gears(user_id, changes.values(), db)

    return users_default_gear_crud.edit_user_default_gear(user_default_gear, user_id, db)


def edit_default_gear(
    user_default_gear: users_default_gear_schema.UsersDefaultGearUpdate,
    user_id: int,
    db: Session,
) -> users_default_gear_schema.UsersDefaultGearRead:
    """Update a user's default gear settings and commit.

    Args:
        user_default_gear: The fields to change.
        user_id: The user whose settings are edited.
        db: Database session.

    Returns:
        The updated default gear settings.

    Raises:
        PermissionDeniedError: If the update names another user.
        NotFoundError: If a gear is not the user's, or the user has no settings.
    """
    updated = stage_default_gear_edit(user_default_gear, user_id, db)
    db.commit()
    logger.info("Default gear updated", extra=core_logger.context(user_id=user_id))
    return updated
