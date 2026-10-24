"""Progress calculation for user goals against the user's activities."""

from sqlalchemy.orm import Session

import core.calendar as core_calendar
import core.exceptions as core_exceptions
import core.logger as core_logger
import core.timezone as core_timezone
import modules.activities.activity.integration_service as activity_integration
import modules.users.users.integration_service as users_integration
import modules.users.users_goals.crud as user_goals_crud
import modules.users.users_goals.schema as user_goals_schema
import modules.users.users_goals.utils as user_goals_utils
from modules.activities.activity.constants import ACTIVITY_TYPES_BY_SPORT

logger = core_logger.get_logger(__name__)

# Which activity types each goal counts. The sport groupings are owned by the
# activities module; a goal states which sports it spans, so a new running or
# cycling type starts counting towards goals the day it is added rather than
# whenever someone remembers this list exists.
_ACTIVITY_TYPE_MAP: dict[str, list[int]] = {
    user_goals_schema.ActivityType.RUN.value: [*ACTIVITY_TYPES_BY_SPORT["run"]],
    user_goals_schema.ActivityType.BIKE.value: [*ACTIVITY_TYPES_BY_SPORT["bike"]],
    user_goals_schema.ActivityType.SWIM.value: [*ACTIVITY_TYPES_BY_SPORT["swim"]],
    # Deliberately wider than the walk sport: a walking goal also counts hiking
    # and snowshoeing, which the stats view reports as their own sports.
    user_goals_schema.ActivityType.WALK.value: [
        *ACTIVITY_TYPES_BY_SPORT["walk"],
        *ACTIVITY_TYPES_BY_SPORT["hike"],
        *ACTIVITY_TYPES_BY_SPORT["snowshoeing"],
    ],
    # Crossfit, cardio training, HIIT and jump rope have no sport grouping of
    # their own: they are goal-only, so the ids are stated here.
    user_goals_schema.ActivityType.CARDIO.value: [20, 41, 46, 47],
}

_DEFAULT_ACTIVITY_TYPES: list[int] = [10, 19]


def calculate_user_goals(
    user_id: int,
    date: str | None,
    first_day_of_week: core_calendar.WeekdayValue,
    db: Session,
) -> list[user_goals_schema.UsersGoalProgress] | None:
    """Calculate progress for all user goals on a specified date.

    Args:
        user_id: The ID of the user.
        date: Date in YYYY-MM-DD format. If None, uses
            current date.
        db: SQLAlchemy database session.
        first_day_of_week: User's configured first weekday.

    Returns:
        List of UsersGoalProgress objects, or None if no
            goals found.

    Raises:
        InvalidInputError: If the date or interval is malformed.
    """
    if not date:
        # The athlete's own calendar day, not the server's. Anchoring on
        # ``datetime.now(UTC)`` rolled daily goals over at UTC midnight and
        # flipped weekly/monthly/yearly windows up to a day early or late, so
        # progress bars visibly reset at the wrong time for anyone off UTC.
        date = users_integration.local_today(user_id, db).strftime("%Y-%m-%d")
    try:
        goals: list[user_goals_schema.UsersGoalRead] = user_goals_crud.get_user_goals_by_user_id(user_id, db)

        if not goals:
            return None

        return [
            calculate_goal_progress_by_activity_type(
                goal,
                date,
                first_day_of_week,
                db,
            )
            for goal in goals
        ]
    except (ValueError, TypeError) as err:
        logger.error(
            "Invalid data while calculating user goals", exc_info=err, extra=core_logger.context(user_id=user_id)
        )
        raise core_exceptions.InvalidInputError("Invalid data provided") from err


