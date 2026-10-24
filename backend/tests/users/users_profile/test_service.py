"""Tests for users_profile.service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.exceptions as core_exceptions
import modules.users.users_profile.exceptions as profile_exceptions
import modules.users.users_profile.service as profile_service

_MODULE = "modules.users.users_profile.service"


class TestEdits:
    @patch(f"{_MODULE}.users_integration")
    def test_profile_edit_stages_then_commits(self, mock_users, mock_db):
        profile = MagicMock()

        profile_service.edit_profile(1, profile, mock_db)

        mock_users.edit_profile.assert_called_once_with(1, profile, mock_db)
        mock_db.commit.assert_called_once()

    @patch(f"{_MODULE}.users_privacy_settings_integration")
    def test_privacy_edit_stages_then_commits(self, mock_privacy, mock_db):
        settings = MagicMock()

        profile_service.edit_privacy_settings(1, settings, mock_db)

        mock_privacy.edit_privacy_settings.assert_called_once_with(1, settings, mock_db)
        mock_db.commit.assert_called_once()

    @patch(f"{_MODULE}.users_integration")
    def test_a_failed_edit_does_not_commit(self, mock_users, mock_db):
        mock_users.edit_profile.side_effect = core_exceptions.ConflictError("taken")

        with pytest.raises(core_exceptions.ConflictError):
            profile_service.edit_profile(1, MagicMock(), mock_db)

        mock_db.commit.assert_not_called()


class TestExportProfile:
    @patch(f"{_MODULE}.profile_export_service")
    @patch(f"{_MODULE}.profile_utils")
    @patch(f"{_MODULE}.users_integration")
    def test_server_managed_fields_never_reach_the_archive(self, mock_users, mock_utils, mock_export, mock_db):
        mock_utils.sqlalchemy_obj_to_dict.return_value = {
            "name": "Test",
            "password": "secret",
            "mfa_secret": "s",
            "access_type": "admin",
            "active": True,
            "mfa_enabled": True,
            "email_verified": True,
            "pending_admin_approval": False,
        }
        storage = MagicMock()

        result = profile_service.export_profile(1, storage, mock_db)

        mock_export.ExportService.assert_called_once_with(1, storage, mock_db)
        exported = mock_export.ExportService.return_value.generate_export_archive.call_args.args[0]
        assert exported == {"name": "Test"}
        assert result == mock_export.ExportService.return_value.generate_export_archive.return_value

    @patch(f"{_MODULE}.users_integration")
    def test_unknown_user_is_not_found(self, mock_users, mock_db):
        mock_users.require_user.side_effect = core_exceptions.NotFoundError("User not found")

        with pytest.raises(core_exceptions.NotFoundError):
            profile_service.export_profile(1, MagicMock(), mock_db)


class TestImportProfile:
    def _import(self, mock_db, *, result=None, error=None):
        with patch(f"{_MODULE}.profile_import_service") as mock_import:
            importer = mock_import.ImportService.return_value
            importer.import_from_zip_data = AsyncMock(return_value=result, side_effect=error)
            return profile_service.import_profile(1, b"zip", MagicMock(), mock_db)

    def test_returns_the_import_result(self, mock_db):
        assert self._import(mock_db, result={"imported": {"activities": 2}}) == {"imported": {"activities": 2}}

    def test_a_rejected_archive_is_a_client_error(self, mock_db):
        with pytest.raises(core_exceptions.PayloadTooLargeError):
            self._import(mock_db, error=profile_exceptions.FileSizeError("too big"))

    def test_a_value_error_is_invalid_input(self, mock_db):
        with pytest.raises(core_exceptions.InvalidInputError) as exc:
            self._import(mock_db, error=ValueError("bad value"))

        assert exc.value.detail == "bad value"

    def test_an_operation_failure_maps_to_its_domain_error(self, mock_db):
        with pytest.raises(profile_exceptions.TransferTimeoutError):
            self._import(mock_db, error=profile_exceptions.ImportTimeoutError("slow"))

    def test_an_unexpected_failure_hides_its_cause(self, mock_db):
        with pytest.raises(core_exceptions.ProcessingError) as exc:
            self._import(mock_db, error=RuntimeError("secret internals"))

        assert "secret internals" not in exc.value.detail
