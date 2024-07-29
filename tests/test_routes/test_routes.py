# pylint: disable=redefined-outer-name,
import random
from datetime import date, timedelta
from typing import Any, AsyncGenerator, Callable, Coroutine, Optional, Tuple
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from mypy_extensions import KwArg, VarArg
from pytest_mock import MockerFixture
from sqlalchemy import and_, func, select
from sqlalchemy.engine import ResultProxy
from sqlalchemy.engine.base import Engine

from rctab.crud.accounting_models import (
    allocations,
    approvals,
    persistence,
    refresh_materialised_view,
    status,
    subscription,
    subscription_details,
    usage,
    usage_view,
)
from rctab.crud.models import database
from rctab.crud.schema import (
    RoleAssignment,
    SubscriptionState,
    SubscriptionStatus,
    Usage,
)
from rctab.routers.accounting.desired_states import refresh_desired_states
from tests.test_routes import constants


@pytest.fixture(scope="function")
async def test_db() -> AsyncGenerator[Database, None]:
    """Connect before & disconnect after each test."""
    await database.connect()
    yield database
    await database.disconnect()


async def create_subscription(
    db: Database,
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
            ).dict(),
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
            ).dict(),
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


@pytest.mark.asyncio
async def test_refresh_desired_states_disable(
    test_db: Database, mocker: MockerFixture
) -> None:
    """Check that refresh_desired_states disables when it should."""
    # pylint: disable=singleton-comparison

    mock_send_email = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    no_approval_sub_id = await create_subscription(
        test_db, always_on=False, current_state=SubscriptionState("Enabled")
    )

    expired_yesterday_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() - timedelta(days=1)),
    )

    over_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
        spent=(101.0, 0),
    )

    over_time_and_over_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() - timedelta(days=1)),
        spent=(101.0, 0),
    )

    not_always_on_sub_id = await create_subscription(test_db, always_on=None)

    await refresh_desired_states(
        constants.ADMIN_UUID,
        [
            no_approval_sub_id,
            expired_yesterday_sub_id,
            over_budget_sub_id,
            not_always_on_sub_id,
            over_time_and_over_budget_sub_id,
        ],
    )

    rows = await test_db.fetch_all(select([status]).order_by(status.c.subscription_id))
    disabled_subscriptions = [
        (row["subscription_id"], row["reason"])
        for row in rows
        if row["active"] is False
    ]
    disabled_subscriptions_set = set(disabled_subscriptions)

    # The subscription_ids are generated at random so we can't use list comparisons
    assert len(disabled_subscriptions) == len(disabled_subscriptions_set)
    assert disabled_subscriptions_set == {
        (no_approval_sub_id, "EXPIRED"),
        (expired_yesterday_sub_id, "EXPIRED"),
        (over_budget_sub_id, "OVER_BUDGET"),
        (not_always_on_sub_id, "EXPIRED"),
        (over_time_and_over_budget_sub_id, "OVER_BUDGET_AND_EXPIRED"),
    }


@pytest.mark.asyncio
async def test_refresh_desired_states_enable(
    test_db: Database, mocker: MockerFixture
) -> None:
    """Check that refresh_desired_states enables when it should."""
    # pylint: disable=singleton-comparison

    mock_send_email = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    # Allocations default to 0, not NULL, so we don't expect this
    # sub to be disabled since 0 usage is not > 0 allocated budget
    no_allocation_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
    )

    always_on_sub_id = await create_subscription(
        test_db,
        always_on=True,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today() - timedelta(days=1)),
        spent=(101.0, 0),
    )

    # E.g. we have just allocated more budget
    currently_disabled_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(200.0, date.today() + timedelta(days=1)),
        allocated_amount=200.0,
        spent=(101.0, 0),
    )
    await test_db.execute(
        status.insert().values(),
        dict(
            subscription_id=str(currently_disabled_sub_id),
            admin=str(constants.ADMIN_UUID),
            active=False,
        ),
    )

    # Q) Can we presume that status, persistence, approvals and allocations
    #    are made during subscription creation?
    await refresh_desired_states(
        constants.ADMIN_UUID,
        [always_on_sub_id, no_allocation_sub_id, currently_disabled_sub_id],
    )

    rows = await test_db.fetch_all(select([status]).order_by(status.c.subscription_id))

    enabled_subscriptions = [
        row["subscription_id"] for row in rows if row["active"] is True
    ]
    enabled_subscriptions_set = set(enabled_subscriptions)

    # The subscription_ids are generated at random so we can't use list comparisons
    assert len(enabled_subscriptions) == len(enabled_subscriptions_set)
    assert enabled_subscriptions_set == {
        always_on_sub_id,
        no_allocation_sub_id,
        currently_disabled_sub_id,
    }


@pytest.mark.asyncio
async def test_refresh_desired_states_doesnt_duplicate(
    test_db: Database, mocker: MockerFixture
) -> None:
    """Check that refresh_desired_states only inserts when necessary."""
    # pylint: disable=singleton-comparison

    always_on_sub_id = await create_subscription(
        test_db,
        always_on=True,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today() - timedelta(days=1)),
        spent=(101.0, 0),
    )
    await test_db.execute(
        status.insert().values(),
        dict(
            subscription_id=str(always_on_sub_id),
            admin=str(constants.ADMIN_UUID),
            active=True,
        ),
    )

    # We want this subscription to stay disabled.
    over_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
        spent=(101.0, 0),
    )
    await test_db.execute(
        status.insert().values(),
        dict(
            subscription_id=str(over_budget_sub_id),
            admin=str(constants.ADMIN_UUID),
            active=False,
        ),
    )

    mock_send_email = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    # Note: here we check that, by default, refresh_desired_states()
    # will refresh all subscriptions
    await refresh_desired_states(
        constants.ADMIN_UUID,
    )

    latest_status_id = (
        select([status.c.subscription_id, func.max(status.c.id).label("max_id")])
        .group_by(status.c.subscription_id)
        .alias()
    )

    latest_status = select([status.c.subscription_id, status.c.active]).select_from(
        status.join(
            latest_status_id,
            and_(
                status.c.subscription_id == latest_status_id.c.subscription_id,
                status.c.id == latest_status_id.c.max_id,
            ),
        )
    )

    rows = await test_db.fetch_all(latest_status)
    enabled_subscriptions = [
        row["subscription_id"] for row in rows if row["active"] is True
    ]
    assert enabled_subscriptions == [
        always_on_sub_id,
    ]

    disabled_subscriptions = [
        row["subscription_id"] for row in rows if row["active"] is False
    ]
    assert disabled_subscriptions == [
        over_budget_sub_id,
    ]
