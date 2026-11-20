"""Tests for PostgreSQL advisory locks, using real database connections."""

import asyncio
from datetime import date
from typing import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import HTTPException
from rctab_models.models import AllUsage
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.constants import ADMIN_OID
from rctab.crud.locks import (
    LockNames,
    _string_to_lock_id,
    advisory_xact_lock,
    try_advisory_xact_lock,
)
from rctab.db import ENGINE
from rctab.routers.accounting.cost_recovery import (
    CostRecoveryMonth,
    calc_cost_recovery,
)
from rctab.routers.accounting.usage import post_usage
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import


@pytest_asyncio.fixture
async def other_db() -> AsyncGenerator[AsyncConnection, None]:
    """A second connection, standing in for a concurrent request."""
    conn = await ENGINE.connect()
    transaction = await conn.begin()
    try:
        yield conn
    finally:
        if transaction.is_active:
            await transaction.rollback()
        await conn.close()


def test_lock_ids() -> None:
    """Lock IDs are stable, distinct and fit in a PostgreSQL bigint."""
    assert _string_to_lock_id("a") == _string_to_lock_id("a")
    assert _string_to_lock_id("a") != _string_to_lock_id("b")
    for name in LockNames:
        assert -(2**63) <= _string_to_lock_id(name) < 2**63


@pytest.mark.asyncio
async def test_try_lock_held_until_transaction_ends(
    test_db: AsyncConnection,  # pylint: disable=redefined-outer-name
    other_db: AsyncConnection,  # pylint: disable=redefined-outer-name
) -> None:
    """A second transaction can't take the lock until the first one ends."""
    await try_advisory_xact_lock(test_db, "test_lock")

    with pytest.raises(HTTPException) as exc_info:
        await try_advisory_xact_lock(other_db, "test_lock")
    assert exc_info.value.status_code == 409

    # Other locks are unaffected.
    await try_advisory_xact_lock(other_db, "another_test_lock")

    # The same transaction can take the lock again.
    await try_advisory_xact_lock(test_db, "test_lock")

    await test_db.commit()
    await try_advisory_xact_lock(other_db, "test_lock")


@pytest.mark.asyncio
async def test_blocking_lock_waits_for_transaction_to_end(
    test_db: AsyncConnection,  # pylint: disable=redefined-outer-name
    other_db: AsyncConnection,  # pylint: disable=redefined-outer-name
) -> None:
    """A blocking lock waits until the holding transaction rolls back."""
    await advisory_xact_lock(test_db, "test_lock")

    waiter = asyncio.create_task(advisory_xact_lock(other_db, "test_lock"))
    await asyncio.sleep(0.5)
    assert not waiter.done()

    await test_db.rollback()
    await asyncio.wait_for(waiter, timeout=5)


@pytest.mark.asyncio
async def test_cost_recovery_rejects_concurrent_calculation(
    test_db: AsyncConnection,  # pylint: disable=redefined-outer-name
    other_db: AsyncConnection,  # pylint: disable=redefined-outer-name
) -> None:
    """Cost recovery returns 409 if another request is calculating it."""
    await try_advisory_xact_lock(other_db, LockNames.COST_RECOVERY)

    with pytest.raises(HTTPException) as exc_info:
        await calc_cost_recovery(
            CostRecoveryMonth(first_day=date(2024, 1, 1)),
            commit_transaction=True,
            admin=UUID(ADMIN_OID),
            conn=test_db,
        )
    assert exc_info.value.status_code == 409

    # A dry run doesn't need the lock.
    await calc_cost_recovery(
        CostRecoveryMonth(first_day=date(2024, 1, 1)),
        commit_transaction=False,
        admin=UUID(ADMIN_OID),
        conn=test_db,
    )


@pytest.mark.asyncio
async def test_post_usage_holds_lock_until_commit(
    test_db: AsyncConnection,  # pylint: disable=redefined-outer-name
    other_db: AsyncConnection,  # pylint: disable=redefined-outer-name
) -> None:
    """The usage upload lock is still held after the route returns."""
    await post_usage(
        AllUsage(usage_list=[], start_date="2024-04-01", end_date="2024-04-01"),
        {"mock": "authentication"},
        test_db,
    )

    with pytest.raises(HTTPException):
        await try_advisory_xact_lock(other_db, LockNames.USAGE_UPLOAD)
