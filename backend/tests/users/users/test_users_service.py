"""Tests for users.users.service module."""

from unittest.mock import MagicMock, patch

import pytest

import core.exceptions as core_exceptions
import modules.users.users.schema as users_schema
import modules.users.users.service as users_service

_CRUD = "modules.users.users.service.users_crud"
_SETTINGS = "modules.users.users.service.server_settings_integration"


def _user(user_id: int = 1, **overrides) -> users_schema.UsersRead:
    fields = {
        "id": user_id,
        "name": "User",
        "username": f"user{user_id}",
        "email": f"user{user_id}@example.com",
        "active": True,
        "access_type": "regular",
    }
    fields.update(overrides)
    return users_schema.UsersRead(**fields)


def _signup() -> users_schema.UsersSignup:
    return users_schema.UsersSignup(
        name="New", username="NewUser", email="New@Example.com", password="SecurePass1!", preferred_language="en"
    )


class TestRequirements:
    @patch(_CRUD)
    def test_require_user_returns_the_user(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = _user()

        assert users_service.require_user(1, mock_db).id == 1

    @patch(_CRUD)
    def test_require_user_missing_is_not_found(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = None

        with pytest.raises(core_exceptions.NotFoundError):
            users_service.require_user(1, mock_db)

    def test_require_active_user_refuses_an_inactive_user(self):
        with pytest.raises(core_exceptions.PermissionDeniedError):
            users_service.require_active_user(_user(active=False))

    def test_require_active_user_passes_an_active_user(self):
        users_service.require_active_user(_user())

    @patch(_CRUD)
    def test_require_admin_users_none_is_not_found(self, mock_crud, mock_db):
        mock_crud.get_users_admin.return_value = []

        with pytest.raises(core_exceptions.NotFoundError):
            users_service.require_admin_users(mock_db)


class TestPublicUser:
    @patch(_CRUD)
    @patch(_SETTINGS)
    def test_hidden_when_public_sharing_is_off(self, mock_settings, mock_crud, mock_db):
        mock_settings.get_server_settings.return_value = MagicMock(
            public_shareable_links=False, public_shareable_links_user_info=True
        )

        assert users_service.get_public_user(1, mock_db) is None
        mock_crud.get_user_by_id.assert_not_called()

    @patch(_CRUD)
    @patch(_SETTINGS)
    def test_hidden_when_user_info_sharing_is_off(self, mock_settings, mock_crud, mock_db):
        mock_settings.get_server_settings.return_value = MagicMock(
            public_shareable_links=True, public_shareable_links_user_info=False
        )

        assert users_service.get_public_user(1, mock_db) is None

    @patch(_CRUD)
    @patch(_SETTINGS)
    def test_visible_when_both_are_on(self, mock_settings, mock_crud, mock_db):
        mock_settings.get_server_settings.return_value = MagicMock(
            public_shareable_links=True, public_shareable_links_user_info=True
        )

        assert users_service.get_public_user(1, mock_db) == mock_crud.get_user_by_id.return_value


class TestListUsers:
    @patch(_CRUD)
    def test_enriches_and_filters_by_authentication(self, mock_crud, mock_db):
        mock_crud.get_users_number.return_value = 2
        mock_crud.get_users_with_pagination.return_value = [_user(1, name="Alice"), _user(2, name="Bob")]
        identity = MagicMock()
        identity.get_identity_link_counts_for_users.return_value = {1: 2}
        identity.get_mfa_enabled_for_users.return_value = {2: True}

        result = users_service.list_users(identity, mock_db, page_number=1, num_records=10, show_external_auth=False)

        assert result.total == 2
        assert [u.name for u in result.records] == ["Bob"]
        assert result.records[0].mfa_enabled is True

    @patch(_CRUD)
    def test_local_filter_drops_users_without_a_link(self, mock_crud, mock_db):
        mock_crud.get_users_number.return_value = 2
        mock_crud.get_users_with_pagination.return_value = [_user(1, name="Alice"), _user(2, name="Bob")]
        identity = MagicMock()
        identity.get_identity_link_counts_for_users.return_value = {1: 1}
        identity.get_mfa_enabled_for_users.return_value = {}

        result = users_service.list_users(identity, mock_db, show_local_auth=False)

        assert [u.name for u in result.records] == ["Alice"]


class TestCreateUser:
    @patch("modules.users.users.service._stage_default_data")
    @patch(_SETTINGS)
    @patch(_CRUD)
    def test_hashes_creates_commits_then_stores_the_credential(self, mock_crud, mock_settings, mock_defaults, mock_db):
        identity = MagicMock()
        identity.validate_and_hash_password_for_user.return_value = "hash"
        mock_crud.create_user.return_value = _user(7)
        user = users_schema.UsersCreate(
            name="N",
            username="NewUser",
            email="New@Example.com",
            active=True,
            access_type="regular",
            password="password123",
        )

        created = users_service.create_user(user, identity, mock_db)

        fields = mock_crud.create_user.call_args.args[0]
        assert fields["username"] == "newuser" and fields["email"] == "new@example.com"
        assert "password" not in fields
        mock_db.commit.assert_called_once()
        identity.set_local_password_hash.assert_called_once_with(7, "hash")
        mock_defaults.assert_called_once_with(7, identity, mock_db)
        assert created.id == 7

    @patch(_SETTINGS)
    @patch(_CRUD)
    def test_duplicate_rolls_back_and_stores_no_credential(self, mock_crud, mock_settings, mock_db):
        identity = MagicMock()
        mock_crud.create_user.side_effect = core_exceptions.ConflictError("dup")
        user = users_schema.UsersCreate(
            name="N", username="n", email="n@example.com", active=True, access_type="regular", password="password123"
        )

        with pytest.raises(core_exceptions.ConflictError):
            users_service.create_user(user, identity, mock_db)

        mock_db.rollback.assert_called_once()
        identity.set_local_password_hash.assert_not_called()


class TestCreateSignupUser:
    def _settings(self, verification: bool, approval: bool):
        return MagicMock(signup_require_email_verification=verification, signup_require_admin_approval=approval)

    @pytest.mark.parametrize(
        ("verification", "approval", "active", "email_verified", "pending"),
        [
            (False, False, True, True, False),
            (True, False, False, False, False),
            (False, True, False, False, True),
            (True, True, False, False, True),
        ],
    )
    @patch("modules.users.users.service._stage_default_data")
    @patch(_CRUD)
    def test_account_state_follows_the_signup_policy(
        self, mock_crud, _defaults, verification, approval, active, email_verified, pending, mock_db
    ):
        identity = MagicMock()
        mock_crud.create_user.return_value = _user(3)

        users_service.create_signup_user(_signup(), self._settings(verification, approval), identity, mock_db)

        fields = mock_crud.create_user.call_args.args[0]
        assert (fields["active"], fields["email_verified"], fields["pending_admin_approval"]) == (
            active,
            email_verified,
            pending,
        )
        assert fields["access_type"] == "regular"
        assert fields["username"] == "newuser"

    @patch("modules.users.users.service._stage_default_data")
    @patch(_CRUD)
    def test_sso_account_gets_no_credential(self, mock_crud, _defaults, mock_db):
        identity = MagicMock()
        mock_crud.create_user.return_value = _user(3)

        users_service.create_signup_user(_signup(), self._settings(False, False), identity, mock_db, False)

        identity.validate_and_hash_password_for_user.assert_not_called()
        identity.set_local_password_hash.assert_not_called()

    @patch(_CRUD)
    def test_duplicate_gives_an_abstract_conflict(self, mock_crud, mock_db):
        mock_crud.create_user.side_effect = core_exceptions.ConflictError("email taken")

        with pytest.raises(core_exceptions.ConflictError) as exc:
            users_service.create_signup_user(_signup(), self._settings(False, False), MagicMock(), mock_db)

        assert exc.value.detail == "Unable to create user."
        mock_db.rollback.assert_called_once()


class TestStageDefaultData:
    @patch("modules.users.users.service.users_default_gear_integration")
    @patch("modules.users.users.service.health_targets_integration")
    @patch("modules.users.users.service.users_privacy_settings_integration")
    @patch("modules.users.users.service.user_integrations_integration")
    def test_creates_every_default_row_then_commits_then_the_mfa_row(
        self, mock_integrations, mock_privacy, mock_targets, mock_gear, mock_db
    ):
        identity = MagicMock()

        users_service._stage_default_data(5, identity, mock_db)

        mock_integrations.create_integrations.assert_called_once_with(5, mock_db)
        mock_privacy.create_privacy_settings.assert_called_once_with(5, mock_db)
        mock_targets.create_health_targets.assert_called_once_with(5, mock_db)
        mock_gear.create_default_gear.assert_called_once_with(5, mock_db)
        mock_db.commit.assert_called_once()
        identity.initialize_user_mfa.assert_called_once_with(5)


@patch("modules.users.users.service.health_weight_integration")
@patch(_CRUD)
class TestEdits:
    def test_admin_edit_lowercases_and_drops_response_only_fields(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, height=170)
        mock_crud.update_user.return_value = _user(1, height=170)

        users_service.stage_user_edit(1, _user(1, username="MixedCase", photo_path="/url"), mock_db)

        changes = mock_crud.update_user.call_args.args[1]
        assert changes["username"] == "mixedcase"
        assert "photo_path" not in changes
        assert "mfa_enabled" not in changes
        mock_weight.recalculate_bmi_for_user.assert_not_called()

    def test_admin_edit_recalculates_bmi_when_height_changes(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, height=170)
        mock_crud.update_user.return_value = _user(1, height=180)

        users_service.stage_user_edit(1, _user(1, height=180), mock_db)

        mock_weight.recalculate_bmi_for_user.assert_called_once_with(1, 180.0, mock_db)

    def test_edit_user_commits_and_reports_authentication(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1)
        mock_crud.update_user.return_value = _user(1)
        identity = MagicMock()
        identity.get_identity_link_counts_for_users.return_value = {1: 2}
        identity.get_mfa_enabled_for_users.return_value = {1: True}

        result = users_service.edit_user(1, _user(1), identity, mock_db)

        mock_db.commit.assert_called_once()
        assert result.external_auth_count == 2
        assert result.mfa_enabled is True

    def test_edit_user_conflict_rolls_back(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1)
        mock_crud.update_user.side_effect = core_exceptions.ConflictError("dup")

        with pytest.raises(core_exceptions.ConflictError):
            users_service.edit_user(1, _user(1), MagicMock(), mock_db)

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    def test_profile_edit_keeps_only_allow_listed_fields(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1)
        mock_crud.update_user.return_value = _user(1)
        profile = users_schema.ProfileUpdate.model_construct(
            name="New", username="MIXED", access_type="admin", active=False, email_verified=True
        )
        profile.__pydantic_fields_set__.update({"name", "username", "access_type", "active", "email_verified"})

        users_service.stage_profile_edit(1, profile, mock_db)

        assert mock_crud.update_user.call_args.args[1] == {"name": "New", "username": "mixed"}

    def test_profile_height_change_recalculates_bmi(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, height=170)
        mock_crud.update_user.return_value = _user(1, height=175)

        users_service.stage_profile_edit(1, users_schema.ProfileUpdate(height=175), mock_db)

        mock_weight.recalculate_bmi_for_user.assert_called_once_with(1, 175.0, mock_db)

    def test_profile_without_height_never_recalculates(self, mock_crud, mock_weight, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, height=170)
        mock_crud.update_user.return_value = _user(1, height=175)

        users_service.stage_profile_edit(1, users_schema.ProfileUpdate(name="Only"), mock_db)

        mock_weight.recalculate_bmi_for_user.assert_not_called()


@patch(_CRUD)
class TestApproveAndVerify:
    def test_approve_activates_and_commits(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, email_verified=True)

        users_service.approve_user(1, mock_db)

        mock_crud.update_user.assert_called_once_with(1, {"pending_admin_approval": False, "active": True}, mock_db)
        mock_db.commit.assert_called_once()

    def test_approve_refuses_an_unverified_email(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, email_verified=False)

        with pytest.raises(core_exceptions.InvalidInputError):
            users_service.approve_user(1, mock_db)

        mock_crud.update_user.assert_not_called()

    def test_verification_activates_without_approval_policy(self, mock_crud, mock_db):
        users_service.stage_email_verification(1, MagicMock(signup_require_admin_approval=False), mock_db)

        assert mock_crud.update_user.call_args.args[1] == {
            "email_verified": True,
            "pending_admin_approval": False,
            "active": True,
        }
        mock_db.commit.assert_not_called()

    def test_verification_leaves_the_account_pending_under_approval_policy(self, mock_crud, mock_db):
        users_service.stage_email_verification(1, MagicMock(signup_require_admin_approval=True), mock_db)

        assert mock_crud.update_user.call_args.args[1] == {"email_verified": True}


class TestDeleteUser:
    @patch("modules.users.users.service.users_photo_service")
    @patch("modules.users.users.service.activity_integration")
    @patch(_CRUD)
    def test_removes_activities_then_the_row_then_the_photo(self, mock_crud, mock_activities, mock_photos, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1)
        storage = MagicMock()
        order = MagicMock()
        order.attach_mock(mock_activities.delete_all_activities_for_user, "activities")
        order.attach_mock(mock_crud.delete_user, "row")
        order.attach_mock(mock_db.commit, "commit")
        order.attach_mock(mock_photos.delete_photo_files, "photos")

        users_service.delete_user(1, storage, mock_db)

        assert [call[0] for call in order.mock_calls] == ["activities", "row", "commit", "photos"]
        mock_photos.delete_photo_files.assert_called_once_with(1, storage)

    @patch("modules.users.users.service.activity_integration")
    @patch(_CRUD)
    def test_unknown_user_deletes_nothing(self, mock_crud, mock_activities, mock_db):
        mock_crud.get_user_by_id.return_value = None

        with pytest.raises(core_exceptions.NotFoundError):
            users_service.delete_user(1, MagicMock(), mock_db)

        mock_activities.delete_all_activities_for_user.assert_not_called()


class TestTimezone:
    @patch(_CRUD)
    def test_prefers_the_users_own_zone(self, mock_crud, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1, timezone="Europe/Lisbon")

        assert users_service.resolve_user_timezone(1, mock_db) == "Europe/Lisbon"

    @patch("modules.users.users.service.core_timezone")
    @patch(_CRUD)
    def test_falls_back_to_the_server_zone(self, mock_crud, mock_tz, mock_db):
        mock_crud.get_user_by_id.return_value = _user(1)
        mock_tz.or_default.side_effect = lambda tz: tz or "UTC"

        assert users_service.resolve_user_timezone(1, mock_db) == "UTC"

    @patch("modules.users.users.service.core_timezone")
    @patch(_CRUD)
    def test_falls_back_when_the_user_is_missing(self, mock_crud, mock_tz, mock_db):
        mock_crud.get_user_by_id.return_value = None
        mock_tz.or_default.side_effect = lambda tz: tz or "UTC"

        assert users_service.resolve_user_timezone(1, mock_db) == "UTC"

    @patch("modules.users.users.service.core_timezone")
    def test_today_is_resolved_in_the_resolved_zone(self, mock_tz, mock_db):
        with patch("modules.users.users.service.resolve_user_timezone", return_value="Pacific/Auckland"):
            result = users_service.user_local_today(1, mock_db)

        mock_tz.today_in.assert_called_once_with("Pacific/Auckland")
        assert result == mock_tz.today_in.return_value
