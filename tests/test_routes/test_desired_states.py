from datetime import date, timedelta
from typing import Tuple
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from rctab_models.models import BillingStatus, DesiredState, SubscriptionState
from sqlalchemy import select

from rctab.crud.accounting_models import refresh_materialised_view
from rctab.crud.accounting_models import status as status_table
from rctab.crud.accounting_models import usage as usage_table
from rctab.crud.accounting_models import usage_view
from rctab.crud.models import database
from rctab.routers.accounting import desired_states
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import PREFIX, get_subscriptions_summary
from tests.test_routes import api_calls, constants
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
    test_db: Database,
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = await test_db.fetch_all(select(status_table))
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.EXPIRED

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=expired_sub_id, execute=False)
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == usage  # type: ignore
    assert sub_summary["allocated"] == usage  # type: ignore


@pytest.mark.asyncio
async def test_desired_states_budget_adjustment_approved_ignored(
    test_db: Database,
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = await test_db.fetch_all(select(status_table))
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=expired_sub_id, execute=False)
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == usage  # type: ignore
    assert sub_summary["allocated"] == allocated  # type: ignore


@pytest.mark.asyncio
async def test_desired_states_budget_adjustment_ignored(
    test_db: Database,
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = await test_db.fetch_all(select(status_table))
    row_dicts = [dict(row) for row in desired_state_rows]

    # The subscription expired today
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=expired_sub_id, execute=False)
    )

    # approved and allocation should match usage
    assert sub_summary["approved"] == approved  # type: ignore
    assert sub_summary["allocated"] == allocated  # type: ignore


def test_desired_states_disabled(
    app_with_signed_status_and_controller_tokens: Tuple[FastAPI, str, str],
    mocker: MockerFixture,
) -> None:
    (
        auth_app,
        status_token,
        controller_token,
    ) = app_with_signed_status_and_controller_tokens

    sub_ids = [UUID(int=0), UUID(int=1), UUID(int=2)]
    with TestClient(auth_app) as client:
        mock_send_emails = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
        )

        # The first subscription has active==True and the second
        # has no subscription_details row, so we only expect the third to be returned

        for sub_id in sub_ids:
            api_calls.create_subscription(
                client, subscription_id=sub_id
            ).raise_for_status()

        # This subscription has no approved_to date so should be disabled
        # for being expired
        api_calls.create_subscription_detail(
            client,
            status_token,
            subscription_id=UUID(int=2),
            state=SubscriptionState("Enabled"),
        ).raise_for_status()

        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.desired_states.refresh_desired_states",
            mock_refresh,
        )

        response = client.get(
            PREFIX + "/desired-states",
            headers={"authorization": "Bearer " + controller_token},
        )

        # Getting the desired states should have the side effect of
        # refreshing the desired states
        mock_refresh.assert_called_once_with(UUID(desired_states.ADMIN_OID))

        assert response.status_code == 200

        expected = [
            DesiredState(
                subscription_id=str(UUID(int=2)),
                desired_state=SubscriptionState("Disabled"),
            )
        ]
        actual = [DesiredState(**x) for x in response.json()]
        assert actual == expected


def test_desired_states_enabled(
    app_with_signed_status_and_controller_tokens: Tuple[FastAPI, str, str],
    mocker: MockerFixture,
) -> None:
    (
        auth_app,
        status_token,
        controller_token,
    ) = app_with_signed_status_and_controller_tokens

    with TestClient(auth_app) as client:
        mock_send_emails = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
        )

        expected = []

        # Both of these are disabled but should be enabled
        for subscription_id, subscription_state in [
            (UUID(int=4), SubscriptionState("Disabled")),
            (UUID(int=5), SubscriptionState("Expired")),
            (UUID(int=6), SubscriptionState("Warned")),
        ]:
            api_calls.create_subscription(
                client, subscription_id=subscription_id
            ).raise_for_status()

            api_calls.create_approval(
                client,
                subscription_id=subscription_id,
                amount=100,
                date_from=date_from,
                date_to=date_to,
                ticket=TICKET,
                allocate=True,
                currency="GBP",
            ).raise_for_status()

            api_calls.create_subscription_detail(
                client,
                token=status_token,
                subscription_id=subscription_id,
                state=subscription_state,
            ).raise_for_status()

            response = client.get(
                PREFIX + "/desired-states",
                headers={"authorization": "Bearer " + controller_token},
            )

            assert response.status_code == 200

            expected.append(
                DesiredState(
                    subscription_id=subscription_id,
                    desired_state=SubscriptionState("Enabled"),
                )
            )

        actual = [DesiredState(**x) for x in response.json()]
        assert len(actual) == len(expected)
        assert set(actual) == set(expected)


@pytest.mark.asyncio
async def test_refresh_sends_disabled_emails(
    test_db: Database, mocker: MockerFixture
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

    await refresh_desired_states(constants.ADMIN_UUID, [over_budget_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        database,
        over_budget_sub_id,
        "will_be_disabled.html",
        "We will turn off your Azure subscription:",
        "subscription disabled",
        {"reason": BillingStatus.EXPIRED},
    )


@pytest.mark.asyncio
async def test_refresh_sends_enabled_emails(
    test_db: Database, mocker: MockerFixture
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

    await refresh_desired_states(constants.ADMIN_UUID, [within_budget_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        database,
        within_budget_sub_id,
        "will_be_enabled.html",
        "We will turn on your Azure subscription:",
        "subscription enabled",
        {},
    )


@pytest.mark.asyncio
async def test_refresh_reason_changes(test_db: Database, mocker: MockerFixture) -> None:
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    # We should email each disabled subscription
    mock_send_emails.assert_called_with(
        database,
        expired_sub_id,
        "will_be_disabled.html",
        "We will turn off your Azure subscription:",
        "subscription disabled",
        {"reason": BillingStatus.EXPIRED},
    )
    assert mock_send_emails.call_count == 1

    desired_state_rows = await test_db.fetch_all(select(status_table))
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    # If the reason for disabling changes, we don't want to send an email
    assert mock_send_emails.call_count == 1

    row_dicts = [
        dict(row)
        for row in await test_db.fetch_all(
            select(status_table).order_by(status_table.c.time_created)
        )
    ]

    # We should have a new row showing that there are two reasons
    assert len(row_dicts) == 2
    assert row_dicts[1]["reason"] == BillingStatus.OVER_BUDGET_AND_EXPIRED


@pytest.mark.asyncio
async def test_refresh_reason_stays_the_same(
    test_db: Database, mocker: MockerFixture
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

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = await test_db.fetch_all(select(status_table))
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1
    assert row_dicts[0]["reason"] == BillingStatus.EXPIRED

    await refresh_desired_states(constants.ADMIN_UUID, [expired_sub_id])

    desired_state_rows = await test_db.fetch_all(
        select(status_table).order_by(status_table.c.time_created)
    )
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1


@pytest.mark.asyncio
async def test_small_tolerance(test_db: Database, mocker: MockerFixture) -> None:
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

    await refresh_desired_states(constants.ADMIN_UUID, [close_to_budget_sub_id])

    desired_state_rows = await test_db.fetch_all(
        select(status_table).where(status_table.c.reason == None)
    )
    row_dicts = [dict(row) for row in desired_state_rows]
    assert len(row_dicts) == 1
