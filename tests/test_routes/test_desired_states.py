from datetime import date, timedelta
from unittest.mock import ANY, AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture
from rctab_models.models import BillingStatus, DesiredState, SubscriptionState
from sqlalchemy import select
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud.accounting_models import refresh_materialised_view
from rctab.crud.accounting_models import status as status_table
from rctab.crud.accounting_models import usage as usage_table
from rctab.crud.accounting_models import usage_view
from rctab.db import get_async_connection
from rctab.routers.accounting import desired_states
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import PREFIX, get_subscriptions_summary
from rctab.settings import Settings
from tests.test_routes import constants
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)

# pylint: disable=redefined-outer-name

date_from = date.today()
date_to = date.today() + timedelta(days=30)
TICKET = "T001-12"


@pytest.mark.asyncio
async def test_desired_states_budget_adjustment_applied(
    test_db: AsyncConnection,
    mocker: MockerFixture,
) -> None:
    approved = 100
    allocated = 80
    usage = 50

    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(approved, date.today()),
        allocated_amount=allocated,
        spent=(usage, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = (await test_db.execute(select(status_table))).mappings().all()
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.EXPIRED

    sub_summary = (
        (await test_db.execute(get_subscriptions_summary(sub_id=expired_sub_id)))
        .mappings()
        .first()
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == usage  # type: ignore
    assert sub_summary["allocated"] == usage  # type: ignore


@pytest.mark.asyncio
async def test_desired_states_budget_adjustment_approved_ignored(
    test_db: AsyncConnection,
    mocker: MockerFixture,
) -> None:
    approved = 100
    allocated = 80
    usage = 90

    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(approved, date.today()),
        allocated_amount=allocated,
        spent=(usage, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = (await test_db.execute(select(status_table))).mappings().all()
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED

    sub_summary = (
        (await test_db.execute(get_subscriptions_summary(sub_id=expired_sub_id)))
        .mappings()
        .first()
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == usage  # type: ignore
    assert sub_summary["allocated"] == allocated  # type: ignore


@pytest.mark.asyncio
async def test_desired_states_budget_adjustment_ignored(
    test_db: AsyncConnection,
    mocker: MockerFixture,
) -> None:
    approved = 100
    allocated = 80

    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(approved, date.today()),
        allocated_amount=allocated,
        spent=(110, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = (await test_db.execute(select(status_table))).mappings().all()
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED

    sub_summary = (
        (await test_db.execute(get_subscriptions_summary(sub_id=expired_sub_id)))
        .mappings()
        .first()
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == approved  # type: ignore
    assert sub_summary["allocated"] == allocated  # type: ignore


@pytest.mark.asyncio
async def test_desired_states_disabled(
    auth_app: FastAPI,
    test_db: AsyncConnection,
    mocker: MockerFixture,
) -> None:
    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )

    sub_unchanged = await create_subscription(
        test_db,
        always_on=True,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
    )
    _ = sub_unchanged
    await create_subscription(test_db)
    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
    )
    await test_db.execute(
        status_table.insert(),
        {
            "subscription_id": expired_sub_id,
            "admin": constants.ADMIN_UUID,
            "active": False,
            "reason": BillingStatus.EXPIRED,
        },
    )

    async def _get_async_connection_override() -> AsyncConnection:
        return test_db

    mock_refresh = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.desired_states.refresh_desired_states", mock_refresh
    )

    auth_app.dependency_overrides[get_async_connection] = _get_async_connection_override

    async with AsyncClient(
        transport=ASGITransport(app=auth_app), base_url="http://test"
    ) as client:
        response = await client.get(PREFIX + "/desired-states")

    assert response.status_code == 200
    mock_refresh.assert_called_once_with(ANY, UUID(desired_states.ADMIN_OID))
    expected = [
        DesiredState(
            subscription_id=expired_sub_id,
            desired_state=SubscriptionState("Disabled"),
        )
    ]
    actual = [DesiredState(**x) for x in response.json()]
    assert actual == expected


@pytest.mark.asyncio
async def test_desired_states_enabled(
    auth_app: FastAPI,
    test_db: AsyncConnection,
    mocker: MockerFixture,
) -> None:
    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        return_value=Settings(ignore_whitelist=True),
    )

    expected = []

    for subscription_state in [
        SubscriptionState("Disabled"),
        SubscriptionState("Expired"),
        SubscriptionState("Warned"),
    ]:
        sub_id = await create_subscription(
            test_db,
            always_on=False,
            current_state=subscription_state,
            approved=(100.0, date.today() + timedelta(days=1)),
        )
        expected.append(
            DesiredState(
                subscription_id=sub_id,
                desired_state=SubscriptionState("Enabled"),
            )
        )
        await test_db.execute(
            status_table.insert(),
            {
                "subscription_id": sub_id,
                "admin": constants.ADMIN_UUID,
                "active": True,
            },
        )

    async def _get_async_connection_override() -> AsyncConnection:
        return test_db

    mock_refresh = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.desired_states.refresh_desired_states", mock_refresh
    )

    auth_app.dependency_overrides[get_async_connection] = _get_async_connection_override

    async with AsyncClient(
        transport=ASGITransport(app=auth_app), base_url="http://test"
    ) as client:
        response = await client.get(PREFIX + "/desired-states")

    assert response.status_code == 200
    mock_refresh.assert_called_once_with(ANY, UUID(desired_states.ADMIN_OID))
    actual = [DesiredState(**x) for x in response.json()]
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


@pytest.mark.asyncio
async def test_refresh_sends_disabled_emails(
    test_db: AsyncConnection, mocker: MockerFixture
) -> None:
    over_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() + timedelta(days=-1)),
        allocated_amount=100,
        spent=(1.0, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [over_budget_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        ANY,
        over_budget_sub_id,
        "will_be_disabled.html",
        "We will turn off your Azure subscription:",
        "subscription disabled",
        {"reason": BillingStatus.EXPIRED},
    )


@pytest.mark.asyncio
async def test_refresh_sends_enabled_emails(
    test_db: AsyncConnection, mocker: MockerFixture
) -> None:
    within_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
        allocated_amount=100,
        spent=(99.0, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [within_budget_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        ANY,
        within_budget_sub_id,
        "will_be_enabled.html",
        "We will turn on your Azure subscription:",
        "subscription enabled",
        {},
    )


@pytest.mark.asyncio
async def test_refresh_reason_changes(
    test_db: AsyncConnection, mocker: MockerFixture
) -> None:
    """We should update the reason for disabling if that reason changes."""
    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today()),
        allocated_amount=100,
        spent=(0.0, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        ANY,
        expired_sub_id,
        "will_be_disabled.html",
        "We will turn off your Azure subscription:",
        "subscription disabled",
        {"reason": BillingStatus.EXPIRED},
    )
    assert mock_send_emails.call_count == 1

    desired_state_rows = (await test_db.execute(select(status_table))).mappings().all()
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.EXPIRED

    await test_db.execute(
        usage_table.insert().values(),
        dict(
            subscription_id=str(expired_sub_id),
            id=str(UUID(int=7)),
            total_cost=101,
            invoice_section="",
            date=date.today(),
        ),
    )
    await refresh_materialised_view(test_db, usage_view)

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    # If the reason for disabling changes, we don't want to send an email
    assert mock_send_emails.call_count == 1

    row_dicts = [
        dict(row)
        for row in (
            await test_db.execute(
                select(status_table).order_by(status_table.c.time_created)
            )
        )
        .mappings()
        .all()
    ]

    # We should have a new row showing that there are two reasons
    assert len(row_dicts) == 2
    assert row_dicts[1]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED


@pytest.mark.asyncio
async def test_refresh_reason_stays_the_same(
    test_db: AsyncConnection, mocker: MockerFixture
) -> None:
    """Multiple calls shouldn't insert extra rows."""

    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(100.0, date.today() - timedelta(days=1)),
        allocated_amount=100,
        spent=(0.0, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = (await test_db.execute(select(status_table))).mappings().all()
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.EXPIRED

    await refresh_desired_states(test_db, constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = (
        (
            await test_db.execute(
                select(status_table).order_by(status_table.c.time_created)
            )
        )
        .mappings()
        .all()
    )
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1


@pytest.mark.asyncio
async def test_small_tolerance(test_db: AsyncConnection, mocker: MockerFixture) -> None:
    """Check that we allow subscriptions to go 0.001p over budget."""
    # pylint: disable=singleton-comparison
    close_to_budget_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        approved=(100.0, date.today() + timedelta(days=1)),
        allocated_amount=100,
        spent=(100.001, 0),
    )

    mock_send_emails = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
    )

    await refresh_desired_states(
        test_db, constants.ADMIN_UUID, [close_to_budget_sub_id]
    )

    desired_state_rows = (
        (
            await test_db.execute(
                select(status_table).where(status_table.c.reason == None)
            )
        )
        .mappings()
        .all()
    )
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1
