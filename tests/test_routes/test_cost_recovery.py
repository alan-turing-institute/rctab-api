import random
from datetime import date
from typing import Tuple
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from databases import Database
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlalchemy import insert, select

from rctab.constants import ADMIN_OID
from rctab.crud import accounting_models
from rctab.crud.accounting_models import usage
from rctab.crud.schema import CostRecovery, Finance, Usage
from rctab.routers.accounting.cost_recovery import (
    CostRecoveryMonth,
    calc_cost_recovery,
    validate_month,
)
from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import constants
from tests.test_routes.constants import ADMIN_DICT
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import
from tests.test_routes.test_routes import create_subscription
from tests.test_routes.utils import no_rollback_test_db  # pylint: disable=unused-import


def test_cost_recovery_app_route(
    app_with_signed_billing_token: Tuple[FastAPI, str],
    mocker: MockerFixture,
) -> None:
    """Check we can cost-recover a month."""

    auth_app, token = app_with_signed_billing_token
    with TestClient(auth_app) as client:

        mock = AsyncMock()
        mocker.patch("rctab.routers.accounting.cost_recovery.calc_cost_recovery", mock)

        recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
        result = client.post(
            PREFIX + "/app-cost-recovery",
            content=recovery_period.model_dump_json(),
            headers={"authorization": "Bearer " + token},
        )

        mock.assert_called_once_with(
            recovery_period, commit_transaction=True, admin=UUID(ADMIN_OID)
        )

        assert result.status_code == 200
        assert result.json() == {
            "detail": "cost recovery calculated",
            "status": "success",
        }


def test_cost_recovery_cli_route(
    auth_app: FastAPI,
    mocker: MockerFixture,
) -> None:
    """Check we can cost-recover a month."""

    with TestClient(auth_app) as client:

        mock = AsyncMock()
        mock.return_value = []
        mocker.patch("rctab.routers.accounting.cost_recovery.calc_cost_recovery", mock)

        recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
        result = client.post(
            PREFIX + "/cli-cost-recovery",
            content=recovery_period.model_dump_json(),
        )

        mock.assert_called_once_with(
            recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
        )

        assert result.status_code == 200
        assert result.json() == []


def test_cost_recovery_cli_route_dry_run(
    auth_app: FastAPI,
    mocker: MockerFixture,
) -> None:
    """Check we return the right values."""

    with TestClient(auth_app) as client:
        mock = AsyncMock()
        mock.return_value = []
        mocker.patch("rctab.routers.accounting.cost_recovery.calc_cost_recovery", mock)

        recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
        result = client.request(
            "GET",
            PREFIX + "/cli-cost-recovery",
            content=recovery_period.model_dump_json(),
        )

        mock.assert_called_once_with(
            recovery_period, commit_transaction=False, admin=constants.ADMIN_UUID
        )

        assert result.status_code == 200
        assert result.json() == []


@pytest.mark.asyncio
async def test_cost_recovery_simple(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we can recover costs for a single finance row."""
    subscription_id = await create_subscription(test_db)

    for _ in range(2):
        await test_db.execute(
            usage.insert().values(),
            Usage(
                subscription_id=str(subscription_id),
                id=str(UUID(int=random.randint(0, 2**32 - 1))),
                total_cost=1,
                invoice_section="",
                date=date(2001, 1, 1),
            ).dict(),
        )

    new_finance = Finance(
        subscription_id=subscription_id,
        ticket="test_ticket",
        amount=1.5,
        date_from="2001-01-01",
        date_to="2001-01-31",
        finance_code="test_finance",
        priority=1,
    )
    await test_db.execute(
        insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
    )
    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(select([accounting_models.cost_recovery]))
    ]

    assert len(results) == 1

    assert results[0]["subscription_id"] == subscription_id
    # £2 used but only £1.50 is recoverable
    assert results[0]["amount"] == 1.5
    assert results[0]["month"] == date(year=2001, month=1, day=1)
    assert results[0]["finance_code"] == "test_finance"


@pytest.mark.asyncio
async def test_cost_recovery_two_finances(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we can recover costs where there are overlapping finance records."""
    subscription_id = await create_subscription(test_db)

    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_id),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=3,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Two finances in our period of interest and one outside
    for date_from in ("2001-01-01", "2001-01-01", "2001-02-01"):
        new_finance = Finance(
            subscription_id=subscription_id,
            ticket="test_ticket",
            amount=1.0,
            date_from=date_from,
            date_to="2001-02-28",
            finance_code="test_finance",
            priority=1,
        )
        await test_db.execute(
            insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
        )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(select([accounting_models.cost_recovery]))
    ]

    assert len(results) == 2

    # Since we have two £1 finance rows, we expect to be billed for £2
    assert results[0]["amount"] == 1.0
    assert results[1]["amount"] == 1.0


