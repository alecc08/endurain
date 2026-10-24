"""Profile photo storage for users.

The photo itself lives in the platform ``StorageProvider``; the user row holds only its key.
"""

import os

import jasil.providers as platform_providers
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.file_uploads as core_file_uploads
import modules.users.users.constants as users_constants
import modules.users.users.crud as users_crud


def delete_photo_files(user_id: int, storage: platform_providers.StorageProvider) -> None:
    """Delete a user's stored photo blobs.

    Args:
        user_id: ID of the user whose photo files to delete.
        storage: The platform storage provider.
    """
    for key in storage.list_keys(users_constants.USER_IMAGE_STORAGE_AREA, f"{user_id}."):
        storage.delete(users_constants.USER_IMAGE_STORAGE_AREA, key)


def delete_photo(user_id: int, storage: platform_providers.StorageProvider, db: Session) -> None:
    """Clear a user's photo reference, commit, then delete the stored blobs.

    The reference is committed first, so a failure never leaves a row pointing at a blob that
    is already gone.

    Args:
        user_id: ID of the user whose photo to delete.
        storage: The platform storage provider.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    users_crud.update_user(user_id, {"photo_path": None}, db)
    db.commit()

    delete_photo_files(user_id, storage)


async def upload_photo(
    user_id: int,
    file: UploadFile,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> str:
    """Validate and store a user's photo, then record its key and commit.

    Args:
        user_id: ID of the user whose photo is being saved.
        file: The uploaded image.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The storage key of the saved photo.

    Raises:
        NotFoundError: If the user does not exist.
        InvalidInputError: If the upload has no filename.
        UnsupportedMediaTypeError: If the extension is not an allowed image type.
    """
    # A blocking read, so it runs off the event loop.
    if await run_in_threadpool(users_crud.get_user_by_id, user_id, db) is None:
        raise core_exceptions.NotFoundError("User not found")

    if not file.filename:
        raise core_exceptions.InvalidInputError("Filename is required")

    # Defense-in-depth allow-list on the user-supplied extension. The upload reader still
    # validates the magic number, so a mismatched signature is rejected even if this passes.
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in users_constants.ALLOWED_USER_IMAGE_EXTENSIONS:
        raise core_exceptions.UnsupportedMediaTypeError("Unsupported user image file type")

    key = f"{user_id}{file_extension}"
    data = await core_file_uploads.read_validated_upload(file, kind=core_file_uploads.UploadKind.IMAGE)
    storage.save(users_constants.USER_IMAGE_STORAGE_AREA, key, data, file.content_type)

    await run_in_threadpool(_record_photo_key, user_id, key, db)
    return key


def _record_photo_key(user_id: int, key: str, db: Session) -> None:
    """Record a user's photo key and commit.

    Args:
        user_id: ID of the user.
        key: The storage key of the saved photo.
        db: Database session.
    """
    users_crud.update_user(user_id, {"photo_path": key}, db)
    db.commit()
