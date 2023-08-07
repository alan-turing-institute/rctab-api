from datetime import date
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlalchemy import insert, select

from rctab.crud.accounting_models import (
    cost_recovery,
    cost_recovery_log,
    finance,
    finance_history,
)
from rctab.crud.models import user_rbac
from rctab.crud.schema import Finance, FinanceWithID
from rctab.routers.accounting.cost_recovery import CostRecoveryMonth
from rctab.routers.accounting.finances import (
    check_create_finance,
    check_update_finance,
    delete_finance,
    get_end_month,
    get_finance,
    get_start_month,
    get_subscription_finances,
    post_finance,
    update_finance,
)
from rctab.routers.accounting.routes import PREFIX, SubscriptionItem
from tests.test_routes import api_calls, constants
from tests.test_routes.constants import ADMIN_DICT
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)


def test_finance_route(auth_app: FastAPI) -> None:
    """Check we can call the finances route when there is no data."""

    with TestClient(auth_app) as client:

        result = client.request(
            "GET",
            PREFIX + "/finance",
            content=SubscriptionItem(sub_id=UUID(int=33)).json(),
        )

        assert result.status_code == 200
        assert result.json() == []


@pytest.mark.asyncio
async def test_empty_finance_table(
    test_db: Database,  # pylint: disable=redefined-outer-name,unused-argument
) -> None:
    """Check we return an empty list when there are no finances."""
    finances = await get_subscription_finances(
        SubscriptionItem(sub_id=UUID(int=33)), "my token"  # type: ignore
    )
    assert finances == []


