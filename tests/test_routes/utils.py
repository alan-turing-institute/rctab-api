from typing import AsyncGenerator

import pytest
from databases import Database

from rctab.settings import get_settings


@pytest.fixture(scope="function")
async def no_rollback_test_db() -> AsyncGenerator[Database, None]:
    """Connect before & disconnect after each test."""

    # For a small number of tests, we want to ensure the same
    # rollback behaviour as on the live db as we are specifically
    # testing that transactions and rollbacks are handled well.
    database = Database(str(get_settings().postgres_dsn), force_rollback=False)

    await database.connect()
    yield database
    await clean_up(database)
    await database.disconnect()


async def clean_up(conn: Database) -> None:
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
        await conn.execute(f"delete from accounting.{table_name}")
