"""Tests for users.users.photo_service module."""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

import core.exceptions as core_exceptions
import modules.users.users.photo_service as users_photo_service

_CRUD = "modules.users.users.photo_service.users_crud"


def _upload(filename: str | None, content_type: str = "image/jpeg") -> UploadFile:
    return UploadFile(io.BytesIO(b"data"), filename=filename, headers=Headers({"content-type": content_type}))


class TestDeletePhotoFiles:
    def test_deletes_every_stored_extension_for_the_user(self):
        storage = MagicMock()
        storage.list_keys.return_value = ["7.jpg", "7.png"]

        users_photo_service.delete_photo_files(7, storage)

        storage.list_keys.assert_called_once_with("user_images", "7.")
        assert [call.args for call in storage.delete.call_args_list] == [
            ("user_images", "7.jpg"),
            ("user_images", "7.png"),
        ]


class TestDeletePhoto:
    @patch(_CRUD)
    def test_commits_the_cleared_reference_before_deleting_blobs(self, mock_crud, mock_db):
        storage = MagicMock()
        storage.list_keys.return_value = ["7.jpg"]
        order = MagicMock()
        order.attach_mock(mock_crud.update_user, "row")
        order.attach_mock(mock_db.commit, "commit")
        order.attach_mock(storage.delete, "blob")

        users_photo_service.delete_photo(7, storage, mock_db)

        assert [call[0] for call in order.mock_calls] == ["row", "commit", "blob"]
        assert mock_crud.update_user.call_args.args[1] == {"photo_path": None}


class TestUploadPhoto:
    @patch(_CRUD)
    def test_stores_the_blob_and_records_the_key(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = MagicMock()
        storage = MagicMock()

        with patch(
            "modules.users.users.photo_service.core_file_uploads.read_validated_upload_sync",
            return_value=b"bytes",
        ):
            key = users_photo_service.upload_photo(7, _upload("Avatar.JPG"), storage, mock_db)

        assert key == "7.jpg"
        assert storage.save.call_args.args[:3] == ("user_images", "7.jpg", b"bytes")
        assert mock_crud.update_user.call_args.args[1] == {"photo_path": "7.jpg"}
        mock_db.commit.assert_called_once()

    @patch(_CRUD)
    def test_unknown_user_is_not_found(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = None

        with pytest.raises(core_exceptions.NotFoundError):
            users_photo_service.upload_photo(7, _upload("a.jpg"), MagicMock(), mock_db)

    @patch(_CRUD)
    def test_missing_filename_is_invalid(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = MagicMock()

        with pytest.raises(core_exceptions.InvalidInputError):
            users_photo_service.upload_photo(7, _upload(None), MagicMock(), mock_db)

    @patch(_CRUD)
    def test_unsupported_extension_stores_nothing(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = MagicMock()
        storage = MagicMock()

        with pytest.raises(core_exceptions.UnsupportedMediaTypeError):
            users_photo_service.upload_photo(7, _upload("a.exe"), storage, mock_db)

        storage.save.assert_not_called()
        mock_db.commit.assert_not_called()
