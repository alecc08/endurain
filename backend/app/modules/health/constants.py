"""Constants for health-related modules."""

from enum import Enum

#: Times an upsert re-reads a day's record and applies again after another writer changed it first.
#: Each round lets at least one writer through, so this serves up to that many concurrent writers of one day.
UPSERT_ATTEMPTS = 5


class Interval(Enum):
    """Enumeration of time intervals for health weight data queries.

    Attributes:
        LAST_7_DAYS: Last 7 days interval.
        LAST_30_DAYS: Last 30 days interval.
        LAST_90_DAYS: Last 90 days interval.
        LAST_YEAR: Last year interval.
        ALL_TIME: All time interval.
    """

    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    LAST_YEAR = "last_year"
    ALL_TIME = "all_time"
