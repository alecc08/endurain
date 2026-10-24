"""Tests for the users_profile module surface."""

from unittest.mock import MagicMock, patch

import modules.users.users_profile.integration_service as profile_integration

_MODULE = "modules.users.users_profile.integration_service"


def test_deleting_staged_transfers_discards_the_export_and_the_imports():
    storage = MagicMock()

    with (
        patch(f"{_MODULE}.profile_export_job_service.discard_staged_export") as export,
        patch(f"{_MODULE}.profile_import_job_service.discard_staged_imports") as imports,
    ):
        profile_integration.delete_staged_transfers(7, storage)

    export.assert_called_once_with(7, storage)
    imports.assert_called_once_with(7, storage)
