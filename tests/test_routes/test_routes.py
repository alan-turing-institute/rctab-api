# pylint: disable=redefined-outer-name,
import random
from datetime import date, timedelta
from typing import Any, AsyncGenerator, Callable, Coroutine, Optional, Tuple
from uuid import UUID

import pytest
from mypy_extensions import KwArg, VarArg
from rctab_models.models import (
    RoleAssignment,
    SubscriptionState,
    SubscriptionStatus,
    Usage,
)
from sqlalchemy.engine import ResultProxy
from sqlalchemy.engine.base import Engine
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud.accounting_models import (
    allocations,
    approvals,
    persistence,
    refresh_materialised_view,
    subscription,
    subscription_details,
    usage,
    usage_view,
)
from rctab.db import ENGINE
from tests.test_routes import constants


@pytest.fixture(scope="function")
async def test_db() -> AsyncGenerator[AsyncConnection, None]:
    """Connect before & disconnect after each test."""
    conn = await ENGINE.connect()
    yield conn
    await ENGINE.dispose()


async def create_subscription(
    db: AsyncConnection,
    always_on: Optional[bool] = None,
    current_state: Optional[SubscriptionState] = None,
    allocated_amount: Optional[float] = None,
    approved: Optional[Tuple[float, date]] = None,
    spent: Optional[Tuple[float, float]] = None,
    spent_date: Optional[date] = None,
) -> UUID:
    """Convenience function for testing.

    db: a databases Database
    always_on: if None then no row in persistence
    current_state: if None then no row in subscription_details
    allocated_amount: if None then no row in allocations
    (approved_amount, approved_to): if None then no row in approvals
    (normal_cost, amortised_cost): the amount spent thus far
    spent_date: the date the costs were incurred
    """
    # pylint: disable=too-many-arguments, invalid-name

    # We don't guard against subscription_id clash
    subscription_id = UUID(int=random.randint(0, (2**32) - 1))

    await db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(subscription_id),
        ),
    )
    if always_on is not None:
        await db.execute(
            persistence.insert().values(),
            dict(
                admin=str(constants.ADMIN_UUID),
                subscription_id=str(subscription_id),
                always_on=always_on,
            ),
        )

    if current_state is not None:
        await db.execute(
            subscription_details.insert().values(),
            SubscriptionStatus(
                subscription_id=str(subscription_id),
                state=current_state,
                display_name="a subscription",
                role_assignments=(
                    RoleAssignment(
                        role_definition_id="some-role-def-id",
                        role_name="Billing Reader",
                        principal_id="some-principal-id",
                        display_name="SomePrincipal Display Name",
                    ),
                ),
            ).model_dump(),
        )

    if allocated_amount is not None:
        await db.execute(
            allocations.insert().values(),
            dict(
                subscription_id=str(subscription_id),
                admin=str(constants.ADMIN_UUID),
                amount=allocated_amount,
                currency="GBP",
            ),
        )

    if approved is not None:
        await db.execute(
            approvals.insert().values(),
            dict(
                subscription_id=str(subscription_id),
                admin=str(constants.ADMIN_UUID),
                amount=approved[0],
                date_to=approved[1],
                date_from=date.today() - timedelta(days=365),
                currency="GBP",
            ),
        )

    if spent:
        await db.execute(
            usage.insert().values(),
            Usage(
                subscription_id=str(subscription_id),
                id=str(UUID(int=random.randint(0, 2**32 - 1))),
                cost=spent[0],
                amortised_cost=spent[1],
                total_cost=sum(spent),
                invoice_section="",
                date=spent_date if spent_date else date.today(),
            ).model_dump(),
        )
        await refresh_materialised_view(db, usage_view)

    return subscription_id


def make_async_execute(
    connection: Engine,
) -> Callable[[VarArg(Any), KwArg(Any)], Coroutine[Any, Any, ResultProxy]]:
    """We need an async function to patch database.execute() with
    but connection.execute() is synchronous so make a wrapper for it."""

    async def async_execute(*args: Any, **kwargs: Any) -> ResultProxy:
        """An async wrapper around connection.execute()."""
        return connection.execute(*args, **kwargs)  # type: ignore

    return async_execute