@pytest.mark.asyncio
async def test_cost_recovery_second_month(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that two months can be recovered correctly."""
    subscription_id = await create_subscription(test_db)

    # Jan
    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_id),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=1,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Feb
    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_id),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=2,
            invoice_section="",
            date=date(2001, 2, 1),
        ).dict(),
    )

    # Jan - Feb
    new_finance = Finance(
        subscription_id=subscription_id,
        ticket="test_ticket",
        amount=2.0,
        date_from="2001-01-01",
        date_to="2001-02-28",
        finance_code="test_finance",
        priority=1,
    )
    await test_db.execute(
        insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
    )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=2, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(
            select([accounting_models.cost_recovery]).order_by(
                accounting_models.cost_recovery.c.id
            )
        )
    ]

    assert len(results) == 2

    assert results[0]["amount"] == 1.0
    assert results[0]["month"] == date(year=2001, month=1, day=1)

    assert results[1]["amount"] == 1.0
    assert results[1]["month"] == date(year=2001, month=2, day=1)


@pytest.mark.asyncio
async def test_cost_recovery_two_subscriptions(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we can recover costs for two different subscriptions."""
    subscription_a = await create_subscription(test_db)
    subscription_b = await create_subscription(test_db)

    # Jan
    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_a),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=1,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Jan
    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_b),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=2,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Jan - Feb
    new_finance = Finance(
        subscription_id=subscription_b,
        ticket="test_ticket",
        amount=2.0,
        date_from="2001-01-01",
        date_to="2001-02-28",
        finance_code="test_finance",
        priority=1,
    )
    await test_db.execute(
        insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
    )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(
            select([accounting_models.cost_recovery]).order_by(
                accounting_models.cost_recovery.c.id
            )
        )
    ]

    assert len(results) == 1

    assert results[0]["subscription_id"] == subscription_b
    assert results[0]["amount"] == 2.0
    assert results[0]["month"] == date(year=2001, month=1, day=1)


@pytest.mark.asyncio
async def test_cost_recovery_priority_one_month(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we can recover costs where there are overlapping finance records."""
    subscription_id = await create_subscription(test_db)

    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_id),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=3,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Two finances in our period of interest and one outside
    for finance_code, priority in [("f-2", 100), ("f-1", 99)]:
        new_finance = Finance(
            subscription_id=subscription_id,
            ticket="test_ticket",
            amount=2.0,
            date_from="2001-01-01",
            date_to="2001-02-28",
            finance_code=finance_code,
            priority=priority,
        )
        await test_db.execute(
            insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
        )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(
            select([accounting_models.cost_recovery]).order_by(
                accounting_models.cost_recovery.c.finance_code
            )
        )
    ]

    assert len(results) == 2

    assert results[0]["finance_code"] == "f-1"
    assert results[0]["amount"] == 2.0

    assert results[1]["finance_code"] == "f-2"
    assert results[1]["amount"] == 1.0


@pytest.mark.asyncio
async def test_cost_recovery_priority_two_months(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check we can recover costs where there are overlapping finance records."""
    subscription_id = await create_subscription(test_db)

    await test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_id),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=3,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Two finances in our period of interest and one outside
    for finance_code, priority in [("f-2", 100), ("f-1", 99)]:
        new_finance = Finance(
            subscription_id=subscription_id,
            ticket="test_ticket",
            amount=2.0,
            date_from="2001-01-01",
            date_to="2001-02-28",
            finance_code=finance_code,
            priority=priority,
        )
        await test_db.execute(
            insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
        )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    results = [
        dict(row)
        for row in await test_db.fetch_all(
            select([accounting_models.cost_recovery]).order_by(
                accounting_models.cost_recovery.c.finance_code
            )
        )
    ]

    assert len(results) == 2

    assert results[0]["finance_code"] == "f-1"
    assert results[0]["amount"] == 2.0

    assert results[1]["finance_code"] == "f-2"
    assert results[1]["amount"] == 1.0


