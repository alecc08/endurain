"""User default gear API endpoints."""

from fastapi import APIRouter, status

import core.dependencies as core_dependencies
import modules.auth.dependencies as auth_dependencies
import modules.users.users_default_gear.schema as user_default_gear_schema
import modules.users.users_default_gear.service as user_default_gear_service

# Define the API router
router = APIRouter()


@router.get(
    "",
    response_model=user_default_gear_schema.UsersDefaultGearRead,
    status_code=status.HTTP_200_OK,
)
async def read_user_default_gear(
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> user_default_gear_schema.UsersDefaultGearRead | None:
    """
    Retrieve default gear settings for authenticated user.

    Args:
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        User default gear settings.
    """
    return user_default_gear_service.get_default_gear(token_user_id, db)


@router.put(
    "",
    response_model=user_default_gear_schema.UsersDefaultGearRead,
    status_code=status.HTTP_200_OK,
)
async def edit_user_default_gear(
    user_default_gear: user_default_gear_schema.UsersDefaultGearUpdate,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> user_default_gear_schema.UsersDefaultGearRead:
    """
    Update default gear settings for authenticated user.

    Args:
        user_default_gear: Updated gear settings.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        Updated user default gear settings.
    """
    return user_default_gear_service.edit_default_gear(user_default_gear, token_user_id, db)
