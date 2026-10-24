"""Pydantic response shapes for the profile import."""

from pydantic import BaseModel, ConfigDict, Field

import modules.users.users_profile.constants as profile_constants


class ProfileImportStatus(BaseModel):
    """Where the authenticated user's profile import is.

    Attributes:
        status: Lifecycle state of the import.
        failure: Why the import failed; set only when it failed.
        imported: How many items of each kind were imported; set only when it completed.
    """

    status: profile_constants.ImportStatus = Field(..., description="Lifecycle state of the import")
    failure: profile_constants.ImportFailure | None = Field(default=None, description="Reason the import failed")
    imported: dict[str, int] | None = Field(default=None, description="Items imported per kind, once completed")

    model_config = ConfigDict(from_attributes=True, extra="forbid")
