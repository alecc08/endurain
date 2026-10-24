"""Application logic for user goals.

Decides who may edit which goal and owns the commit for the user's own requests. The
progress calculation is :mod:`modules.users.users_goals.progress_service`; what other
modules may consume lives in :mod:`modules.users.users_goals.integration_service`.
"""

from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.logger as core_logger
import modules.users.users_goals.crud as user_goals_crud
import modules.users.users_goals.schema as user_goals_schema

logger = core_logger.get_logger(__name__)


def list_goals(
    user_id: int,
    db: Session,
    interval: user_goals_schema.Interval | None = None,
    activity_type: user_goals_schema.ActivityType | None = None,
    goal_type: user_goals_schema.GoalType | None = None,
) -> list[user_goals_schema.UsersGoalRead]:
    """List a user's goals with optional filters.

    Args:
        user_id: The user whose goals to list.
        db: Database session.
        interval: Optional filter by goal interval.
        activity_type: Optional filter by activity type.
        goal_type: Optional filter by goal type.

    Returns:
        The goals matching the filters.
    """
    return user_goals_crud.get_user_goals_by_user_id(user_id, db, interval, activity_type, goal_type)


def create_goal(
    user_id: int,
    user_goal: user_goals_schema.UsersGoalCreate,
    db: Session,
) -> user_goals_schema.UsersGoalRead:
    """Create a goal for a user and commit.

    Args:
        user_id: The user the goal belongs to.
        user_goal: Goal data to create.
        db: Database session.

    Returns:
        The created goal.

    Raises:
        ConflictError: If the user already has a goal for this activity type, interval and goal type.
    """
    created = user_goals_crud.create_user_goal(user_id, user_goal, db)
    db.commit()
    logger.debug("User goal created", extra=core_logger.context(user_id=user_id, goal_id=created.id))
    return created


def update_goal(
    user_id: int,
    user_goal: user_goals_schema.UsersGoalUpdate,
    db: Session,
) -> user_goals_schema.UsersGoalRead:
    """Update a user's goal and commit.

    Args:
        user_id: The user who owns the goal.
        user_goal: The fields to change.
        db: Database session.

    Returns:
        The updated goal.

    Raises:
        PermissionDeniedError: If the update names another user.
        NotFoundError: If the user has no such goal.
    """
    if user_goal.user_id != user_id:
        logger.warning(
            "Refused an edit of another user's goal",
            extra=core_logger.context(user_id=user_id, target_user_id=user_goal.user_id),
        )
        raise core_exceptions.PermissionDeniedError("Cannot edit user goal for another user")

    updated = user_goals_crud.update_user_goal(user_id, user_goal, db)
    db.commit()
    logger.debug("User goal updated", extra=core_logger.context(user_id=user_id, goal_id=updated.id))
    return updated


def delete_goal(user_id: int, goal_id: int, db: Session) -> None:
    """Delete a user's goal and commit.

    Args:
        user_id: The user who owns the goal.
        goal_id: The goal to delete.
        db: Database session.

    Raises:
        NotFoundError: If the user has no such goal.
    """
    user_goals_crud.delete_user_goal(user_id, goal_id, db)
    db.commit()
    logger.debug("User goal deleted", extra=core_logger.context(user_id=user_id, goal_id=goal_id))
