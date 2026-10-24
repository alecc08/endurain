"""User management router for authenticated operations."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Security, UploadFile, status

import core.dependencies as core_dependencies
import core.rate_limit as core_rate_limit
import modules.auth.dependencies as auth_dependencies
import modules.auth.identity_providers.links.schema as auth_identity_links_schema
import modules.auth.identity_service as auth_identity_service
import modules.users.users.dependencies as users_dependencies
import modules.users.users.photo_service as users_photo_service
import modules.users.users.schema as users_schema
import modules.users.users.service as users_service

# Define the API router
router = APIRouter()


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UsersListResponse,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read_all"])],
)
def read_users_all_pagination(
    _validate_pagination_values_on_query: Annotated[
        Callable, Depends(core_dependencies.validate_pagination_values_on_query)
    ],
    db: core_dependencies.DbSession,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    page_number: Annotated[
        int | None,
        Query(description="Pagination page number"),
    ] = None,
    num_records: Annotated[
        int | None,
        Query(description="Number of records per page"),
    ] = None,
    show_inactive: Annotated[
        bool | None,
        Query(description="Filter by inactive status"),
    ] = None,
    show_email_unverified: Annotated[
        bool | None,
        Query(description="Filter by email verification status"),
    ] = None,
    show_pending_approval: Annotated[
        bool | None,
        Query(description="Filter by pending approval status"),
    ] = None,
    show_external_auth: Annotated[
        bool | None,
        Query(description="Filter by external authentication status"),
    ] = None,
    show_local_auth: Annotated[
        bool | None,
        Query(description="Filter by local authentication status"),
    ] = None,
    username: Annotated[
        str | None,
        Query(description="Keep only users whose username contains this text"),
    ] = None,
) -> users_schema.UsersListResponse:
    """Retrieve paginated list of all users.

    Args:
        _validate_pagination_values: Pagination validation.
        db: Database session dependency.
        identity_service: Identity service dependency.
        page_number: Optional page number to retrieve.
        num_records: Optional number of records per page.
        show_inactive: Optional filter by inactive status.
        show_email_unverified: Optional filter by email verification status.
        show_pending_approval: Optional filter by pending approval status.
        show_external_auth: Optional filter by external authentication status.
        show_local_auth: Optional filter by local authentication status.
        username: Optional text the username must contain.

    Returns:
        Paginated list of users with total count.
    """
    return users_service.list_users(
        identity_service,
        db,
        page_number=page_number,
        num_records=num_records,
        show_inactive=show_inactive,
        show_email_unverified=show_email_unverified,
        show_pending_approval=show_pending_approval,
        show_external_auth=show_external_auth,
        show_local_auth=show_local_auth,
        username=username,
    )


@router.get(
    "/username/contains/{username}",
    status_code=status.HTTP_200_OK,
    response_model=list[users_schema.UserPublicRead],
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read"])],
)
def read_users_contain_username(
    username: users_dependencies.Username,
    db: core_dependencies.DbSession,
) -> list[users_schema.UserPublicRead]:
    """Search active users by partial username match.

    Args:
        username: Partial username to search for.
        db: Database session dependency.

    Returns:
        The matching users' public projections.
    """
    return users_service.search_public_users(username, db)


@router.get(
    "/username/{username}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UsersRead | None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read_all"])],
)
def read_users_username(
    username: users_dependencies.Username,
    db: core_dependencies.DbSession,
) -> users_schema.UsersRead | None:
    """Get user by exact username.

    Args:
        username: Exact username to search for.
        db: Database session dependency.

    Returns:
        User if found, None otherwise.
    """
    return users_service.get_user_by_username(username, db)


@router.get(
    "/email/{email}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UsersRead | None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read_all"])],
)
def read_users_email(
    email: users_dependencies.Email,
    db: core_dependencies.DbSession,
) -> users_schema.UsersRead | None:
    """Get user by email address.

    Args:
        email: Email address to search for.
        db: Database session dependency.

    Returns:
        User if found, None otherwise.
    """
    return users_service.get_user_by_email(email, db)


@router.get(
    "/id/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UserPublicRead | None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read"])],
)
def read_users_id(
    user_id: core_dependencies.PositiveId,
    db: core_dependencies.DbSession,
) -> users_schema.UserPublicRead | None:
    """Get a user's public projection by ID.

    Args:
        user_id: User ID to retrieve.
        db: Database session dependency.

    Returns:
        The public projection if the user exists, None otherwise.
    """
    return users_service.get_public_profile(user_id, db)


@router.get(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UsersRead | None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read_all"])],
)
def read_users_full(
    user_id: core_dependencies.PositiveId,
    db: core_dependencies.DbSession,
) -> users_schema.UsersRead | None:
    """Get a user's full record by ID (admin operation).

    Args:
        user_id: User ID to retrieve.
        db: Database session dependency.

    Returns:
        The full record if the user exists, None otherwise.
    """
    return users_service.get_user(user_id, db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=users_schema.UsersRead)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def create_user(
    request: Request,
    user: users_schema.UsersCreate,
    _check_scope: Annotated[Callable, Security(auth_dependencies.check_scopes, scopes=["users:write"])],
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    db: core_dependencies.DbSession,
) -> users_schema.UsersRead:
    """Create a new user (admin operation).

    Args:
        request: The incoming request, read by the rate limiter.
        user: User creation data.
        _check_scope: Authorization check.
        identity_service: Identity service dependency.
        db: Database session dependency.

    Returns:
        Created user data.
    """
    return users_service.create_user(user, identity_service, db)


@router.post(
    "/{user_id}/image",
    status_code=status.HTTP_201_CREATED,
    response_model=str | None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.UPLOAD)
def upload_user_image(
    request: Request,
    user_id: core_dependencies.PositiveId,
    file: UploadFile,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> str | None:
    """Upload user profile image.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user to upload image for.
        file: Uploaded image file.
        storage: The platform storage provider.
        db: Database session dependency.

    Returns:
        Path to uploaded image.
    """
    users_photo_service.upload_photo(user_id, file, storage, db)
    return users_service.require_user(user_id, db).photo_path


@router.put(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.UsersRead,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def edit_user(
    request: Request,
    user_id: core_dependencies.PositiveId,
    user_attributtes: users_schema.UsersRead,
    token_user_id: auth_dependencies.CurrentUserId,
    db: core_dependencies.DbSession,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> users_schema.UsersRead:
    """Update user information.

    A change of email, access type or active flag signs the edited user out everywhere.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user to update.
        user_attributtes: User data to update.
        token_user_id: ID of the administrator making the edit.
        db: Database session dependency.
        identity_service: Identity service dependency.

    Returns:
        Updated user data.
    """
    return users_service.edit_user(user_id, user_attributtes, token_user_id, identity_service, db)


@router.put(
    "/{user_id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=users_schema.MessageResponse,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def approve_user(
    request: Request,
    user_id: core_dependencies.PositiveId,
    db: core_dependencies.DbSession,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> users_schema.MessageResponse:
    """Approve pending user account.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user to approve.
        db: Database session dependency.
        identity_service: Identity service dependency.

    Returns:
        Success message.
    """
    users_service.approve_user(user_id, db)
    identity_service.request_sign_up_approved_email(user_id)

    # Return success message
    return users_schema.MessageResponse(message=f"User ID {user_id} approved successfully.")


@router.post("/{user_id}/password/change", status_code=status.HTTP_200_OK, response_model=users_schema.MessageResponse)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def edit_user_password(
    request: Request,
    user_id: core_dependencies.PositiveId,
    user_attributes: users_schema.UsersAdminEditPassword,
    _check_scope: Annotated[Callable, Security(auth_dependencies.check_scopes, scopes=["users:write"])],
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> users_schema.MessageResponse:
    """Update user password.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user to update password for.
        user_attributes: New password data.
        _check_scope: Authorization check.
        identity_service: Identity service dependency.

    Returns:
        Success message.
    """
    identity_service.change_managed_user_password(
        user_id,
        user_attributes.password,
    )

    # Return success message
    return users_schema.MessageResponse(message=f"User ID {user_id} password updated successfully")


@router.delete(
    "/{user_id}/photo",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_user_photo(
    request: Request,
    user_id: core_dependencies.PositiveId,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> None:
    """Delete user profile photo.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user whose photo to delete.
        storage: The platform storage provider.
        db: Database session dependency.

    Returns:
        None
    """
    users_photo_service.delete_photo(user_id, storage, db)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.SENSITIVE)
def delete_user(
    request: Request,
    user_id: core_dependencies.PositiveId,
    storage: core_dependencies.Storage,
    db: core_dependencies.DbSession,
) -> None:
    """Delete user account.

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of user to delete.
        storage: The platform storage provider.
        db: Database session dependency.

    Returns:
        None
    """
    users_service.delete_user(user_id, storage, db)


@router.get(
    "/{user_id}/identity-providers",
    status_code=status.HTTP_200_OK,
    response_model=list[auth_identity_links_schema.UsersIdentityProviderResponse],
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:read"])],
)
def get_user_identity_providers(
    user_id: core_dependencies.PositiveId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> list[auth_identity_links_schema.UsersIdentityProviderResponse]:
    """List the identity provider links of a specific user (admin).

    Args:
        user_id: ID of the user whose identity provider links to retrieve.
        identity_service: Identity service dependency.

    Returns:
        The user's enriched identity provider links (empty list if none).
    """
    return identity_service.get_user_identity_provider_links(user_id)


@router.delete(
    "/{user_id}/identity-providers/{idp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Security(auth_dependencies.check_scopes, scopes=["users:write"])],
)
@core_rate_limit.limiter.limit(core_rate_limit.WRITE)
def delete_user_identity_provider(
    request: Request,
    user_id: core_dependencies.PositiveId,
    idp_id: core_dependencies.PositiveId,
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
) -> None:
    """Unlink an identity provider from a specific user (admin).

    Args:
        request: The incoming request, read by the rate limiter.
        user_id: ID of the user to unlink the identity provider from.
        idp_id: ID of the identity provider to unlink.
        identity_service: Identity service dependency.

    Returns:
        None
    """
    identity_service.admin_delete_identity_provider_link(user_id, idp_id)
