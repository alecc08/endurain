"""Tests for users_profile.subscribers: the durable and bus entry points of a queued import."""

from unittest.mock import MagicMock, patch

import pytest
from jasil.events import Event, new_event

import core.local_pool as core_local_pool
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


@pytest.fixture(autouse=True)
def inline_transfer_pool():
    """Run the transfer pool's jobs on the calling thread, and keep the real pool out of the test."""
    with patch(f"{_MODULE}.profile_transfer_pool.pool") as pool:
        pool.submit.side_effect = lambda run, *args, **kwargs: run(*args, **kwargs)
        yield pool


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


def test_a_bus_import_runs_on_the_transfer_pool_not_the_subscriber_thread(inline_transfer_pool, run_import):
    profile_subscribers.run_import_requested_on_bus(_event())

    inline_transfer_pool.submit.assert_called_once()


def test_a_bus_import_the_full_pool_refuses_is_closed_not_left_queued(inline_transfer_pool):
    inline_transfer_pool.submit.side_effect = core_local_pool.PoolFullError("full")
    with (
        patch(f"{_MODULE}.profile_import_job_service.fail_unstarted_import") as fail,
        patch(f"{_MODULE}.platform_runtime.get_active_platform", return_value=MagicMock()),
    ):
        profile_subscribers.run_import_requested_on_bus(_event())

    assert fail.call_args.args[0].user_id == 4


def test_a_bus_export_the_full_pool_refuses_is_closed_not_left_queued(inline_transfer_pool):
    inline_transfer_pool.submit.side_effect = core_local_pool.PoolFullError("full")
    with (
        patch(f"{_MODULE}.profile_export_job_service.fail_unstarted_export") as fail,
        patch(f"{_MODULE}.platform_runtime.get_active_platform", return_value=MagicMock()),
    ):
        profile_subscribers.run_export_requested_on_bus(_export_event())

    assert fail.call_args.args[0].user_id == 4


def test_both_paths_are_registered_for_the_event():
    events, registry = MagicMock(), MagicMock()

    profile_subscribers.register_bus_subscribers(events)
    profile_subscribers.register_durable_handlers(registry)

    assert events.subscribe.call_args_list[0].args[0] == profile_events.USERS_PROFILE_IMPORT_REQUESTED
    assert registry.register.call_args_list[0].args[:2] == (
        profile_events.USERS_PROFILE_IMPORT_REQUESTED,
        profile_subscribers.IMPORT_REQUESTED_SUBSCRIBER_ID,
    )


def _export_event(retry_count: int = 0) -> Event:
    return new_event(
        profile_events.USERS_PROFILE_EXPORT_REQUESTED, {"user_id": 4}, source="test", retry_count=retry_count
    )


def test_the_export_handlers_run_the_export_the_event_names():
    platform = MagicMock()
    with (
        patch(f"{_MODULE}.profile_export_job_service.run_export") as run,
        patch(f"{_MODULE}.platform_runtime.get_active_platform", return_value=platform),
        patch(f"{_MODULE}.core_config.settings", MagicMock(JOBS_MAX_ATTEMPTS=3)),
    ):
        profile_subscribers.process_export_requested_for_event(_export_event(retry_count=1))
        durable = run.call_args
        profile_subscribers.run_export_requested_on_bus(_export_event())
        bus = run.call_args

    assert durable.args[0].user_id == 4
    assert durable.kwargs["will_retry"] is True
    assert bus.kwargs["will_retry"] is False


def test_the_export_is_registered_on_both_paths():
    events, registry = MagicMock(), MagicMock()

    profile_subscribers.register_bus_subscribers(events)
    profile_subscribers.register_durable_handlers(registry)

    assert profile_events.USERS_PROFILE_EXPORT_REQUESTED in [call.args[0] for call in events.subscribe.call_args_list]
    assert (
        profile_events.USERS_PROFILE_EXPORT_REQUESTED,
        profile_subscribers.EXPORT_REQUESTED_SUBSCRIBER_ID,
    ) in [call.args[:2] for call in registry.register.call_args_list]
