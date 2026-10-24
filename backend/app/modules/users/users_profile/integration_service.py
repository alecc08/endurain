"""Operations other modules may call on the profile import and export."""

import jasil.providers as platform_providers

import modules.users.users_profile.export_job_service as profile_export_job_service
import modules.users.users_profile.import_job_service as profile_import_job_service


def delete_staged_transfers(user_id: int, storage: platform_providers.StorageProvider) -> None:
    """Delete the archives staged for a user's profile export and imports.

    Housekeeping for a deleted account: a storage failure is logged, and the scheduled sweep
    removes whatever is left.

    Args:
        user_id: The user whose staged archives to remove.
        storage: The platform storage provider.
    """
    profile_export_job_service.discard_staged_export(user_id, storage)
    profile_import_job_service.discard_staged_imports(user_id, storage)