@pytest.mark.asyncio
async def test_get_correct_finance(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we return the right record."""
    sub_id_a = await create_subscription(test_db)
    sub_id_b = await create_subscription(test_db)

    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )

    f_b = Finance(
        subscription_id=sub_id_b,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )
    await test_db.execute(finance.insert().values(), {**ADMIN_DICT, **f_a.dict()})
    await test_db.execute(finance.insert().values(), {**ADMIN_DICT, **f_b.dict()})

    actual = await get_subscription_finances(
        SubscriptionItem(sub_id=sub_id_a), "my token"  # type: ignore
    )
    # We strip the new Finance ID before comparison
    assert [Finance(**x.dict()) for x in actual] == [f_a]


def test_finances_route(auth_app: FastAPI) -> None:
    """Check we can post a Finance."""

    with TestClient(auth_app) as client:

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)

        f_a = Finance(
            subscription_id=constants.TEST_SUB_UUID,
            ticket="test_ticket",
            amount=0.0,
            date_from="2022-08-01",
            date_to="2022-08-03",
            finance_code="test_finance",
            priority=1,
        )
        result = client.post(PREFIX + "/finances", content=f_a.json())

        assert result.status_code == 201


@pytest.mark.asyncio
async def test_post_finance(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: MockerFixture,
) -> None:
    """Check that we can post a new finance."""

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID
    result = await post_finance(f_a, mock_rbac)  # type: ignore

    assert Finance(**result.dict()) == f_a


def test_get_start_month() -> None:
    date_from = date(2022, 8, 15)

    start_date = get_start_month(date_from)
    assert start_date == date(2022, 8, 1)


def test_get_end_month() -> None:
    """
    Check that we return the correct last day of a month (including leap years).
    """
    date_feb = date(2022, 2, 15)
    end_feb = get_end_month(date_feb)
    date_july = date(2022, 7, 19)
    end_july = get_end_month(date_july)
    date_feb_leap_year = date(2020, 2, 7)
    end_feb_leap_year = get_end_month(date_feb_leap_year)
    assert end_feb.day == 28
    assert end_feb_leap_year.day == 29
    assert end_july.day == 31


@pytest.mark.asyncio
async def test_check_finance(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-07-19",
        date_to="2022-07-23",
        finance_code="test_finance",
        priority=1,
    )

    await check_create_finance(f_a)

    assert f_a.date_from.day == 1
    assert f_a.date_to.day == 31


@pytest.mark.asyncio
async def test_check_finance_raise_exception_dates(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """
    Test if we raise exception if date_from is later than date_to
    """
    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-07-19",
        date_to="2022-06-30",
        finance_code="test_finance",
        priority=1,
    )
    with pytest.raises(HTTPException) as exception_info:
        await check_create_finance(f_a)
    assert (
        exception_info.value.detail
        == f"Date from ({str(f_a.date_from)}) cannot be greater than date to ({str(f_a.date_to)})"
    )


@pytest.mark.asyncio
async def test_check_finance_raise_exception_negative_amount(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """
    Test if we raise exception if amount is < 0.
    """
    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=-1,
        date_from="2022-06-19",
        date_to="2022-06-30",
        finance_code="test_finance",
        priority=1,
    )
    with pytest.raises(HTTPException) as exception_info:
        await check_create_finance(f_a)
    assert exception_info.value.detail == "Amount should not be negative but was -1.0"


@pytest.mark.asyncio
async def test_check_finance_raise_exception_already_recovered(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Test if check_finance() correctly raises exceptions.

    It should raise if costs for the subscriptions have already been recovered.
    """
    subscription_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=subscription_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-31",
        finance_code="test_finance",
        priority=1,
    )
    # no exception expected if no cost recovery record found
    await check_create_finance(f_a)
    f_a_id = await test_db.execute(
        finance.insert().values(), {**ADMIN_DICT, **f_a.dict()}
    )

    # no exception expected if no cost recovery record found for this subscription id
    subscription_b = await create_subscription(test_db)
    f_b = Finance(
        subscription_id=subscription_b,
        ticket="test_ticket",
        amount=0.0,
        date_from="2001-08-01",
        date_to="2040-08-31",
        finance_code="test_finance",
        priority=1,
    )
    f_b_id = await test_db.execute(
        finance.insert().values(), {**ADMIN_DICT, **f_b.dict()}
    )
    values = dict(
        finance_id=f_b_id,
        subscription_id=str(subscription_b),
        month=date(2022, 8, 1),
        finance_code="test_code",
        amount=500.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)
    await check_create_finance(f_a)

    values = dict(
        finance_id=f_b_id,
        subscription_id=str(subscription_a),
        month=date(2022, 7, 1),
        finance_code="test_code",
        amount=500.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)
    await check_create_finance(f_a)

    # we expect an exception when trying to add an earlier record
    values = dict(
        finance_id=f_a_id,  # It doesn't really matter which ID we use here
        subscription_id=str(subscription_a),
        month=date(2022, 10, 1),
        finance_code="test_code",
        amount=500.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)
    with pytest.raises(HTTPException) as exception_info:
        await check_create_finance(f_a)
    assert (
        exception_info.value.detail
        == f"We have already recovered costs until {str(date(2022, 10, 1))}"
        + f" for the subscription {str(f_a.subscription_id)}, "
        + "please choose a later start date"
    )

    # we expect an exception if trying to add a record on the same month
    values = dict(
        finance_id=f_a_id,  # It doesn't really matter which ID we use here
        subscription_id=str(subscription_a),
        month=date(2022, 8, 1),
        finance_code="test_code",
        amount=500.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)
    with pytest.raises(HTTPException) as exception_info:
        await check_create_finance(f_a)
    assert (
        exception_info.value.detail
        == f"We have already recovered costs until {str(date(2022, 8, 1))}"
        + f" for the subscription {str(f_a.subscription_id)}, "
        + "please choose a later start date"
    )

    #  no exception expected as the new finance is later
    values = dict(
        finance_id=f_a_id,  # It doesn't really matter which ID we use here
        subscription_id=str(subscription_a),
        month=date(2022, 6, 12),
        finance_code="test_code",
        amount=500.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)
    await check_create_finance(f_a)


