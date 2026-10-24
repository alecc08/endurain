"""Tests for users.users_goals.service module."""

from unittest.mock import patch

import modules.users.users_goals.schema as user_goals_schema
import modules.users.users_goals.service as user_goals_service


@patch("modules.users.users_goals.service.user_goals_crud")
class TestUserGoalsService:
    def test_create_commits(self, mock_crud, mock_db):
        goal = user_goals_schema.UsersGoalCreate(
            interval="weekly", activity_type="run", goal_type="calories", goal_calories=5000
        )

        result = user_goals_service.create_goal(1, goal, mock_db)

        assert result == mock_crud.create_user_goal.return_value
        mock_db.commit.assert_called_once()

    def test_update_commits(self, mock_crud, mock_db):
        goal = user_goals_schema.UsersGoalUpdate(
            interval="weekly", activity_type="run", goal_type="calories", goal_calories=5000
        )

        result = user_goals_service.update_goal(1, 7, goal, mock_db, if_match="*")

        assert result == mock_crud.update_user_goal.return_value
        mock_crud.update_user_goal.assert_called_once_with(1, 7, goal, mock_db, if_match="*")
        mock_db.commit.assert_called_once()

    def test_delete_commits(self, mock_crud, mock_db):
        user_goals_service.delete_goal(1, 5, mock_db)

        mock_crud.delete_user_goal.assert_called_once_with(1, 5, mock_db)
        mock_db.commit.assert_called_once()
