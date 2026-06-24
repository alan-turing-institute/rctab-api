import asyncio
from asyncio import AbstractEventLoop
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud.models import user_rbac
from rctab.db import ENGINE
from tests.test_routes import constants


@pytest.fixture(scope="session")
def event_loop() -> Generator[AbstractEventLoop, None, None]:
    """Overrides pytest's default function-scoped event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_data() -> AsyncGenerator[None, None]:
    # Insert async setup code here
    # Ensure pooled connections created in other test loops are dropped first.
    await ENGINE.dispose()
    conn = await ENGINE.connect()
    try:
        await cleanup_test_data(conn)
        await create_test_user(conn)
        # commit the transaction to ensure the test user is created
        await conn.commit()
        yield
    finally:
        await conn.close()
        await ENGINE.dispose()


async def cleanup_test_data(conn: Any) -> None:
    """Cleans up test data after tests are run."""
    # This function should be called after all tests are done
    await clean_up(conn)
    await conn.execute(
        delete(user_rbac).where(
            user_rbac.c.oid.in_(
                (str(constants.ADMIN_UUID), str(constants.USER_WITHOUT_ACCESS_UUID))
            )
        )
    )


async def create_test_user(
    conn: AsyncConnection,
) -> None:  # pylint: disable=unused-argument
    """Allows plugins and conftest files to perform initial configuration.

    This hook is called for every plugin and initial conftest
    file after command line options have been parsed."""
    await conn.execute(
        insert(user_rbac).values(
            (str(constants.ADMIN_UUID), constants.ADMIN_NAME, True, True)
        )
    )
    await conn.execute(
        insert(user_rbac).values(
            (
                str(constants.USER_WITHOUT_ACCESS_UUID),
                constants.USER_WITHOUT_ACCESS_NAME,
                False,
                False,
            )
        )
    )


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """Called before test process is exited."""
    return


async def clean_up(conn: AsyncConnection) -> None:
    """Deletes data from all accounting tables."""

    for table_name in (
        "status",
        "usage",
        "allocations",
        "approvals",
        "persistence",
        "emails",
        "cost_recovery",
        "finance",
        "finance_history",
        "subscription",
        "cost_recovery_log",
    ):
        await conn.execute(text(f"truncate table accounting.{table_name} cascade"))


@pytest.fixture(autouse=True)
def mock_advisory_locks() -> Generator[None, None, None]:
    """Automatically mock advisory locks for all route tests to prevent blocking."""
    # Mock the advisory lock context managers to be no-ops
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=None)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "rctab.routers.accounting.usage.advisory_lock", return_value=mock_context
        ),
        patch(
            "rctab.routers.accounting.cost_recovery.advisory_lock_nowait",
            return_value=mock_context,
        ),
        patch("rctab.crud.accounting_models.advisory_lock", return_value=mock_context),
    ):
        yield
