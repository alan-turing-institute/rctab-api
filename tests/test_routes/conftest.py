from typing import Any

from sqlalchemy import create_engine, delete, insert, text
from sqlalchemy.engine import Connection

from rctab.crud.models import DATABASE_URL, user_rbac
from tests.test_routes import constants

engine = create_engine(DATABASE_URL)


def pytest_configure(config: Any) -> None:  # pylint: disable=unused-argument
    """Allows plugins and conftest files to perform initial configuration.

    This hook is called for every plugin and initial conftest
    file after command line options have been parsed."""

    conn = engine.connect()

    conn.execute(
        insert(user_rbac).values(
            (str(constants.ADMIN_UUID), constants.ADMIN_NAME, True, True)
        )
    )

    conn.close()


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """Called before test process is exited."""

    conn = engine.connect()

    clean_up(conn)

    conn.execute(delete(user_rbac).where(user_rbac.c.oid == str(constants.ADMIN_UUID)))

    conn.close()


def clean_up(conn: Connection) -> None:
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
        conn.execute(text(f"truncate table accounting.{table_name} cascade"))
