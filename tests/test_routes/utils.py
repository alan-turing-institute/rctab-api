# from asyncio import sleep
from typing import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio.engine import AsyncConnection
from sqlalchemy.sql.expression import text

from rctab.db import ENGINE

# from rctab.settings import get_settings


@pytest.fixture(scope="function")
async def no_rollback_test_db() -> AsyncGenerator[AsyncConnection, None]:
    """Connect before & disconnect after each test."""

    # For a small number of tests, we want to ensure the same
    # rollback behaviour as on the live db as we are specifically
    # testing that transactions and rollbacks are handled well.
    # database = Database(str(get_settings().postgres_dsn), force_rollback=False)

    # If you want to use the database fixture, uncomment the line below
    print("CONNECTING...", flush=True)
    async with ENGINE.connect() as conn:
        print("TRANSACTION...", flush=True)
        # await conn.commit()
        trans = await conn.begin()
        try:
            yield conn
        finally:
            print("ROLLBACK...", flush=True)
            await trans.rollback()
        print("CLEANUP...", flush=True)
        await clean_up(conn)
        await conn.commit()
    return
    # await database.connect()
    # print("CONNECTING...", flush=True)
    # conn = await ENGINE.connect()
    # print("CONNECTED...", flush=True)
    # yield conn
    # print("CLEANING UP...", flush=True)
    # await clean_up(conn)
    # print("CLEANED UP...", flush=True)
    # await sleep(1)


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
        # print(f"Cleaning up table: {table_name}", flush=True)
        await conn.execute(text(f"delete from accounting.{table_name}"))
