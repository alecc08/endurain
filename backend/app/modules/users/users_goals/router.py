"""User goals API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

import core.dependencies as core_dependencies
import core.rate_limit as core_rate_limit
import modules.auth.dependencies as auth_dependencies
import modules.users.users_goals.progress_service as user_goals_progress_service
import modules.users.users_goals.schema as user_goals_schema
import modules.users.users_goals.service as user_goals_service

# Define the API router
router = APIRouter()


@router.get(
    "",
    response_model=list[user_goals_schema.UsersGoalRead],
    status_code=status.HTTP_200_OK,
)
def get_user_goals(
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
    interval: Annotated[
        user_goals_schema.Interval | None,
        Query(description="Filter by goal interval"),
    ] = None,
    activity_type: Annotated[
        user_goals_schema.ActivityType | None,
        Query(description="Filter by activity type"),
    ] = None,
    goal_type: Annotated[
        user_goals_schema.GoalType | None,
        Query(description="Filter by goal type"),
    ] = None,
) -> list[user_goals_schema.UsersGoalRead]:
    """Retrieve goals for the authenticated user with optional filters.

    Args:
        token_user_id: User ID from access token.
        db: Database session dependency.
        interval: Optional filter by goal interval.
        activity_type: Optional filter by activity type.
        goal_type: Optional filter by goal type.

    Returns:
        List of user goal objects matching the filters.
    """
    return user_goals_service.list_goals(
        user_id=token_user_id,
        db=db,
        interval=interval,
        activity_type=activity_type,
        goal_type=goal_type,
    )


@router.get(
    "/results",
    response_model=list[user_goals_schema.UsersGoalProgress],
    status_code=status.HTTP_200_OK,
)
def get_user_goals_results(
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> list[user_goals_schema.UsersGoalProgress]:
    """Calculate and retrieve goal progress for authenticated user.

    Args:
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        List of goal progress objects, empty if no goals.
    """
    return user_goals_progress_service.get_goals_progress(token_user_id, db)


@router.post(
    "",
    response_model=user_goals_schema.UsersGoalRead,
    status_code=status.HTTP_201_CREATED,
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def create_user_goal(
    request: Request,
    user_goal: user_goals_schema.UsersGoalCreate,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> user_goals_schema.UsersGoalRead:
    """Create a new goal for the authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        user_goal: Goal data to create.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        The created goal object.
    """
    return user_goals_service.create_goal(token_user_id, user_goal, db)


@router.put(
    "",
    status_code=status.HTTP_200_OK,
    response_model=user_goals_schema.UsersGoalRead,
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def update_user_goal(
    request: Request,
    user_goal: user_goals_schema.UsersGoalUpdate,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> user_goals_schema.UsersGoalRead:
    """Update an existing goal for the authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        user_goal: Updated goal data.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        The updated goal object.
    """
    return user_goals_service.update_goal(token_user_id, user_goal, db)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_user_goal(
    request: Request,
    goal_id: core_dependencies.PositiveId,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> None:
    """Delete a goal for the authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        goal_id: ID of the goal to delete.
        token_user_id: User ID from access token.
        db: Database session dependency.
    """
    return user_goals_service.delete_goal(token_user_id, goal_id, db)
