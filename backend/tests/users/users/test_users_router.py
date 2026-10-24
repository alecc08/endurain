"""Tests for the users management router endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.database as core_database
import core.dependencies as core_dependencies
import core.exceptions as core_exceptions
import modules.auth.dependencies as auth_dependencies
import modules.auth.identity_service as auth_identity_service
import modules.users.users.schema as users_schema

_SERVICE = "modules.users.users.router.users_service"
_PHOTO = "modules.users.users.router.users_photo_service"


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def identity_service():
    return MagicMock()


@pytest.fixture
def client(mock_db, identity_service):
    from modules.users.users.router import router

    app = FastAPI()
    app.include_router(router, prefix="/users")
    core_exceptions.register_exception_handlers(app)
    app.dependency_overrides[auth_dependencies.check_scopes] = lambda: None
    app.dependency_overrides[core_database.get_db] = lambda: mock_db
    app.dependency_overrides[core_dependencies.get_storage] = lambda: MagicMock()
    app.dependency_overrides[auth_identity_service.get_identity_service] = lambda: identity_service
    app.dependency_overrides[core_dependencies.validate_pagination_values_on_query] = lambda: None
    return TestClient(app)


def _user(user_id: int, **overrides) -> users_schema.UsersRead:
    fields = {
        "id": user_id,
        "name": f"User {user_id}",
        "username": f"user{user_id}",
        "email": f"user{user_id}@example.com",
        "active": True,
        "access_type": "regular",
    }
    fields.update(overrides)
    return users_schema.UsersRead(**fields)


class TestReadUsers:
    @patch(f"{_SERVICE}.list_users")
    def test_list_passes_the_query_through(self, mock_list, client, mock_db, identity_service):
        mock_list.return_value = users_schema.UsersListResponse(
            total=1, num_records=10, page_number=1, records=[_user(1, name="Alice")]
        )

        response = client.get("/users?page_number=1&num_records=10&show_external_auth=false")

        assert response.status_code == 200
        assert response.json()["records"][0]["name"] == "Alice"
        mock_list.assert_called_once()
        assert mock_list.call_args.args == (identity_service, mock_db)
        assert mock_list.call_args.kwargs["page_number"] == 1
        assert mock_list.call_args.kwargs["show_external_auth"] is False

    @patch(f"{_SERVICE}.search_users_by_username")
    def test_contains_username(self, mock_search, client):
        mock_search.return_value = [_user(1, username="testuser1"), _user(2, username="testuser2")]

        response = client.get("/users/username/contains/test")

        assert response.status_code == 200
        assert [u["username"] for u in response.json()] == ["testuser1", "testuser2"]

    @patch(f"{_SERVICE}.get_user_by_username")
    def test_exact_username_not_found_is_null(self, mock_get, client):
        mock_get.return_value = None

        response = client.get("/users/username/nonexistent")

        assert response.status_code == 200
        assert response.json() is None

    @patch(f"{_SERVICE}.get_user_by_email")
    def test_email_found(self, mock_get, client):
        mock_get.return_value = _user(1, email="test@example.com")

        response = client.get("/users/email/test@example.com")

        assert response.json()["email"] == "test@example.com"

    @patch(f"{_SERVICE}.get_user")
    def test_id_found(self, mock_get, client):
        mock_get.return_value = _user(42, name="ID User")

        response = client.get("/users/id/42")

        assert response.status_code == 200
        assert response.json()["id"] == 42

    def test_id_must_be_positive(self, client):
        assert client.get("/users/id/0").status_code == 422


class TestCreateUser:
    @patch(f"{_SERVICE}.create_user")
    def test_creates_through_the_service(self, mock_create, client, identity_service, mock_db):
        mock_create.return_value = _user(1, name="New User", username="newuser", email="new@example.com")

        response = client.post(
            "/users",
            json={
                "name": "New User",
                "username": "newuser",
                "email": "new@example.com",
                "active": True,
                "access_type": "regular",
                "password": "testpass123",
            },
        )

        assert response.status_code == 201
        assert response.json()["username"] == "newuser"
        assert mock_create.call_args.args[1:] == (identity_service, mock_db)

    @patch(f"{_SERVICE}.create_user")
    def test_duplicate_is_a_conflict(self, mock_create, client):
        mock_create.side_effect = core_exceptions.ConflictError("Duplicate entry error")

        response = client.post(
            "/users",
            json={
                "name": "New User",
                "username": "newuser",
                "email": "new@example.com",
                "active": True,
                "access_type": "regular",
                "password": "testpass123",
            },
        )

        assert response.status_code == 409


class TestUploadUserImage:
    @patch(f"{_SERVICE}.get_user")
    @patch(f"{_PHOTO}.upload_photo")
    def test_returns_the_resolved_photo_url(self, mock_upload, mock_get, client):
        mock_upload.return_value = "1.jpg"
        mock_get.return_value = _user(1, photo_path="/users/1/photo?t=x")

        response = client.post("/users/1/image", files={"file": ("avatar.jpg", b"fake-image-data", "image/jpeg")})

        assert response.status_code == 201
        assert response.json() == "/users/1/photo?t=x"
        mock_upload.assert_called_once()


class TestEditUser:
    @patch(f"{_SERVICE}.edit_user")
    def test_returns_the_edited_user(self, mock_edit, client, identity_service, mock_db):
        mock_edit.return_value = _user(1, name="Updated User", external_auth_count=2)

        response = client.put(
            "/users/1",
            json={
                "id": 1,
                "name": "Updated User",
                "username": "updated",
                "email": "updated@example.com",
                "active": True,
                "access_type": "regular",
            },
        )

        assert response.status_code == 200
        assert response.json()["external_auth_count"] == 2
        assert mock_edit.call_args.args[0] == 1
        assert mock_edit.call_args.args[2:] == (identity_service, mock_db)


class TestApproveUser:
    @patch(f"{_SERVICE}.approve_user")
    def test_approves_then_sends_the_notice(self, mock_approve, client, identity_service, mock_db):
        response = client.put("/users/1/approve")

        assert response.status_code == 200
        assert response.json() == {"message": "User ID 1 approved successfully."}
        mock_approve.assert_called_once_with(1, mock_db)
        identity_service.request_sign_up_approved_email.assert_called_once_with(1)

    @patch(f"{_SERVICE}.approve_user")
    def test_unverified_email_sends_no_notice(self, mock_approve, client, identity_service):
        mock_approve.side_effect = core_exceptions.InvalidInputError("User email is not verified")

        response = client.put("/users/1/approve")

        assert response.status_code == 400
        identity_service.request_sign_up_approved_email.assert_not_called()


class TestEditUserPassword:
    def test_success(self, client, identity_service):
        response = client.put("/users/1/password", json={"password": "newpassword123"})

        assert response.status_code == 200
        assert response.json() == {"message": "User ID 1 password updated successfully"}
        identity_service.change_managed_user_password.assert_called_once_with(1, "newpassword123")


class TestDeleteUserPhoto:
    @patch(f"{_PHOTO}.delete_photo")
    def test_success(self, mock_delete, client, mock_db):
        response = client.delete("/users/1/photo")

        assert response.status_code == 204
        assert mock_delete.call_args.args[0] == 1
        assert mock_delete.call_args.args[2] == mock_db


class TestDeleteUser:
    @patch(f"{_SERVICE}.delete_user")
    def test_success(self, mock_delete, client, mock_db):
        response = client.delete("/users/1")

        assert response.status_code == 204
        assert mock_delete.call_args.args[0] == 1
        assert mock_delete.call_args.args[2] == mock_db

    @patch(f"{_SERVICE}.delete_user")
    def test_unknown_user_is_not_found(self, mock_delete, client):
        mock_delete.side_effect = core_exceptions.NotFoundError("User not found")

        assert client.delete("/users/1").status_code == 404
