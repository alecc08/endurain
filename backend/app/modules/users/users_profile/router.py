"""Profile API endpoints for user management and operations.

This module provides FastAPI endpoints for:
- User profile retrieval and updates
- Password and privacy settings management
- MFA (Multi-Factor Authentication) operations
- Profile photo upload and deletion
- Session management
- Identity provider linking and unlinking
- Profile data export and import
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

import core.dependencies as core_dependencies
import core.file_uploads as core_file_uploads
import core.rate_limit as core_rate_limit
import modules.auth.dependencies as auth_dependencies
import modules.auth.identity_providers.link_tokens.schema as idp_link_token_schema
import modules.auth.identity_providers.links.schema as auth_identity_links_schema
import modules.auth.identity_service as auth_identity_service
import modules.auth.mfa.backup_codes.schema as mfa_backup_codes_schema
import modules.auth.mfa.schema as mfa_schema
import modules.auth.sessions.schema as auth_sessions_schema
import modules.users.users.integration_service as users_integration
import modules.users.users.schema as users_schema
import modules.users.users_privacy_settings.schema as users_privacy_settings_schema
import modules.users.users_profile.dependencies as profile_dependencies
import modules.users.users_profile.import_job_service as profile_import_job_service
import modules.users.users_profile.schema as profile_schema
import modules.users.users_profile.service as profile_service

# Define the API router
router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK, response_model=users_schema.UsersMe)
def read_users_me(
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    db: core_dependencies.DbSession,
) -> users_schema.UsersMe:
    """Retrieve authenticated user profile with integrations.

    Args:
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        db: Database session.

    Returns:
        User object with integration and privacy settings.
    """
    return profile_service.get_profile(token_user_id, identity_service, db)


@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    response_model=list[auth_sessions_schema.UsersSessionsRead],
)
def read_sessions_me(
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> list[auth_sessions_schema.UsersSessionsRead]:
    """Retrieve all sessions for authenticated user.

    Args:
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.

    Returns:
        List of session objects for the user.
    """
    return identity_service.get_user_sessions(token_user_id)


@router.post(
    "/idp/{idp_id}/link/token",
    status_code=status.HTTP_201_CREATED,
    response_model=idp_link_token_schema.IdpLinkTokenResponse,
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def generate_link_token(
    idp_id: core_dependencies.PositiveId,
    link_request: idp_link_token_schema.IdpLinkTokenRequest,
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
) -> idp_link_token_schema.IdpLinkTokenResponse:
    """Generate a one-time token for linking an identity provider.

    This endpoint creates a short-lived (60 seconds), single-use token
    that can be used to securely initiate the OAuth flow for linking
    an identity provider to the authenticated user's account.

    Linking an identity provider is a sensitive operation that enables
    persistent authentication. Step-up verification is required: the
    caller MUST supply ``current_password``, and an MFA code when MFA
    is enabled on the account.

    This approach is more secure than passing access tokens in query
    parameters, as the link token:
    - Expires in 60 seconds
    - Can only be used once
    - Is scoped specifically for IdP linking
    - Limits exposure in server logs and browser history

    Args:
        idp_id (int): The ID of the identity provider to link.
        link_request (IdpLinkTokenRequest): Request with step-up credentials.
        request (Request): The FastAPI request object.
        token_user_id (int): The authenticated user's ID extracted from the access token.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.

    Returns:
        IdpLinkTokenResponse: Contains the one-time token and expiration time.

    Raises:
        HTTPException:
            - 401 UNAUTHORIZED: If step-up verification fails.
            - 404 NOT_FOUND: If the identity provider doesn't exist or is disabled.
            - 409 CONFLICT: If the identity provider is already linked.
            - 500 INTERNAL_SERVER_ERROR: If token generation fails.
    """
    return identity_service.generate_link_token(
        idp_id=idp_id,
        link_request=link_request,
        request=request,
        user_id=token_user_id,
        step_up_store=step_up_store,
    )


@router.post(
    "/image",
    status_code=status.HTTP_201_CREATED,
    response_model=str,
)
@core_rate_limit.limiter.limit(core_rate_limit.UPLOAD)
def upload_profile_image(
    request: Request,
    file: UploadFile,
    token_user_id: auth_dependencies.CurrentUserId,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> str:
    """Upload user profile image with security validation.

    Args:
        request: The incoming request, read by the rate limiter.
        file: Image file to upload.
        token_user_id: User ID from access token.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The storage key of the saved photo.
    """
    return users_integration.upload_user_photo(token_user_id, file, storage, db)


@router.put("", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def edit_user(
    request: Request,
    user_attributtes: users_schema.ProfileUpdate,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> dict:
    """Edit self-service profile fields for the authenticated user.

    Uses an explicit allow-list (:class:`users_schema.ProfileUpdate`)
    so administrative attributes such as ``access_type``,
    ``active``, ``mfa_enabled``, ``mfa_secret``, ``email_verified``,
    and ``pending_admin_approval`` cannot be modified through this
    endpoint, even if a malicious client submits them.

    Args:
        request: The incoming request, read by the rate limiter.
        user_attributtes: Allow-listed profile updates.
        token_user_id: User ID from access token.
        db: Database session.

    Returns:
        Success message with user ID.
    """
    profile_service.edit_profile(token_user_id, user_attributtes, db)

    return {"message": f"User ID {token_user_id} updated successfully"}


@router.put("/email", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def edit_profile_email(
    request: Request,
    email_change: users_schema.EmailChange,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
    db: core_dependencies.DbSession,
) -> dict:
    """Change the authenticated user's email after step-up verification.

    The address is where password resets go, so the caller must re-prove identity with the
    current password (and an MFA code when MFA is enabled). The new address starts unverified and
    a verification link is emailed to it.

    Args:
        request: The incoming request, read by the rate limiter.
        email_change: The new address with the step-up credentials.
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.
        db: Database session.

    Returns:
        Success message.
    """
    profile_service.change_email(token_user_id, email_change, identity_service, step_up_store, db)

    return {"message": f"User ID {token_user_id} email updated successfully"}


@router.put("/privacy", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def edit_profile_privacy_settings(
    request: Request,
    user_privacy_settings: users_privacy_settings_schema.UsersPrivacySettingsUpdate,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
) -> dict:
    """Edit privacy settings for authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        user_privacy_settings: New privacy settings.
        token_user_id: User ID from access token.
        db: Database session.

    Returns:
        Success message.
    """
    profile_service.edit_privacy_settings(token_user_id, user_privacy_settings, db)

    return {"message": f"User ID {token_user_id} privacy settings updated successfully"}


@router.put("/password", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def edit_profile_password(
    request: Request,
    user_attributtes: users_schema.UsersEditPassword,
    token_user_id: auth_dependencies.CurrentUserId,
    token_session_id: Annotated[
        str,
        Depends(auth_dependencies.get_sid_from_access_token),
    ],
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
) -> dict:
    """Update user password after step-up verification.

    Requires the caller to re-prove identity with the current
    password — and an MFA code when MFA is enabled — before the
    new password is accepted. This prevents a stolen access
    token alone from being parlayed into permanent account
    takeover.

    When ``revoke_other_sessions`` is set on the request, all of
    the user's other sessions are revoked after the change while
    the current session is preserved, so a password change can
    evict a suspected attacker without logging the caller out.

    Args:
        request: The incoming request, read by the rate limiter.
        user_attributtes: Schema with current password, new
            password, optional MFA code, and the optional
            ``revoke_other_sessions`` flag.
        token_user_id: ID of the user extracted from the access
            token.
        token_session_id: Session ID of the caller, preserved when
            other sessions are revoked.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.

    Returns:
        dict: A success message indicating the user's password
        was updated.

    Raises:
        HTTPException: 401 if step-up verification fails.
    """
    identity_service.change_own_password(
        user_id=token_user_id,
        current_password=user_attributtes.current_password,
        new_password=user_attributtes.password,
        mfa_code=user_attributtes.mfa_code,
        step_up_store=step_up_store,
        revoke_other_sessions=user_attributtes.revoke_other_sessions,
        current_session_id=token_session_id,
    )

    return {"message": f"User ID {token_user_id} password updated successfully"}


@router.put("/photo", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_profile_photo(
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> None:
    """Delete authenticated user's profile photo.

    Args:
        request: The incoming request, read by the rate limiter.
        token_user_id: User ID from access token.
        storage: The platform storage provider.
        db: Database session.
    """
    users_integration.delete_user_photo(token_user_id, storage, db)


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_profile_other_sessions(
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    token_session_id: Annotated[
        str,
        Depends(auth_dependencies.get_sid_from_access_token),
    ],
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> None:
    """Revoke all of the authenticated user's other sessions.

    Signs out every device except the caller's current session
    (identified from the access token), so a user can end all
    other sessions without logging themselves out. This is the
    standalone form of the password change's
    ``revoke_other_sessions`` option.

    Args:
        request: The incoming request, read by the rate limiter.
        token_user_id: User ID from access token.
        token_session_id: The caller's current session, preserved.
        identity_service: Identity service dependency.

    Returns:
        None.
    """
    identity_service.delete_other_user_sessions(token_user_id, token_session_id)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_profile_session(
    request: Request,
    session_id: profile_dependencies.SessionId,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> None:
    """Delete user session from database.

    Args:
        request: The incoming request, read by the rate limiter.
        session_id: Session identifier to delete.
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.

    Returns:
        None.
    """
    identity_service.delete_user_session(session_id, token_user_id)


# Import/export logic


@router.post(
    "/delete-account",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def delete_my_account(
    request: Request,
    response: Response,
    step_up: users_schema.StepUpVerification,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> None:
    """Delete the authenticated user's account and all of their data.

    Requires step-up verification: the current password, and an MFA code when MFA is enabled. The
    deletion is permanent and cannot be undone. Export the profile first to keep a copy. The browser's
    refresh-token cookie is cleared on the response.

    Args:
        request: The incoming request, read by the rate limiter.
        response: The response, which receives the cookie-deletion headers.
        step_up: Step-up verification payload.
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.
        storage: The platform storage provider.
        db: Database session.
    """
    profile_service.delete_account(token_user_id, step_up, identity_service, step_up_store, storage, db)
    identity_service.clear_session_cookies(response)


@router.get("/export", status_code=status.HTTP_200_OK, response_class=StreamingResponse)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def export_profile_data(
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> StreamingResponse:
    """Export all profile data as ZIP archive.

    Args:
        request: The incoming request, read by the rate limiter.
        token_user_id: User ID from access token.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        Streaming response with ZIP archive.
    """
    chunks, size = profile_service.export_profile(token_user_id, storage, db)
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=user_{token_user_id}_export.zip",
            "Content-Length": str(size),
        },
    )


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, response_model=profile_schema.ProfileImportStatus)
@core_rate_limit.limiter.limit(core_rate_limit.UPLOAD)
def import_profile_data(
    request: Request,
    file: UploadFile,
    token_user_id: auth_dependencies.CurrentUserId,
    import_states: profile_dependencies.ProfileImportStateStoreDep,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> profile_schema.ProfileImportStatus:
    """Queue a profile import from a ZIP archive.

    The archive is validated and staged, and a worker imports it; poll ``GET /profile/import`` for
    the outcome. The database part is all-or-nothing, so a failed import leaves nothing behind.

    Args:
        request: The incoming request, read by the rate limiter.
        file: ZIP file containing profile data.
        token_user_id: User ID from access token.
        import_states: Shared store of the import's state.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The queued import's state.
    """
    # Comprehensive security validation via the unified pipeline.
    zip_data = core_file_uploads.read_validated_upload_sync(file, kind=core_file_uploads.UploadKind.ZIP)

    state = profile_import_job_service.request_import(token_user_id, zip_data, import_states, storage, db)
    return profile_schema.ProfileImportStatus.model_validate(state)


@router.get("/import", status_code=status.HTTP_200_OK, response_model=profile_schema.ProfileImportStatus)
def read_profile_import_status(
    token_user_id: auth_dependencies.CurrentUserId,
    import_states: profile_dependencies.ProfileImportStateStoreDep,
) -> profile_schema.ProfileImportStatus:
    """Report where the authenticated user's profile import is.

    Args:
        token_user_id: User ID from access token.
        import_states: Shared store of the import's state.

    Returns:
        The import's state.
    """
    state = profile_import_job_service.get_import_status(token_user_id, import_states)
    return profile_schema.ProfileImportStatus.model_validate(state)


# MFA logic
@router.get(
    "/mfa/status",
    status_code=status.HTTP_200_OK,
    response_model=mfa_schema.MFAStatusResponse,
)
def get_mfa_status(
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> mfa_schema.MFAStatusResponse:
    """Return MFA enabled status for authenticated user.

    Args:
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.

    Returns:
        MFA status response with enabled flag.
    """
    return identity_service.get_mfa_status(token_user_id)


@router.get(
    "/mfa/backup-codes/status",
    status_code=status.HTTP_200_OK,
    response_model=mfa_backup_codes_schema.MFABackupCodeStatus,
)
def get_backup_code_status(
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> mfa_backup_codes_schema.MFABackupCodeStatus:
    """Retrieve MFA backup code status for authenticated user.

    Args:
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.

    Returns:
        Backup code status with counts and creation date.
    """
    return identity_service.get_backup_code_status(token_user_id)


@router.post(
    "/mfa/setup",
    status_code=status.HTTP_201_CREATED,
    response_model=mfa_schema.MFASetupResponse,
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def setup_mfa(
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    mfa_secret_store: Annotated[
        auth_dependencies.MFASecretStoreBackend,
        Depends(auth_dependencies.get_mfa_secret_store),
    ],
) -> mfa_schema.MFASetupResponse:
    """Initiate MFA setup for authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        mfa_secret_store: Temporary secret storage.

    Returns:
        MFA setup response with secret and QR code.
    """
    return identity_service.setup_mfa(
        user_id=token_user_id,
        mfa_secret_store=mfa_secret_store,
    )


@router.put("/mfa/enable", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def enable_mfa(
    request: Request,
    mfa_request: mfa_schema.MFASetupRequest,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
    mfa_secret_store: Annotated[
        auth_dependencies.MFASecretStoreBackend,
        Depends(auth_dependencies.get_mfa_secret_store),
    ],
) -> dict:
    """Enable MFA for authenticated user after step-up verification.

    A stolen access token alone must not be sufficient to enrol a
    new TOTP secret on a victim's account (which would lock the
    legitimate user out and hand the attacker the backup codes).
    The caller therefore has to re-prove identity with their
    current password before the binding is committed. The TOTP
    code in the request body is the fresh enrolment code from the
    user's authenticator app and is verified separately by
    :func:`modules.auth.mfa.service.enable_user_mfa` against the secret
    issued by ``POST /profile/mfa/setup``. SSO-only accounts may
    omit ``current_password`` (see
    :func:`modules.auth._internal.services.step_up_service.verify_step_up_credentials`).

    Args:
        request: The incoming request, read by the rate limiter.
        mfa_request: MFA setup request with TOTP code and (when the
            account has a local password) current password.
        token_user_id: User ID from access token.
        identity_service: Identity service instance for backup code
            generation and step-up verification.
        mfa_secret_store: Temporary secret storage.
        step_up_store: Step-up lockout store.

    Returns:
        Success message and the freshly issued backup codes.

    Raises:
        HTTPException: 400 if no setup is in progress or the TOTP
            code is invalid; 401 if step-up verification fails.
    """
    return identity_service.enable_mfa(
        request=mfa_request,
        user_id=token_user_id,
        step_up_store=step_up_store,
        mfa_secret_store=mfa_secret_store,
    )


@router.put("/mfa/disable", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def disable_mfa(
    request: Request,
    mfa_request: mfa_schema.MFADisableRequest,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
) -> dict:
    """Disable MFA for authenticated user after step-up verification.

    Disabling MFA materially weakens the account's security
    posture, so a valid access token alone is not sufficient: the
    caller must re-prove identity with both their current
    password and a fresh MFA code. The MFA code may be either a
    6-digit TOTP or an unused ``XXXX-XXXX`` backup code — the
    same set of factors accepted at login. Step-up verification
    is the single source of truth for the MFA check;
    :func:`modules.auth.mfa.service.disable_user_mfa` only clears state.

    Args:
        request: The incoming request, read by the rate limiter.
        mfa_request: MFA disable request with current password and
            MFA code.
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.

    Returns:
        Success message.

    Raises:
        HTTPException: 401 if the current password is wrong or
            the MFA code is invalid; 400 if MFA is not currently
            enabled.
    """
    return identity_service.disable_mfa(
        request=mfa_request,
        user_id=token_user_id,
        step_up_store=step_up_store,
    )


@router.post("/mfa/verify", status_code=status.HTTP_200_OK, response_model=dict)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def verify_mfa(
    request: Request,
    mfa_request: mfa_schema.MFARequest,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> dict:
    """Verify MFA code for authenticated user.

    Args:
        request: The incoming request, read by the rate limiter.
        mfa_request: MFA request with code to verify.
        token_user_id: User ID from access token.
        identity_service: Identity service instance for backup code verification.

    Returns:
        Success message.

    Raises:
        HTTPException: If MFA code is invalid.
    """
    return identity_service.verify_mfa(
        request=mfa_request,
        user_id=token_user_id,
    )


@router.post(
    "/mfa/backup-codes",
    status_code=status.HTTP_201_CREATED,
    response_model=mfa_backup_codes_schema.MFABackupCodesResponse,
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def generate_mfa_backup_codes(
    response: Response,
    request: Request,
    step_up: users_schema.StepUpVerification,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
) -> mfa_backup_codes_schema.MFABackupCodesResponse:
    """Generate new MFA backup codes for authenticated user.

    Requires step-up verification (current password + MFA code,
    when MFA is enabled). Issuing new backup codes invalidates
    the previous set, so an attacker holding only an access
    token must not be able to lock the legitimate user out of
    their second factor.

    Args:
        response: FastAPI response object.
        request: FastAPI request object for rate limiting.
        step_up: Step-up verification payload.
        token_user_id: User ID from access token.
        identity_service: Identity service for code generation.
        step_up_store: Step-up lockout store.

    Returns:
        Response with generated backup codes and timestamp.

    Raises:
        HTTPException: 401 if step-up verification fails, 404 if
            user not found, 400 if MFA is not enabled.
    """
    return identity_service.generate_backup_codes(
        step_up=step_up,
        user_id=token_user_id,
        step_up_store=step_up_store,
    )


# Identity Provider Management Endpoints
@router.get(
    "/idp",
    status_code=status.HTTP_200_OK,
    response_model=list[auth_identity_links_schema.UsersIdentityProviderResponse],
)
def get_my_identity_providers(
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> list[auth_identity_links_schema.UsersIdentityProviderResponse]:
    """Retrieve all identity provider links for the authenticated user.

    This endpoint fetches all external identity provider (IdP) connections associated
    with the current user's account. Each link includes connection metadata and enriched
    details about the identity provider (name, slug, icon, and provider type).

    Args:
        token_user_id (int): The authenticated user's ID extracted from the JWT access token.
            Injected automatically via dependency injection.
        identity_service: Identity service dependency.

    Returns:
        list[dict]: A list of dictionaries representing the user's IdP links. Each dictionary contains:
            - id (int): Unique identifier for the user-IdP link
            - user_id (int): ID of the user
            - idp_id (int): ID of the identity provider
            - idp_subject (str): User's unique identifier at the IdP
            - linked_at (datetime): Timestamp when the link was created
            - last_login (datetime): Timestamp of the last login via this IdP
            - idp_access_token_expires_at (datetime): Expiration time of the IdP access token
            - idp_refresh_token_updated_at (datetime): Last update time of the refresh token
            - idp_name (str): Display name of the identity provider (if available)
            - idp_slug (str): URL-safe identifier for the IdP (if available)
            - idp_icon (str): Icon/logo URL for the IdP (if available)
            - idp_provider_type (str): Type of provider (e.g., "oauth2", "oidc") (if available)

    Raises:
        HTTPException: May raise authentication/authorization errors via the dependency injection.
    """
    # Get enriched IdP links via the identity-service boundary
    return identity_service.get_user_identity_provider_links(token_user_id)


@router.post(
    "/idp/{idp_id}/unlink",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def delete_my_identity_provider(
    idp_id: core_dependencies.PositiveId,
    step_up: users_schema.StepUpVerification,
    request: Request,
    token_user_id: auth_dependencies.CurrentUserId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
) -> None:
    """Delete (unlink) an identity provider from the authenticated user's account.

    This endpoint allows users to remove the association between their
    account and a specific identity provider. It requires step-up
    verification (current password and MFA when enabled) and includes
    safety checks to prevent account lockout by ensuring users maintain
    at least one authentication method (either a password or another
    IdP link).

    Args:
        idp_id (int): The ID of the identity provider to unlink.
        step_up (StepUpVerification): Step-up verification payload.
        request (Request): The FastAPI request object.
        token_user_id (int): User ID extracted from the access token.
        identity_service: Identity service dependency.
        step_up_store: Step-up lockout store.

    Returns:
        None: Returns 204 No Content on successful deletion.

    Raises:
        HTTPException (401): If step-up verification fails.
        HTTPException (404): If the identity provider doesn't exist or
            is not linked to the user's account.
        HTTPException (400): If attempting to unlink the last authentication method
            without having a password set (prevents account lockout).
        HTTPException (500): If the deletion operation fails at the database level.

    Notes:
        - Enforces step-up verification before unlinking.
        - Prevents account lockout by ensuring users have at least one
          authentication method (password or remaining IdP link).
        - Logs the unlinking action for audit purposes.
        - Uses token-based authentication to ensure users can only
          unlink their own IdPs.
    """
    identity_service.delete_identity_provider_link(
        idp_id=idp_id,
        step_up=step_up,
        user_id=token_user_id,
        step_up_store=step_up_store,
    )
    return None
