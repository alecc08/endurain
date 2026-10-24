from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(mock_db):
    import core.database as core_db
    import modules.users.users.public_router as router

    app = FastAPI()
    app.include_router(router.router, prefix="/public/users")

    def _mock():
        return None

    app.dependency_overrides[core_db.get_db] = lambda: mock_db
    return app


class TestReadUsersById:
    @patch("modules.users.users.public_router.users_service.get_public_user")
    def test_success(self, mock_get, mock_db):
        from modules.users.users.schema import UsersRead

        client = TestClient(_build_app(mock_db))
        mock_get.return_value = UsersRead(
            id=1,
            name="Test User",
            username="testuser",
            email="test@example.com",
            active=True,
            access_type="regular",
        )

        response = client.get("/public/users/id/1")
        assert response.status_code == 200

    @patch("modules.users.users.public_router.users_service.get_public_user")
    def test_not_found(self, mock_get, mock_db):
        client = TestClient(_build_app(mock_db))
        mock_get.return_value = None

        response = client.get("/public/users/id/999")
        assert response.status_code == 200
        assert response.json() is None
