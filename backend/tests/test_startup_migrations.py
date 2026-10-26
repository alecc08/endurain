"""Every startup migration step runs while one lock is held, so replicas migrate one at a time."""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

import core.migrations as core_migrations


def test_every_step_runs_while_the_lock_is_held():
    order: list[str] = []

    @contextmanager
    def lock():
        order.append("lock")
        try:
            yield
        finally:
            order.append("unlock")

    with (
        patch.object(core_migrations, "migration_lock", lock),
        patch.object(core_migrations, "run_alembic_upgrade", lambda: order.append("alembic")),
        patch.object(core_migrations, "bootstrap_substrate_schema", lambda: order.append("substrate")),
        patch.object(core_migrations, "check_migrations", AsyncMock(side_effect=lambda: order.append("data"))),
    ):
        asyncio.run(core_migrations.migrate_schema_and_data())

    assert order == ["lock", "alembic", "substrate", "data", "unlock"]


def test_the_lock_is_released_when_a_step_fails():
    order: list[str] = []

    @contextmanager
    def lock():
        try:
            yield
        finally:
            order.append("unlock")

    def fail() -> None:
        raise RuntimeError("boom")

    with (
        patch.object(core_migrations, "migration_lock", lock),
        patch.object(core_migrations, "run_alembic_upgrade", fail),
        pytest.raises(RuntimeError),
    ):
        asyncio.run(core_migrations.migrate_schema_and_data())

    assert order == ["unlock"]
