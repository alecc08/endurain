"""Request-parameter types for the profile routes."""

from typing import Annotated

from fastapi import Depends, Path

import core.dependencies as core_dependencies
import modules.users.users_profile.import_state_store as profile_import_state_store

#: The identifier of one of the caller's sessions, as the auth boundary issued it.
SessionId = Annotated[str, Path(min_length=1)]


def get_profile_import_state_store(
    state: core_dependencies.PlatformState,
) -> profile_import_state_store.ProfileImportStateStore:
    """Return the import state store over the platform state provider.

    Args:
        state: The platform state provider.

    Returns:
        The import state store.
    """
    return profile_import_state_store.ProfileImportStateStore(state)


ProfileImportStateStoreDep = Annotated[
    profile_import_state_store.ProfileImportStateStore, Depends(get_profile_import_state_store)
]