def test_finance_post_get_put_delete(auth_app: FastAPI) -> None:
    """Check we can call the finance routes."""

    with TestClient(auth_app) as client:

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)

        f_a = Finance(
            subscription_id=constants.TEST_SUB_UUID,
            ticket="test_ticket",
            amount=0.0,
            date_from="2022-08-01",
            date_to="2022-08-03",
            finance_code="test_finance",
            priority=1,
        )
        result = client.post(PREFIX + "/finances", content=f_a.json())
        assert result.status_code == 201
        f_a_returned = FinanceWithID.parse_raw(result.content)

        f_a_returned.amount = 10.0
        result = client.put(
            PREFIX + f"/finances/{f_a_returned.id}", content=f_a_returned.json()
        )
        assert result.status_code == 200

        result = client.get(PREFIX + f"/finances/{f_a_returned.id}")
        assert result.status_code == 200
        assert FinanceWithID.parse_raw(result.content) == f_a_returned

        result = client.request(
            "DELETE",
            PREFIX + f"/finances/{f_a_returned.id}",
            content=SubscriptionItem(sub_id=constants.TEST_SUB_UUID).json(),
        )
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_finance_history_delete(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that our trigger and function work for deletions."""

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )
    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID
    result = await post_finance(f_a, mock_rbac)  # type: ignore
    await delete_finance(result.id, SubscriptionItem(sub_id=sub_id_a))

    # The finance record should have been deleted
    actual = await get_subscription_finances(
        SubscriptionItem(sub_id=sub_id_a), "my token"  # type: ignore
    )
    assert actual == []

    rows = await test_db.fetch_all(select([finance_history]))
    dicts = [dict(x) for x in rows]

    assert len(dicts) == 1
    # This is a quirk of the testing setup,
    # which allows us to check that time_deleted has been populated
    assert dicts[0].pop("time_deleted") == dicts[0].pop("time_created")
    assert FinanceWithID(**dicts[0]) == result


@pytest.mark.asyncio
async def test_finance_history_update(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that our trigger and function work for deletions."""

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID
    f_b = await post_finance(f_a, mock_rbac)  # type: ignore

    f_c = FinanceWithID(**f_b.dict())
    f_c.amount = 100

    await update_finance(f_c.id, f_c, mock_rbac)

    # The finance record should have been deleted
    actual = await get_subscription_finances(
        SubscriptionItem(sub_id=sub_id_a), "my token"  # type: ignore
    )
    assert len(actual) == 1

    rows = await test_db.fetch_all(select([finance_history]))
    dicts = [dict(x) for x in rows]

    assert len(dicts) == 1
    # This is a quirk of the testing setup,
    # which allows us to check that time_deleted has been populated
    assert dicts[0].pop("time_deleted") == dicts[0].pop("time_created")
    assert FinanceWithID(**dicts[0]) == f_b


@pytest.mark.asyncio
async def test_delete_finance_raises(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that the delete route checks for matching IDs."""

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2022-08-01",
        date_to="2022-08-03",
        finance_code="test_finance",
        priority=1,
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID
    result = await post_finance(f_a, mock_rbac)  # type: ignore

    # We should raise if the finance ID doesn't exist
    with pytest.raises(HTTPException) as exception_info:
        await delete_finance(result.id + 1, SubscriptionItem(sub_id=sub_id_a))

    assert exception_info.value.detail == "Finance not found"

    # We should raise if the finance row's subscription doesn't match the one supplied
    with pytest.raises(HTTPException) as exception_info:
        await delete_finance(
            result.id, SubscriptionItem(sub_id=UUID(int=sub_id_a.int + 1))
        )

    assert exception_info.value.detail == "Subscription ID does not match"

    values = dict(
        finance_id=result.id,
        subscription_id=str(sub_id_a),
        month=date(2001, 1, 1),
        finance_code="test_code",
        amount=0.0,
        admin=constants.ADMIN_UUID,
    )
    await test_db.execute(cost_recovery.insert().values(), values)

    # We should raise if this finance ID has been fully or partially recovered
    with pytest.raises(HTTPException) as exception_info:
        await delete_finance(result.id, SubscriptionItem(sub_id=sub_id_a))

    assert exception_info.value.detail == "Costs have already been recovered"


@pytest.mark.asyncio
async def test_get_finance_raises(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we return a 400 status code if not found."""

    with pytest.raises(HTTPException):
        await get_finance(1, "a token")  # type: ignore

    del test_db


def test_finance_can_update(auth_app: FastAPI) -> None:
    """Check that we can update some fields, even after cost recovery."""

    with TestClient(auth_app) as client:

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)

        f_a = Finance(
            subscription_id=constants.TEST_SUB_UUID,
            ticket="test_ticket",
            amount=0.0,
            date_from="2022-08-01",
            date_to="2022-10-31",
            finance_code="test_finance",
            priority=1,
        )
        result = client.post(PREFIX + "/finances", content=f_a.json())
        assert result.status_code == 201
        f_a_returned = FinanceWithID.parse_raw(result.content)

        result = client.post(
            PREFIX + "/cli-cost-recovery",
            content=CostRecoveryMonth(first_day="2022-09-01").json(),
        )
        assert result.status_code == 200

        f_a_returned.amount = 10.0
        result = client.put(
            PREFIX + f"/finances/{f_a_returned.id}", content=f_a_returned.json()
        )
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_update_finance_checks(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we call the check_update_finance function."""

    mock_check = AsyncMock()
    mocker.patch("rctab.routers.accounting.finances.check_update_finance", mock_check)

    f_a = FinanceWithID(
        id=1,
        subscription_id=UUID(int=1),
        ticket="test ticket",
        amount=0,
        priority=0,
        finance_code="",
        date_from=date.today(),
        date_to=date.today(),
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID

    await update_finance(1, f_a, mock_rbac)
    mock_check.assert_called_once_with(f_a)

    del test_db


@pytest.mark.asyncio
async def test_check_update_finance(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we validate updates."""

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2000-01-01",
        date_to="2000-06-30",
        finance_code="test_finance",
        priority=1,
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = constants.ADMIN_UUID

    # f_b is the same as f_a but has an ID
    f_b = await post_finance(f_a, mock_rbac)  # type: ignore

    f_c = FinanceWithID(**f_b.dict())

    # Subscription IDs should match
    f_c.subscription_id = UUID(int=101)

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_c)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "Subscription IDs should match"

    # date_to should come after date_from
    f_d = FinanceWithID(**f_b.dict())
    f_d.date_to = f_d.date_from

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_d)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "date_to <= date_from"

    # Amount should be >= 0
    f_e = FinanceWithID(**f_b.dict())
    f_e.amount = -0.1

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_e)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "amount < 0"

    # Can't insert new.date_from if that month has been recovered
    await test_db.execute(
        insert(cost_recovery_log),
        {"month": date.fromisoformat("1999-12-01"), "admin": constants.ADMIN_UUID},
    )
    f_f = FinanceWithID(**{**f_b.dict(), **{"date_from": "1999-11-01"}})

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_f)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "new.date_from has been recovered"

    # Can't change old.date_from if that month has been recovered
    await test_db.execute(
        insert(cost_recovery_log),
        {"month": date.fromisoformat("2000-04-01"), "admin": constants.ADMIN_UUID},
    )
    f_g = FinanceWithID(**{**f_b.dict(), **{"date_from": "2000-02-01"}})

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_g)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "old.date_from has been recovered"

    # Can't change new.date_to if that month has been recovered
    f_h = FinanceWithID(**{**f_b.dict(), **{"date_to": "2000-03-31"}})

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_h)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "new.date_to has been recovered"

    # Can't change old.date_to if that month has been recovered
    await test_db.execute(
        insert(cost_recovery_log),
        {"month": date.fromisoformat("2000-07-01"), "admin": constants.ADMIN_UUID},
    )
    f_i = FinanceWithID(**{**f_b.dict(), **{"date_to": "2000-08-30"}})

    with pytest.raises(HTTPException) as exception_info:
        await check_update_finance(f_i)

    assert exception_info.value.status_code == 400
    assert exception_info.value.detail == "old.date_to has been recovered"