def calculate_goal_progress_by_activity_type(
    goal: user_goals_schema.UsersGoalRead,
    date: str,
    first_day_of_week: core_calendar.WeekdayValue,
    db: Session,
) -> user_goals_schema.UsersGoalProgress:
    """Calculate goal progress for a specific activity type.

    Args:
        goal: User goal object with goal details.
        date: Reference date in YYYY-MM-DD format.
        db: SQLAlchemy database session.
        first_day_of_week: User's configured first weekday.

    Returns:
        UsersGoalProgress object with progress details.

    Raises:
        InvalidInputError: If the date or interval is malformed.
    """
    try:
        start_date, end_date = user_goals_utils.get_start_end_date_by_interval(
            goal.interval,
            date,
            first_day_of_week,
        )

        # Get activity types based on goal.activity_type
        activity_types = _ACTIVITY_TYPE_MAP.get(goal.activity_type, _DEFAULT_ACTIVITY_TYPES)

        # Fetch all activities in a single query (exclude hidden to avoid
        # counting duplicate imports from multiple sources)
        activities = activity_integration.list_user_activities_in_timeframe_by_types(
            goal.user_id,
            activity_types,
            start_date,
            end_date,
            db,
            exclude_hidden=True,
        )

        # Calculate totals based on goal type
        percentage_completed: float = 0
        total_calories = 0
        total_activities_number = 0
        total_distance = 0
        total_elevation = 0
        total_duration: float = 0

        if activities:
            if goal.goal_type == user_goals_schema.GoalType.CALORIES:
                total_calories = sum(activity.calories or 0 for activity in activities)
                if goal.goal_calories and goal.goal_calories > 0:
                    percentage_completed = (total_calories / goal.goal_calories) * 100
            elif goal.goal_type == user_goals_schema.GoalType.DISTANCE:
                total_distance = sum(activity.distance or 0 for activity in activities)
                if goal.goal_distance and goal.goal_distance > 0:
                    percentage_completed = (total_distance / goal.goal_distance) * 100
            elif goal.goal_type == user_goals_schema.GoalType.ELEVATION:
                total_elevation = sum(activity.elevation_gain or 0 for activity in activities)
                if goal.goal_elevation and goal.goal_elevation > 0:
                    percentage_completed = (total_elevation / goal.goal_elevation) * 100
            elif goal.goal_type == user_goals_schema.GoalType.DURATION:
                total_duration = sum(activity.total_elapsed_time or 0 for activity in activities)
                if goal.goal_duration and goal.goal_duration > 0:
                    percentage_completed = (total_duration / goal.goal_duration) * 100
            elif goal.goal_type == user_goals_schema.GoalType.ACTIVITIES:
                total_activities_number = len(activities)
                if goal.goal_activities_number and goal.goal_activities_number > 0:
                    percentage_completed = (total_activities_number / goal.goal_activities_number) * 100

        if percentage_completed > 100:
            percentage_completed = 100

        # Create and return the progress object
        return user_goals_schema.UsersGoalProgress(
            goal_id=goal.id,
            interval=goal.interval,
            activity_type=goal.activity_type,
            goal_type=goal.goal_type,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            percentage_completed=round(percentage_completed),
            total_calories=total_calories,
            total_activities_number=total_activities_number,
            total_distance=round(total_distance),
            total_elevation=round(total_elevation),
            total_duration=round(total_duration),
            goal_calories=goal.goal_calories,
            goal_activities_number=goal.goal_activities_number,
            goal_distance=goal.goal_distance,
            goal_elevation=goal.goal_elevation,
            goal_duration=goal.goal_duration,
        )
    except (ValueError, TypeError) as err:
        logger.error(
            "Invalid data while calculating goal progress", exc_info=err, extra=core_logger.context(goal_id=goal.id)
        )
        raise core_exceptions.InvalidInputError("Invalid data provided") from err


def get_goals_progress(user_id: int, db: Session) -> list[user_goals_schema.UsersGoalProgress] | None:
    """Calculate goal progress for a user as of their own calendar day.

    Args:
        user_id: The user whose goals to evaluate.
        db: Database session.

    Returns:
        The progress of each goal, or None if the user has no goals.

    Raises:
        NotFoundError: If the user does not exist.
    """
    user = users_integration.get_user(user_id, db)
    if user is None:
        raise core_exceptions.NotFoundError("User not found")

    today = core_timezone.today_in(users_integration.timezone_or_default(user.timezone))
    return calculate_user_goals(user_id, today.strftime("%Y-%m-%d"), user.first_day_of_week, db)
