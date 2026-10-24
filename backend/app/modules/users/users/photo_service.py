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

#: The content type served for each stored extension.
PHOTO_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def delete_photo_files(user_id: int, storage: platform_providers.StorageProvider) -> None:
    """Delete every stored photo blob of a user, as housekeeping.

    Used once the row no longer names a photo. Failing to remove a blob only wastes space, so the
    failure is logged and not raised: the caller's change is already committed.

    Args:
        user_id: ID of the user whose photo files to delete.
        storage: The platform storage provider.
    """
    try:
        for key in storage.list_keys(users_constants.USER_IMAGE_STORAGE_AREA, f"{user_id}."):
            storage.delete(users_constants.USER_IMAGE_STORAGE_AREA, key)
    except Exception as err:
        logger.warning("Could not delete user photo files", exc_info=err, extra=core_logger.context(user_id=user_id))


def _delete_replaced_blob(
    user_id: int, replaced: str | None, keep: str | None, storage: platform_providers.StorageProvider
) -> None:
    """Delete the blob a committed change replaced, as housekeeping.

    Only the key the row held is removed, never a listing of the user's blobs: a listing could
    include the blob of a concurrent upload that has not committed yet. Failing to remove it only
    wastes space, and account deletion removes every blob under the user's prefix, so the failure
    is logged and not raised.

    Args:
        user_id: The user whose old blob to remove.
        replaced: The key the row held before the change.
        keep: The key the row holds now, which must stay.
        storage: The platform storage provider.
    """
    if replaced is None or replaced == keep:
        return
    try:
        storage.delete(users_constants.USER_IMAGE_STORAGE_AREA, replaced)
    except Exception as err:
        logger.warning(
            "Could not remove a replaced user photo", exc_info=err, extra=core_logger.context(user_id=user_id)
        )


def delete_photo(user_id: int, storage: platform_providers.StorageProvider, db: Session) -> None:
    """Clear a user's photo reference, commit, then delete the stored blob.

    The reference is committed first, so a failure never leaves a row pointing at a blob that
    is already gone.

    Args:
        user_id: ID of the user whose photo to delete.
        storage: The platform storage provider.
        db: Database session.

    Raises:
        NotFoundError: If the user does not exist.
    """
    replaced = users_crud.replace_photo_key(user_id, None, db)
    db.commit()
    logger.info("User photo removed", extra=core_logger.context(user_id=user_id))

    _delete_replaced_blob(user_id, replaced, None, storage)


def store_photo(
    user_id: int,
    extension: str,
    data: bytes,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> str:
    """Store a user's already validated photo, record its key and commit.

    The read that checks the user ends before the blob is written, so no transaction stays open
    across the storage call. The blob the row named before is removed after the commit.

    Args:
        user_id: ID of the user whose photo is being saved.
        extension: The image extension including the dot, one of the allowed photo extensions.
        data: The validated image bytes.
        storage: The platform storage provider.
        db: Database session.

    Returns:
        The storage key of the saved photo.

    Raises:
        NotFoundError: If the user does not exist.
        UnsupportedMediaTypeError: If the extension is not an allowed image type.
    """
    extension = extension.lower()
    if extension not in users_constants.ALLOWED_USER_IMAGE_EXTENSIONS:
        raise core_exceptions.UnsupportedMediaTypeError("Unsupported user image file type")

    if users_crud.get_user_by_id(user_id, db) is None:
        raise core_exceptions.NotFoundError("User not found")
    db.commit()

    key = f"{user_id}{extension}"
    storage.save(users_constants.USER_IMAGE_STORAGE_AREA, key, data, PHOTO_CONTENT_TYPES[extension])

    replaced = users_crud.replace_photo_key(user_id, key, db)
    db.commit()
    logger.info("User photo saved", extra=core_logger.context(user_id=user_id))

    _delete_replaced_blob(user_id, replaced, key, storage)
    return key


def upload_photo(
    user_id: int,
    file: UploadFile,
    storage: platform_providers.StorageProvider,
    db: Session,
) -> str:
    """Validate and store a user's uploaded photo, then record its key and commit.

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

    data = core_file_uploads.read_validated_upload_sync(file, kind=core_file_uploads.UploadKind.IMAGE)
    return store_photo(user_id, file_extension, data, storage, db)


def read_photo(user_id: int, token: str, storage: platform_providers.StorageProvider, db: Session) -> tuple[bytes, str]:
    """Read a user's stored photo when the signed token is valid.

    The row names the photo, so a blob left under another extension is never served. The read
    transaction ends before the storage call.

    Args:
        user_id: The user whose photo to read.
        token: The signed access token minted when the user record was serialized.
        storage: The platform storage provider.
        db: Database session.

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

    key = users_crud.get_photo_key(user_id, db)
    db.commit()
    if not key:
        raise core_exceptions.NotFoundError("User photo not found")

    data = storage.get(users_constants.USER_IMAGE_STORAGE_AREA, key)
    if data is None:
        raise core_exceptions.NotFoundError("User photo not found")

    return data, PHOTO_CONTENT_TYPES.get(os.path.splitext(key)[1].lower(), "application/octet-stream")
