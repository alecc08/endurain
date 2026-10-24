"""Profile photo storage for users.

The photo itself lives in the platform ``StorageProvider``; the user row holds only its key.
"""

import os

import jasil.providers as platform_providers
from fastapi import UploadFile
from sqlalchemy.orm import Session

import core.exceptions as core_exceptions
import core.file_uploads as core_file_uploads
import core.logger as core_logger
import modules.users.users.constants as users_constants
import modules.users.users.crud as users_crud
import modules.users.users.signing as users_signing

logger = core_logger.get_logger(__name__)

#: Stored extensions, probed in turn because the row holds only the key the upload wrote and
#: older rows may carry any allowed extension.
PHOTO_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


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
    logger.info("User photo removed", extra=core_logger.context(user_id=user_id))

    delete_photo_files(user_id, storage)


def upload_photo(
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
    if users_crud.get_user_by_id(user_id, db) is None:
        raise core_exceptions.NotFoundError("User not found")

    if not file.filename:
        raise core_exceptions.InvalidInputError("Filename is required")

    # Defense-in-depth allow-list on the user-supplied extension. The upload reader still
    # validates the magic number, so a mismatched signature is rejected even if this passes.
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in users_constants.ALLOWED_USER_IMAGE_EXTENSIONS:
        raise core_exceptions.UnsupportedMediaTypeError("Unsupported user image file type")

    key = f"{user_id}{file_extension}"
    data = core_file_uploads.read_validated_upload_sync(file, kind=core_file_uploads.UploadKind.IMAGE)
    storage.save(users_constants.USER_IMAGE_STORAGE_AREA, key, data, file.content_type)

    users_crud.update_user(user_id, {"photo_path": key}, db)
    db.commit()
    logger.info("User photo saved", extra=core_logger.context(user_id=user_id))
    return key


def read_photo(user_id: int, token: str, storage: platform_providers.StorageProvider) -> tuple[bytes, str]:
    """Read a user's stored photo when the signed token is valid.

    Args:
        user_id: The user whose photo to read.
        token: The signed access token minted when the user record was serialized.
        storage: The platform storage provider.

    Returns:
        The image bytes and their content type.

    Raises:
        NotFoundError: If the token is invalid or forged, or no photo is stored. Answered as a 404
            rather than a 403, so the response does not confirm the user id.
    """
    if not users_signing.verify_user_image_token(user_id, token):
        # Security-relevant: a forged token, or one replayed against another user. Logged at
        # warning so a probing pattern is visible.
        logger.warning(
            "Rejected a user photo request with an invalid signed token",
            extra=core_logger.context(user_id=user_id),
        )
        raise core_exceptions.NotFoundError("User photo not found")

    for extension, content_type in PHOTO_CONTENT_TYPES.items():
        data = storage.get(users_constants.USER_IMAGE_STORAGE_AREA, f"{user_id}{extension}")
        if data is not None:
            return data, content_type

    raise core_exceptions.NotFoundError("User photo not found")
