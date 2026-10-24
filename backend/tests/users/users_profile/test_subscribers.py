"""Tests for users_profile.subscribers: the durable and bus entry points of a queued import."""

from unittest.mock import MagicMock, patch

import pytest
from jasil.events import Event, new_event

import modules.users.users_profile.events as profile_events
import modules.users.users_profile.subscribers as profile_subscribers

_MODULE = "modules.users.users_profile.subscribers"


def _event(retry_count: int = 0) -> Event:
    return new_event(
        profile_events.USERS_PROFILE_IMPORT_REQUESTED,
        {"user_id": 4, "staged_key": "4/a.zip"},
        source="test",
        retry_count=retry_count,
    )


@pytest.fixture
def run_import():
    platform = MagicMock()
    with (
        patch(f"{_MODULE}.profile_import_job_service.run_import") as run,
        patch(f"{_MODULE}.platform_runtime.get_active_platform", return_value=platform),
    ):
        yield run


def test_the_durable_handler_runs_the_import_the_event_names(run_import):
    profile_subscribers.process_import_requested_for_event(_event())

    payload = run_import.call_args.args[0]
    assert (payload.user_id, payload.staged_key) == (4, "4/a.zip")


def test_a_durable_attempt_with_attempts_left_asks_to_be_retried(run_import):
    with patch(f"{_MODULE}.core_config.settings", MagicMock(JOBS_MAX_ATTEMPTS=3)):
        profile_subscribers.process_import_requested_for_event(_event(retry_count=1))

    assert run_import.call_args.kwargs["will_retry"] is True


def test_the_last_durable_attempt_does_not(run_import):
    with patch(f"{_MODULE}.core_config.settings", MagicMock(JOBS_MAX_ATTEMPTS=3)):
        profile_subscribers.process_import_requested_for_event(_event(retry_count=3))

    assert run_import.call_args.kwargs["will_retry"] is False


def test_the_bus_subscriber_never_asks_for_a_retry(run_import):
    profile_subscribers.run_import_requested_on_bus(_event())

    assert run_import.call_args.kwargs["will_retry"] is False


def test_both_paths_are_registered_for_the_event():
    events, registry = MagicMock(), MagicMock()

    profile_subscribers.register_bus_subscribers(events)
    profile_subscribers.register_durable_handlers(registry)

    assert events.subscribe.call_args.args[0] == profile_events.USERS_PROFILE_IMPORT_REQUESTED
    assert registry.register.call_args.args[:2] == (
        profile_events.USERS_PROFILE_IMPORT_REQUESTED,
        profile_subscribers.IMPORT_REQUESTED_SUBSCRIBER_ID,
    )
