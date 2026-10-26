"""Public API router for activity exercise titles."""

from fastapi import APIRouter, Request

import core.dependencies as core_dependencies
import core.rate_limit as core_rate_limit
import modules.activities.activity_exercise_titles.schema as activity_exercise_titles_schema
import modules.activities.activity_exercise_titles.service as activity_exercise_titles_service

router = APIRouter()


@router.get(
    "/all",
    response_model=list[activity_exercise_titles_schema.ActivityExerciseTitlesRead],
)
@core_rate_limit.limiter.limit(core_rate_limit.PUBLIC_READ)
def list_public_activity_exercise_titles(
    request: Request,
    db: core_dependencies.DbSession,
) -> list[activity_exercise_titles_schema.ActivityExerciseTitlesRead]:
    """Return all activity exercise titles via the public endpoint."""
    return activity_exercise_titles_service.list_public_activity_exercise_titles(db)
