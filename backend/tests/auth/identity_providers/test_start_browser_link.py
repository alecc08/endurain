"""Tests for the browser identity-provider link flow in the identity-provider utils."""

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import modules.auth.identity_providers.utils as idp_utils

_MODULE = "modules.auth.identity_providers.utils"


def _run(claim=None, *, redirect=None, idp="default", future="default"):
    claim = claim or MagicMock(return_value=1)
    request = MagicMock()
    if idp == "default":
        idp = MagicMock(enabled=True, name="TestIdP")
    if future == "default":
        future = Future()
        future.set_result("https://idp.example.com/auth")
    with (
        patch(f"{_MODULE}.core_network.get_ip_address", return_value="10.0.0.1"),
        patch(f"{_MODULE}.idp_service") as service,
        patch(f"{_MODULE}.oauth_state_utils.create_state_id_and_nonce", return_value=("state-id", "nonce")),
        patch(f"{_MODULE}.core_async_bridge.dispatch", return_value=future) as dispatch,
    ):
        service.get_identity_provider.return_value = idp
        url = idp_utils.start_browser_link("test-token", 1, redirect, request, claim, MagicMock())
    return url, claim, service, dispatch


class TestStartBrowserLink:
    def test_returns_the_authorization_url(self):
        url, claim, service, _ = _run()

        assert url == "https://idp.example.com/auth"
        claim.assert_called_once_with(link_token="test-token", idp_id=1, client_ip="10.0.0.1")
        assert service.create_link_oauth_state.call_args.kwargs["user_id"] == 1

    def test_stores_the_return_path_and_marks_a_web_client(self):
        _, _, service, _ = _run(redirect="/settings/security")

        kwargs = service.create_link_oauth_state.call_args.kwargs
        assert kwargs["redirect_path"] == "/settings/security"
        assert kwargs["client_type"] == "web"

    def test_a_bad_redirect_is_rejected_before_the_token_is_claimed(self):
        claim = MagicMock(return_value=1)

        with pytest.raises(HTTPException) as exc:
            _run(claim, redirect="https://evil.example.com")

        assert exc.value.status_code == 400
        claim.assert_not_called()

    def test_a_rejected_token_stops_the_flow(self):
        claim = MagicMock(side_effect=HTTPException(status_code=401, detail="Invalid or expired link token"))

        with pytest.raises(HTTPException) as exc:
            _run(claim)

        assert exc.value.status_code == 401

    def test_an_unknown_provider_is_not_found(self):
        with pytest.raises(HTTPException) as exc:
            _run(idp=None)

        assert exc.value.status_code == 404

    def test_a_disabled_provider_is_not_found(self):
        with pytest.raises(HTTPException) as exc:
            _run(idp=MagicMock(enabled=False))

        assert exc.value.status_code == 404

    def test_no_main_loop_fails_the_flow(self):
        with pytest.raises(HTTPException) as exc:
            _run(future=None)

        assert exc.value.status_code == 500
