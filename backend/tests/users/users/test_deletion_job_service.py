"""Tests for users.deletion_job_service: accepting, running and closing account deletions."""

from unittest.mock import MagicMock, patch

import pytest
from jasil.backends.state_memory import MemoryState

import core.exceptions as core_exceptions
import modules.users.users.constants as users_constants
import modules.users.users.deletion_job_service as job_service
import modules.users.users.deletion_state_store as deletion_state_store
import modules.users.users.events as users_events

_MODULE = "modules.users.users.deletion_job_service"
_Status = users_constants.DeletionStatus
_Kind = users_constants.DeletionKind.ACCOUNT


@pytest.fixture
def states():
    return deletion_state_store.UserDeletionStateStore(MemoryState())


@pytest.fixture
def mock_db():
    return MagicMock()


def _payload(user_id: int = 1) -> users_events.DeletionRequestedPayload:
    return users_events.DeletionRequestedPayload(user_id=user_id)


class TestRequestDeletion:
    def _request(self, states, db, *, jobs_enabled, identity=None):
        identity = identity or MagicMock()
        with (
            patch(f"{_MODULE}.core_config.settings", MagicMock(JOBS_ENABLED=jobs_enabled)),
            patch(f"{_MODULE}.users_service") as users_service,
            patch(f"{_MODULE}.users_crud") as users_crud,
            patch(f"{_MODULE}.users_event_publishers") as publishers,
            patch(f"{_MODULE}._deletion_pool") as pool,
        ):
            result = job_service.request_deletion(1, identity, states, MagicMock(), db)
        return result, identity, users_service, users_crud, publishers, pool

    def test_a_durable_deletion_signs_out_deactivates_and_publishes(self, states, mock_db):
        result, identity, users_service, users_crud, publishers, pool = self._request(
            states, mock_db, jobs_enabled=True
        )

        assert result.status == _Status.QUEUED
        users_service.require_deletable_user.assert_called_once_with(1, mock_db)
        identity.delete_all_user_sessions.assert_called_once_with(1)
        users_crud.update_user.assert_called_once_with(1, {"active": False}, mock_db)
        publishers.publish_deletion_requested.assert_called_once_with(1, mock_db, commit=mock_db.commit)
        pool.submit.assert_not_called()
        assert states.get(1, _Kind).status == _Status.QUEUED

    def test_without_durable_jobs_the_commit_precedes_the_pool_submit(self, states, mock_db):
        _, _, _, _, publishers, pool = self._request(states, mock_db, jobs_enabled=False)

        pool.require_capacity.assert_called_once_with()
        mock_db.commit.assert_called_once_with()
        pool.submit.assert_called_once()
        publishers.publish_deletion_requested.assert_not_called()

    def test_a_pending_deletion_is_refused_without_touching_the_account(self, states, mock_db):
        states.begin(1, _Kind)
        identity = MagicMock()

        with pytest.raises(core_exceptions.ConflictError):
            self._request(states, mock_db, jobs_enabled=True, identity=identity)

        identity.delete_all_user_sessions.assert_not_called()

    def test_a_failure_before_the_job_starts_frees_the_claim(self, states, mock_db):
        identity = MagicMock()
        identity.delete_all_user_sessions.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            self._request(states, mock_db, jobs_enabled=True, identity=identity)

        assert states.get(1, _Kind).status == _Status.FAILED
        assert states.begin(1, _Kind) is True

    def test_a_full_local_pool_refuses_before_the_claim_is_taken(self, states, mock_db):
        with (
            patch(f"{_MODULE}.core_config.settings", MagicMock(JOBS_ENABLED=False)),
            patch(f"{_MODULE}.users_service"),
            patch(f"{_MODULE}._deletion_pool") as pool,
        ):
            pool.require_capacity.side_effect = core_exceptions.ServiceUnavailableError("full")
            with pytest.raises(core_exceptions.ServiceUnavailableError):
                job_service.request_deletion(1, MagicMock(), states, MagicMock(), mock_db)

        assert states.get(1, _Kind) is None

    def test_the_only_administrator_is_refused_first(self, states, mock_db):
        identity = MagicMock()
        with (
            patch(f"{_MODULE}.users_service") as users_service,
            patch(f"{_MODULE}.users_crud") as users_crud,
        ):
            users_service.require_deletable_user.side_effect = core_exceptions.ConflictError("only admin")
            with pytest.raises(core_exceptions.ConflictError):
                job_service.request_deletion(1, identity, states, MagicMock(), mock_db)

        identity.delete_all_user_sessions.assert_not_called()
        users_crud.update_user.assert_not_called()
        assert states.get(1, _Kind) is None