@pytest.mark.asyncio
async def test_check_update_finance_admin(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we update the admin column when we update a finance."""

    creator_oid = UUID(int=1)
    await test_db.execute(
        insert(user_rbac),
        {
            "oid": creator_oid,
            "username": "creator",
            "has_access": True,
            "is_admin": True,
        },
    )

    updater_oid = UUID(int=2)
    await test_db.execute(
        insert(user_rbac),
        {
            "oid": updater_oid,
            "username": "creator",
            "has_access": True,
            "is_admin": True,
        },
    )

    sub_id_a = await create_subscription(test_db)
    f_a = Finance(
        subscription_id=sub_id_a,
        ticket="test_ticket",
        amount=0.0,
        date_from="2000-01-01",
        date_to="2000-06-30",
        finance_code="test_finance",
        priority=1,
    )

    mock_rbac = mocker.Mock()
    mock_rbac.oid = creator_oid

    # f_b is the same as f_a but has an ID
    f_b = await post_finance(f_a, mock_rbac)  # type: ignore

    mock_rbac.oid = updater_oid
    await update_finance(f_b.id, f_b, mock_rbac)

    rows = await test_db.fetch_all(select([finance]))
    updated_finances = [dict(row) for row in rows]
    assert len(updated_finances) == 1
    assert updated_finances[0]["admin"] == updater_oid
