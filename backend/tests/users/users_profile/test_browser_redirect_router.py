"""Tests for profile browser redirect router."""

from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.config as core_config
import modules.auth.identity_service as auth_identity_service
import modules.users.users_profile.browser_redirect_router as profile_browser_redirect_router


class TestLinkIdentityProvider:
    """Test suite for link_identity_provider endpoint."""

    endpoint = "/api/v1/profile/idp/1/link?link_token=test-token"

    def _make_app(self):
        app = FastAPI()
        app.include_router(
            profile_browser_redirect_router.router,
            prefix=core_config.ROOT_PATH + "/profile",
        )
        mock_identity_service = MagicMock()
        app.dependency_overrides[auth_identity_service.get_identity_service] = lambda: mock_identity_service
        return app, mock_identity_service

    def test_redirects_to_the_authorization_url(self):
        app, mock_identity_service = self._make_app()
        mock_identity_service.start_browser_idp_link.return_value = "https://idp.example.com/auth"

        response = TestClient(app).get(self.endpoint, follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "https://idp.example.com/auth"
        assert "no-store" in response.headers["cache-control"]

    def test_passes_the_token_provider_and_return_path_through(self):
        app, mock_identity_service = self._make_app()
        mock_identity_service.start_browser_idp_link.return_value = "https://idp.example.com/auth"

        TestClient(app).get(self.endpoint + "&redirect=/settings/security", follow_redirects=False)

        args = mock_identity_service.start_browser_idp_link.call_args.args
        assert args[:3] == ("test-token", 1, "/settings/security")

    def test_an_auth_refusal_is_returned_as_is(self):
        app, mock_identity_service = self._make_app()
        mock_identity_service.start_browser_idp_link.side_effect = HTTPException(
            status_code=401, detail="Invalid or expired link token"
        )

        assert TestClient(app).get(self.endpoint).status_code == 401

    def test_the_provider_id_must_be_positive(self):
        app, _ = self._make_app()

        response = TestClient(app).get("/api/v1/profile/idp/0/link?link_token=test-token")

        assert response.status_code == 422
