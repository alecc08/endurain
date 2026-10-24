"""Request-parameter types for the profile routes."""

from typing import Annotated

from fastapi import Path

#: The identifier of one of the caller's sessions, as the auth boundary issued it.
SessionId = Annotated[str, Path(min_length=1)]
