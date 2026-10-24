"""Public user router for unauthenticated user info access."""

from fastapi import APIRouter, status

import core.dependencies as core_dependencies
import modules.users.users.schema as users_schema
import modules.users.users.service as users_service

# Define the API router
router = APIRouter()


@router.get(
    "/id/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UserPublicRead | None,
)
def read_users_id(
    user_id: core_dependencies.PositiveId,
    db: core_dependencies.DbSession,
) -> users_schema.UserPublicRead | None:
    """Get public user info by ID.

    Args:
        user_id: The user ID to retrieve.
        db: Database session dependency.

    Returns:
        User data if found and public sharing enabled.
    """
    return users_service.get_public_user(user_id, db)