@pytest.mark.asyncio
async def test_cost_recovery_validates(
    mocker: MockerFixture,
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we validate the month being recovered."""
    mock_validate = mocker.Mock()
    mocker.patch("rctab.routers.accounting.cost_recovery.validate_month", mock_validate)

    cost_recovery_month = CostRecoveryMonth(first_day="2001-01-01")

    await calc_cost_recovery(cost_recovery_month, True, constants.ADMIN_UUID)

    mock_validate.assert_called_once_with(cost_recovery_month, None)

    twenty_ten = date.fromisoformat("2010-10-01")

    await test_db.execute(
        insert(accounting_models.cost_recovery_log),
        {**ADMIN_DICT, "month": date.fromisoformat("2010-08-01")},
    )
    await test_db.execute(
        insert(accounting_models.cost_recovery_log), {**ADMIN_DICT, "month": twenty_ten}
    )
    await test_db.execute(
        insert(accounting_models.cost_recovery_log),
        {**ADMIN_DICT, "month": date.fromisoformat("2010-09-01")},
    )

    await calc_cost_recovery(cost_recovery_month, True, constants.ADMIN_UUID)

    mock_validate.assert_called_with(
        cost_recovery_month, CostRecoveryMonth(first_day=twenty_ten)
    )


@pytest.mark.asyncio
async def test_cost_recovery_commit_param(
    no_rollback_test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: MockerFixture,
) -> None:
    """Check the return value when we do a dry-run."""
    subscription_a = await create_subscription(no_rollback_test_db)

    # Jan
    await no_rollback_test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_a),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=1,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Jan - Feb
    new_finance = Finance(
        subscription_id=subscription_a,
        ticket="test_ticket",
        amount=2.0,
        date_from="2001-01-01",
        date_to="2001-02-28",
        finance_code="test_finance",
        priority=1,
    )
    new_finance_id = await no_rollback_test_db.execute(
        insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
    )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))

    mocker.patch(
        "rctab.routers.accounting.cost_recovery.database", new=no_rollback_test_db
    )
    cost_recoveries = await calc_cost_recovery(
        cost_recovery_period, commit_transaction=False, admin=constants.ADMIN_UUID
    )

    assert cost_recoveries == [
        CostRecovery(
            subscription_id=subscription_a,
            finance_id=new_finance_id,
            month="2001-01-01",
            finance_code="test_finance",
            amount=1,
        )
    ]

    results = [
        dict(row)
        for row in await no_rollback_test_db.fetch_all(
            select([accounting_models.cost_recovery])
        )
    ]

    # Since we used commit_transaction=False, we expect the table to be empty
    assert len(results) == 0

    results = [
        dict(row)
        for row in await no_rollback_test_db.fetch_all(
            select([accounting_models.cost_recovery_log])
        )
    ]

    # Since we used commit_transaction=False, we expect the table to be empty
    assert len(results) == 0


class PretendTimeoutError(Exception):
    pass


@pytest.mark.asyncio
async def test_cost_recovery_rollsback(
    no_rollback_test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: MockerFixture,
) -> None:
    """Check that we roll back if disconnected."""

    subscription_a = await create_subscription(no_rollback_test_db)

    # Jan
    await no_rollback_test_db.execute(
        usage.insert().values(),
        Usage(
            subscription_id=str(subscription_a),
            id=str(UUID(int=random.randint(0, 2**32 - 1))),
            total_cost=1,
            invoice_section="",
            date=date(2001, 1, 1),
        ).dict(),
    )

    # Jan - Feb
    new_finance = Finance(
        subscription_id=subscription_a,
        ticket="test_ticket",
        amount=2.0,
        date_from="2001-01-01",
        date_to="2001-02-28",
        finance_code="test_finance",
        priority=1,
    )
    await no_rollback_test_db.execute(
        insert(accounting_models.finance), {**ADMIN_DICT, **new_finance.dict()}
    )

    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))

    # Patch CostRecovery as a hack to check error handling
    # (transaction should be rolled back and an exception raised)
    mock = mocker.Mock()
    mock.side_effect = PretendTimeoutError
    mocker.patch("rctab.routers.accounting.cost_recovery.CostRecovery", mock)

    with pytest.raises(PretendTimeoutError):
        mocker.patch(
            "rctab.routers.accounting.cost_recovery.database", no_rollback_test_db
        )
        await calc_cost_recovery(
            cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
        )

    results = [
        dict(row)
        for row in await no_rollback_test_db.fetch_all(
            select([accounting_models.cost_recovery])
        )
    ]

    # Since we used commit_transaction=False, we expect the table to be empty
    assert len(results) == 0


@pytest.mark.asyncio
async def test_cost_recovery_log(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we can only recover a month once."""
    # pylint: disable=unused-argument
    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2000, month=1, day=2))

    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
    )

    # We can dry-run previous months...
    await calc_cost_recovery(
        cost_recovery_period, commit_transaction=False, admin=constants.ADMIN_UUID
    )

    # ...but we mustn't commit
    with pytest.raises(HTTPException) as exception_info:
        await calc_cost_recovery(
            cost_recovery_period, commit_transaction=True, admin=constants.ADMIN_UUID
        )

    assert exception_info.value.detail == "Expected 2000-02"
    assert exception_info.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_month(mocker: MockerFixture) -> None:
    """Test our date validation function."""

    # Any old month can be the first month so this shouldn't raise
    cost_recovery_period = CostRecoveryMonth(first_day=date(year=2001, month=1, day=1))
    validate_month(cost_recovery_period, None)

    mock_date = mocker.Mock(wraps=date)
    mock_date.today.return_value = date.fromisoformat("2001-06-01")
    mocker.patch("rctab.routers.accounting.cost_recovery.date", mock_date)

    # We shouldn't recover the current month, as the usage isn't finalised...
    cost_recovery_period = CostRecoveryMonth(first_day=date.fromisoformat("2001-06-01"))
    with pytest.raises(HTTPException) as exception_info:
        validate_month(cost_recovery_period, None)

    assert exception_info.value.detail == "Cannot recover later than 2001-05"
    assert exception_info.value.status_code == 400

    # ...even if it's next in line...
    cost_recovery_period = CostRecoveryMonth(first_day="2001-06-01")
    last_recovered_month = CostRecoveryMonth(first_day="2001-05-01")
    with pytest.raises(HTTPException) as exception_info:
        validate_month(cost_recovery_period, last_recovered_month)

    assert exception_info.value.detail == "Cannot recover later than 2001-05"
    assert exception_info.value.status_code == 400

    # ...nor future months...
    cost_recovery_period = CostRecoveryMonth(first_day="2001-07-01")
    with pytest.raises(HTTPException) as exception_info:
        validate_month(cost_recovery_period, None)

    assert exception_info.value.detail == "Cannot recover later than 2001-05"
    assert exception_info.value.status_code == 400

    # ...nor any month other than the next un-recovered month.
    cost_recovery_period = CostRecoveryMonth(first_day="2001-03-01")
    last_recovered_month = CostRecoveryMonth(first_day="2001-01-01")
    with pytest.raises(HTTPException) as exception_info:
        validate_month(cost_recovery_period, last_recovered_month)

    assert exception_info.value.detail == "Expected 2001-02"
    assert exception_info.value.status_code == 400
