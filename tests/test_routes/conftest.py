from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, delete, insert, text
from sqlalchemy.engine import Connection

from rctab.crud.models import DATABASE_URL, user_rbac
from tests.test_routes import constants

engine = create_engine(str(DATABASE_URL))


def pytest_configure(config: Any) -> None:  # pylint: disable=unused-argument
    """Allows plugins and conftest files to perform initial configuration.

    This hook is called for every plugin and initial conftest
    file after command line options have been parsed."""

    with engine.begin() as conn:
        conn.execute(
            insert(user_rbac).values(
                (str(constants.ADMIN_UUID), constants.ADMIN_NAME, True, True)
            )
        )


def pytest_unconfigure(config: Any) -> None:  # pylint: disable=unused-argument
    """Called before test process is exited."""

    with engine.begin() as conn:

        clean_up(conn)

        conn.execute(
            delete(user_rbac).where(user_rbac.c.oid == str(constants.ADMIN_UUID))
        )


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


@pytest.fixture(autouse=True)
def mock_advisory_locks():
    """Automatically mock advisory locks for all route tests to prevent blocking."""
    # Mock the advisory lock context managers to be no-ops
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=None)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "rctab.routers.accounting.usage.advisory_lock", return_value=mock_context
    ), patch(
        "rctab.routers.accounting.cost_recovery.advisory_lock_nowait",
        return_value=mock_context,
    ), patch(
        "rctab.crud.accounting_models.advisory_lock", return_value=mock_context
    ):
        yield
