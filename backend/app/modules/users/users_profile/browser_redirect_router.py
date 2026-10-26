"""Browser redirect router for OAuth identity provider linking.

This module handles browser-based OAuth flows for linking
external identity providers to user accounts using one-time
link tokens.

Key Features:
- One-time link token validation
- OAuth state management
- Security checks (IP validation, token expiry)
- Browser redirect handling
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse

import core.dependencies as core_dependencies
import modules.auth.identity_service as auth_identity_service

# Define the API router
router = APIRouter()


@router.get(
    "/idp/{idp_id}/link",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    response_class=RedirectResponse,
)
def link_identity_provider(
    idp_id: core_dependencies.PositiveId,
    link_token: Annotated[str, Query(alias="link_token")],
    request: Request,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    redirect: Annotated[
        str | None,
        Query(
            description="Frontend return path after linking (relative path or a configured custom scheme)",
        ),
    ] = None,
) -> RedirectResponse:
    """Initiate linking an identity provider using a one-time link token.

    This endpoint validates the one-time link token and initiates the OAuth flow
    to link an external identity provider (IdP) to the user's account. The user
    will be redirected to the IdP's authorization page.

    Security:
        - Uses one-time, short-lived (60s) link tokens instead of access tokens
        - Validates token expiry and single-use constraint
        - Optional IP address validation

    Args:
        idp_id (int): The ID of the identity provider to link.
        link_token (str): One-time link token from query parameter.
        request (Request): The FastAPI request object containing request context.
        identity_service: Identity service dependency.
        redirect: Optional frontend return path after linking.

    Returns:
        RedirectResponse: A redirect to the identity provider's authorization URL
            with HTTP 307 status code.

    """
    authorization_url = identity_service.start_browser_idp_link(link_token, idp_id, redirect, request)

    return RedirectResponse(
        url=authorization_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
        },
    )
