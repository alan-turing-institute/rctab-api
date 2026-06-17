from typing import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.db import ENGINE


@pytest_asyncio.fixture(scope="function")
async def no_rollback_test_db() -> AsyncGenerator[AsyncConnection, None]:
    """Connect before & disconnect after each test.

    For a small number of tests, we want to test that calc_cost_recovery's
    internal savepoint (begin_nested) commits or rolls back correctly. This
    fixture provides a real outer transaction to wrap that savepoint in.
    The outer transaction is always rolled back after the test.
    """
    async with ENGINE.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