class TestRunDeletion:
    def _run(self, states, *, batches, row_exists=True, delete_error=None, will_retry=False):
        erasers = MagicMock()
        erasers.delete_activities.side_effect = [*batches, 0] if delete_error is None else delete_error
        with (
            patch(f"{_MODULE}.core_database.SessionLocal") as session_local,
            patch(f"{_MODULE}.users_contributor_registry.erasers", return_value=erasers),
            patch(f"{_MODULE}.users_crud") as users_crud,
            patch(f"{_MODULE}.users_photo_service") as photos,
        ):
            users_crud.get_user_by_id.return_value = MagicMock() if row_exists else None
            storage = MagicMock()
            job_service.run_deletion(_payload(), states, storage, will_retry=will_retry)
        return erasers, users_crud, photos, session_local, storage

    def test_erases_in_batches_then_the_row_then_the_files(self, states):
        states.begin(1, _Kind)

        erasers, users_crud, photos, session_local, storage = self._run(states, batches=[100, 40])

        assert erasers.delete_activities.call_count == 3
        assert erasers.delete_activities.call_args.args[:2] == (1, users_constants.DELETION_BATCH_SIZE)
        users_crud.delete_user.assert_called_once()
        photos.delete_photo_files.assert_called_once_with(1, storage)
        erasers.delete_staged_files.assert_called_once_with(1, storage)
        assert states.get(1, _Kind).status == _Status.COMPLETED
        # Every batch, and the row, commits in a transaction of its own.
        assert session_local.return_value.__enter__.return_value.commit.call_count == 4

    def test_a_row_an_earlier_attempt_deleted_is_not_deleted_again(self, states):
        states.begin(1, _Kind)

        _, users_crud, _, _, _ = self._run(states, batches=[], row_exists=False)

        users_crud.delete_user.assert_not_called()
        assert states.get(1, _Kind).status == _Status.COMPLETED

    def test_a_deletion_that_is_not_pending_is_skipped(self, states):
        erasers, users_crud, _, _, _ = self._run(states, batches=[])

        erasers.delete_activities.assert_not_called()
        users_crud.delete_user.assert_not_called()

    def test_a_failure_nothing_retries_fails_the_deletion_and_frees_the_claim(self, states):
        states.begin(1, _Kind)

        _, users_crud, photos, _, _ = self._run(states, batches=[], delete_error=RuntimeError("boom"))

        users_crud.delete_user.assert_not_called()
        photos.delete_photo_files.assert_not_called()
        assert states.get(1, _Kind).status == _Status.FAILED
        assert states.begin(1, _Kind) is True

    def test_a_failure_a_worker_will_retry_stays_queued_and_raises(self, states):
        states.begin(1, _Kind)

        with pytest.raises(RuntimeError):
            self._run(states, batches=[], delete_error=RuntimeError("boom"), will_retry=True)

        assert states.get(1, _Kind).status == _Status.QUEUED
        assert states.begin(1, _Kind) is False


class TestStatusAndDeadLetter:
    def test_status_is_not_found_when_none_is_recorded(self, states):
        with pytest.raises(core_exceptions.NotFoundError):
            job_service.get_deletion_status(1, states)

    def test_status_reports_the_recorded_state(self, states):
        states.begin(1, _Kind)

        assert job_service.get_deletion_status(1, states).status == _Status.QUEUED

    def test_a_dead_lettered_deletion_is_failed_and_its_claim_freed(self, states):
        states.begin(1, _Kind)

        job_service.close_dead_lettered_deletion(_payload(), states)

        assert states.get(1, _Kind).status == _Status.FAILED
        assert states.begin(1, _Kind) is True

    def test_a_finished_deletion_is_left_as_it_is(self, states):
        states.begin(1, _Kind)
        states.set_status(1, _Kind, _Status.COMPLETED)

        job_service.close_dead_lettered_deletion(_payload(), states)

        assert states.get(1, _Kind).status == _Status.COMPLETED
