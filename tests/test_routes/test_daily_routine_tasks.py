import random
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from pytest_mock import MockerFixture
from sqlalchemy import insert

from rctab.constants import EMAIL_TYPE_SUMMARY
from rctab.crud.accounting_models import emails, failed_emails, subscription
from rctab.daily_routine_tasks import (
    calc_how_long_to_sleep_for,
    get_timestamp_last_summary_email,
    routine_tasks,
    send_summary_email,
)
from rctab.routers.accounting.send_emails import MissingEmailParamsError
from tests.test_routes import constants
from tests.test_routes.test_abolishment import create_expired_subscription
from tests.test_routes.test_routes import (  # pylint: disable=unused-import # noqa
    create_subscription,
    test_db,
)


@pytest.mark.asyncio
async def test_daily_task_loop(
    test_db: Database,  # pylint: disable=redefined-outer-name  # noqa
    mocker: MockerFixture,
) -> None:
    class BreakLoopException(Exception):
        pass

    # The summary email background task exists immediately if there are no recipients
    mock_settings = mocker.patch("rctab.daily_routine_tasks.get_settings")
    mock_settings.return_value.admin_email_recipients = ["me@my.org"]

    mock_sleep = AsyncMock(side_effect=BreakLoopException)
    mocker.patch("rctab.daily_routine_tasks.sleep", mock_sleep)

    mock_send = AsyncMock()
    mocker.patch("rctab.daily_routine_tasks.send_summary_email", mock_send)

    mock_abolish_send = mocker.patch(
        "rctab.routers.accounting.abolishment.send_with_sendgrid"
    )
    mock_abolish_send.return_value = 200

    mocker.patch("rctab.daily_routine_tasks.ADMIN_OID", str(constants.ADMIN_UUID))

    mock_now = mocker.patch("rctab.daily_routine_tasks.datetime_utcnow")
    mock_now.return_value = datetime.combine(
        date.today(), time(15, 59, 0), timezone.utc
    )

    subscription_id = await create_subscription(test_db)

    await create_expired_subscription(test_db)

    try:
        await routine_tasks()
    except BreakLoopException:
        pass

    # Since we've "woken" 10 seconds before the email is due to be sent,
    # we don't send email yet
    mock_send.assert_not_called()

    mock_now.return_value = datetime.combine(date.today(), time(16, 1, 0), timezone.utc)

    try:
        await routine_tasks()
    except BreakLoopException:
        pass

    # Since we've "woken" a whole 3601 seconds before the email is due to be sent,
    # we should go back to sleep
    mock_send.assert_called_once()

    insert_statement = insert(emails).values(
        {
            "subscription_id": subscription_id,
            "status": 200,
            "type": EMAIL_TYPE_SUMMARY,
            "recipients": ";".join(["me@mail"]),
            # "time_created": datetime.now()
        }
    )
    await test_db.execute(insert_statement)

    mock_now.return_value = datetime.combine(date.today(), time(16, 2, 0), timezone.utc)

    try:
        await routine_tasks()
    except BreakLoopException:
        pass

    # We've already sent an email on this day, so we don't want to send another one.
    mock_send.assert_called_once()

    mock_now.return_value = datetime.combine(
        date.today(), time(16, 2, 0), timezone.utc
    ) + timedelta(days=1)

    try:
        await routine_tasks()
    except BreakLoopException:
        pass

    # We last sent an email yesterday so expect another
    assert mock_send.call_count == 2


def test_calc_how_long_to_sleep_for(mocker: MockerFixture) -> None:
    mock_now = mocker.patch("rctab.daily_routine_tasks.datetime_utcnow")
    mock_now.return_value = datetime.combine(date.today(), time(15, 0, 0), timezone.utc)
    assert calc_how_long_to_sleep_for("16:00:00") == 3600
    assert calc_how_long_to_sleep_for("14:00:00") == 3600 * 23


def test_calc_how_long_to_sleep_floor(mocker: MockerFixture) -> None:
    mock_now = mocker.patch("rctab.daily_routine_tasks.datetime_utcnow")
    mock_now.return_value = datetime.combine(
        date.today(), time(11, 59, 59, 500000), timezone.utc
    )
    #  We never want to sleep for less than one second
    assert calc_how_long_to_sleep_for("12:00:00") == 1


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
