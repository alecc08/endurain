"""Tests for core.attempt_state (provider-backed claim and polled state)."""

from unittest.mock import patch

import pytest
from jasil.backends.state_memory import MemoryState
from jasil.providers import StateBackendUnavailableError
from pydantic import BaseModel

import core.attempt_state as core_attempt_state


class _State(BaseModel):
    step: str


def _store(state=None, ttl=60) -> core_attempt_state.AttemptStateStore:
    return core_attempt_state.AttemptStateStore(state or MemoryState(), "feature", "job", ttl)


def test_keys_are_namespaced_by_feature_and_kind():
    state = MemoryState()
    store = _store(state)
    store.begin("1", _State(step="queued"))

    assert state.get(core_attempt_state.key("feature", "job:state", "1")) is not None
    assert state.get(core_attempt_state.key("feature", "job:claim", "1")) is not None
    assert core_attempt_state.key("garmin", "link:state", "1") == "endurain:garmin:link:state:1"


def test_a_second_begin_is_refused_until_the_attempt_finishes():
    store = _store()

    assert store.begin("1", _State(step="queued")) is True
    assert store.begin("1", _State(step="queued")) is False

    store.record("1", _State(step="done"), finished=True)

    assert store.begin("1", _State(step="queued")) is True


def test_subjects_and_features_do_not_block_each_other():
    state = MemoryState()
    store = _store(state)
    other_feature = core_attempt_state.AttemptStateStore(state, "other", "job", 60)
    store.begin("1", _State(step="queued"))

    assert store.begin("2", _State(step="queued")) is True
    assert other_feature.begin("1", _State(step="queued")) is True


def test_read_returns_the_recorded_state_or_none():
    store = _store()
    assert store.read("1") is None

    store.begin("1", _State(step="queued"))
    store.record("1", _State(step="running"), finished=False)

    assert _State.model_validate_json(store.read("1")) == _State(step="running")


def test_progress_renews_the_claim():
    state = MemoryState()
    store = _store(state)
    store.begin("1", _State(step="queued"))
    with patch.object(state, "set") as write:
        store.record("1", _State(step="running"), finished=False)

    assert core_attempt_state.key("feature", "job:claim", "1") in [call.args[0] for call in write.call_args_list]


def test_release_frees_the_claim_without_touching_the_state():
    store = _store()
    store.begin("1", _State(step="queued"))

    store.release("1")

    assert store.read("1") is not None
    assert store.begin("1", _State(step="queued")) is True


def test_a_claim_is_not_left_behind_when_the_first_state_cannot_be_written():
    state = MemoryState()
    store = _store(state)
    with (
        patch.object(state, "set", side_effect=StateBackendUnavailableError("down")),
        pytest.raises(core_attempt_state.StateUnavailableError),
    ):
        store.begin("1", _State(step="queued"))

    assert store.begin("1", _State(step="queued")) is True


def test_an_outage_on_read_is_a_service_unavailable_error():
    state = MemoryState()
    store = _store(state)
    with (
        patch.object(state, "get", side_effect=StateBackendUnavailableError("down")),
        pytest.raises(core_attempt_state.StateUnavailableError),
    ):
        store.read("1")


def test_an_outage_while_recording_or_releasing_is_swallowed():
    state = MemoryState()
    store = _store(state)
    store.begin("1", _State(step="queued"))
    with patch.object(state, "set", side_effect=StateBackendUnavailableError("down")):
        store.record("1", _State(step="running"), finished=False)
    with patch.object(state, "delete", side_effect=StateBackendUnavailableError("down")):
        store.release("1")
