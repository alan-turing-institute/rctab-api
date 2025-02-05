from datetime import date, timedelta
from uuid import UUID

import pytest
from databases import Database
from pytest_mock import MockerFixture
from rctab_models.models import SubscriptionState
from sqlalchemy import select

from rctab.crud.accounting_models import subscription_details
from rctab.routers.accounting.abolishment import (
    adjust_budgets_to_zero,
    get_inactive_subs,
    send_abolishment_email,
    set_abolished_flag,
)
from rctab.routers.accounting.routes import get_subscriptions_summary
from tests.test_routes import constants
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)


async def create_expired_subscription(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> UUID:
    """
    Creates a subscription which has been inactive for more than 90 days.
    """

    date_91d_ago = date.today() - timedelta(days=91)

    approved = 100
    allocated = 80
    usage = 110

    expired_sub_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        approved=(approved, date_91d_ago),
        allocated_amount=allocated,
        spent=(usage, 0),
        spent_date=date_91d_ago,
    )

    await test_db.execute(
        subscription_details.update()
        .where(subscription_details.c.subscription_id == expired_sub_id)
        .values(time_created=date_91d_ago)
    )

    return expired_sub_id


@pytest.mark.asyncio
async def test_abolishment(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: MockerFixture,
) -> None:

    # Testing get_inactive_subs
    expired_sub_id = await create_expired_subscription(test_db)

    inactive_subs = await get_inactive_subs()

    assert inactive_subs
    assert len(inactive_subs) == 1
    assert inactive_subs[0] == expired_sub_id

    # Testing adjust_budgets_to_zero
    adjustments = await adjust_budgets_to_zero(constants.ADMIN_UUID, inactive_subs)

    assert adjustments
    assert len(adjustments) == 1
    assert adjustments[0]["subscription_id"] == expired_sub_id
    assert adjustments[0]["allocation"] == 30.0
    assert adjustments[0]["approval"] == 10.0

    sub_query = get_subscriptions_summary(execute=False).alias()
    summary_qr = select(sub_query).where(sub_query.c.subscription_id == expired_sub_id)
    summary = await test_db.fetch_all(summary_qr)

    assert summary
    assert len(summary) == 1
    for row in summary:
        assert row["total_cost"] == row["allocated"]
        assert row["total_cost"] == row["approved"]
        assert row["abolished"] is False

    # Testing set_abolished_flag
    await set_abolished_flag(inactive_subs)

    sub_query = get_subscriptions_summary(execute=False).alias()
    summary_qr = select(sub_query).where(sub_query.c.subscription_id == expired_sub_id)
    summary = await test_db.fetch_all(summary_qr)

    assert summary
    assert len(summary) == 1
    for row in summary:
        assert row["abolished"] is True

    # Testing send_emails
    email_recipients = ["test@test.com"]
    mock_send_email = mocker.patch(
        "rctab.routers.accounting.abolishment.send_with_sendgrid"
    )
    mock_send_email.return_value = 200

    await send_abolishment_email(email_recipients, adjustments)

    mock_send_email.assert_called_with(
        "Abolishment of subscriptions",
        "abolishment.html",
        {
            "abolishments": [
                {
                    "subscription_id": expired_sub_id,
                    "name": "a subscription",
                    "allocation": adjustments[0]["allocation"],
                    "approval": adjustments[0]["approval"],
                }
            ]
        },
        email_recipients,
    )


@pytest.mark.asyncio
async def test_abolishment_no_allocation(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:

    sub_id = await create_subscription(test_db, spent=(1.0, 1.0))

    adjustments = await adjust_budgets_to_zero(constants.ADMIN_UUID, [sub_id])

    assert len(adjustments) == 1
