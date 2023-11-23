import random
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from pytest_mock import MockerFixture

from rctab.constants import EMAIL_TYPE_SUMMARY
from rctab.crud.accounting_models import emails, failed_emails, subscription
from rctab.daily_routine_tasks import (
    get_timestamp_last_summary_email,
    send_summary_email,
)
from rctab.routers.accounting.send_emails import MissingEmailParamsError
from tests.test_routes import constants
from tests.test_routes.test_routes import (  # pylint: disable=unused-import # noqa
    create_subscription,
    test_db,
)


@pytest.mark.asyncio
async def test_get_timestamp_last_summary_email(
    test_db: Database,  # pylint: disable=redefined-outer-name  # noqa
) -> None:
    test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(test_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )
    time_created = datetime.now(timezone.utc) - timedelta(seconds=10)
    time_last_summary = await get_timestamp_last_summary_email()
    assert not time_last_summary
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            status=1,  # don't know what status means in this context or what possible values are
            type=EMAIL_TYPE_SUMMARY,
            recipients="Some happy email recipient",
            time_created=time_created,
        ),
    )

    time_last_summary = await get_timestamp_last_summary_email()
    assert time_last_summary == time_created


@pytest.mark.asyncio
async def test_send_summary_email(
    mocker: MockerFixture,
    test_db: Database,  # pylint: disable=redefined-outer-name  # noqa
) -> None:
    # pylint: disable=unused-argument
    mock_prepare = AsyncMock()
    mock_prepare.return_value = {"mock new subs": "return_value"}
    mocker.patch("rctab.daily_routine_tasks.prepare_summary_email", mock_prepare)

    email_recipients = ["test@test.com"]

    mock_send = mocker.patch("rctab.daily_routine_tasks.send_with_sendgrid")

    await send_summary_email(email_recipients)

    mock_send.assert_called_with(
        "Daily summary",
        "daily_summary.html",
        {"mock new subs": "return_value"},
        email_recipients,
    )


@pytest.mark.asyncio
async def test_send_summary_email_missing_params(
    mocker: MockerFixture,
    test_db: Database,  # pylint: disable=redefined-outer-name  # noqa
) -> None:
    # pylint: disable=unused-argument
    mock_prepare = AsyncMock()
    mock_prepare.return_value = {"mock new subs": "return_value"}
    mocker.patch("rctab.daily_routine_tasks.prepare_summary_email", mock_prepare)

    mock_send = mocker.patch("rctab.daily_routine_tasks.send_with_sendgrid")
    email_recipients = ["me@my.org", "they@their.org"]
    mock_send.side_effect = MissingEmailParamsError(
        subject="the_subject",
        recipients=email_recipients,
        from_email="the_email_address",
        message="the_message",
    )

    await send_summary_email(email_recipients)

    row = await test_db.fetch_one(failed_emails.select())

    assert row is not None
    assert row["type"] == "Daily summary"
    assert row["subject"] == "the_subject"
    assert row["recipients"] == "me@my.org;they@their.org"
    assert row["from_email"] == "the_email_address"
    assert row["message"] == "the_message"
