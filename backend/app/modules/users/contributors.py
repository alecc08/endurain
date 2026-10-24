"""Typed callbacks the users namespace asks composition to install.

Deleting an account must erase the data other modules keep about the user. Those modules sit above
users (activities consumes the users surface), so users states what it needs erased and
``app/module_registry.py`` installs the answers.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

#: ``(user_id, db)`` -> stages the deletion of every activity the user owns and returns how many it
#: touched. Going through the owning module is what lets it clean up the blobs stored per activity.
ActivitiesEraser = Callable[[int, Session], int]


@dataclass(frozen=True, kw_only=True)
class UserErasers:
    """The erasures composition installs for the users namespace.

    Attributes:
        delete_activities: Stages the deletion of a user's activities and their stored files.
    """

    delete_activities: ActivitiesEraser
