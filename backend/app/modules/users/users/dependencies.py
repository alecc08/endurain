"""Request-parameter types for the user routes."""

from typing import Annotated

from fastapi import Path

#: A username path segment: required, and decoded and lower-cased by the lookup.
Username = Annotated[str, Path(min_length=1)]

#: An email address path segment: required, and lower-cased by the lookup.
Email = Annotated[str, Path(min_length=1)]
