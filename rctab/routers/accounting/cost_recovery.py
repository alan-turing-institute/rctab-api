from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import sqlalchemy
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, between, desc, func, insert, select

from rctab.constants import ADMIN_OID
from rctab.crud.accounting_models import (
    cost_recovery,
    cost_recovery_log,
    finance,
    usage,
)
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import CostRecovery, UserRBAC
from rctab.routers.accounting.routes import router
from rctab.routers.accounting.usage import authenticate_usage_app


class CostRecoveryMonth(BaseModel):
    # The first day of the month
    first_day: date


def validate_month(
    month_to_recover: CostRecoveryMonth,
    last_recovered_month: Optional[CostRecoveryMonth],
) -> None:
    """Raise if month shouldn't be recovered."""
    if last_recovered_month:
        # If we have previously recovered a month,
        # we know exactly which month we should be recovering
        month_expected = last_recovered_month.first_day + timedelta(days=31)
        month_expected = date(
            year=month_expected.year, month=month_expected.month, day=1
        )
        if month_to_recover.first_day != month_expected:
            raise HTTPException(
                status_code=400, detail="Expected " + month_expected.isoformat()[:-3]
            )

    # We can never recover later than last month
    middle_of_this_month = date.today().replace(day=15)
    middle_of_last_month = middle_of_this_month - timedelta(days=30)
    first_of_last_month = middle_of_last_month.replace(day=1)
    if month_to_recover.first_day > first_of_last_month:
        raise HTTPException(
            status_code=400,
            detail="Cannot recover later than " + first_of_last_month.isoformat()[:-3],
        )


async def calc_cost_recovery(
    recovery_month: CostRecoveryMonth, commit_transaction: bool, admin: UUID
) -> List[CostRecovery]:
    """Calculates the cost recovery for a given period.

    Cost recovery must have been calculated for all previous months
    but not for this month.
    """
    last_recovered_day = await database.fetch_one(
        select([cost_recovery_log]).order_by(desc(cost_recovery_log.c.month))
    )
    last_recovered_month = (
        CostRecoveryMonth(first_day=last_recovered_day["month"])
        if last_recovered_day
        else None
    )
    if commit_transaction:
        validate_month(recovery_month, last_recovered_month)

    transaction = await database.transaction()
    try:

        cost_recovery_ids = []

        # We're only interested in subscriptions if they have a finance record
        subscription_ids = [
            r["sub_id"]
            for r in await database.fetch_all(
                select(
                    [func.distinct(finance.c.subscription_id).label("sub_id")]
                ).where(
                    between(
                        recovery_month.first_day, finance.c.date_from, finance.c.date_to
                    )
                )
            )
        ]

        for subscription_id in subscription_ids:

            usage_row = await database.fetch_one(
                select([func.sum(usage.c.total_cost).label("the_sum")])
                .where(
                    func.date_trunc(
                        "month", sqlalchemy.cast(usage.c.date, sqlalchemy.Date)
                    )
                    == func.date_trunc(
                        "month",
                        sqlalchemy.cast(recovery_month.first_day, sqlalchemy.Date),
                    )
                )
                .where(usage.c.subscription_id == subscription_id)
            )
            # This should always return a row, though the_sum can be NULL
            assert usage_row
            total_usage = usage_row["the_sum"] or 0.0
            usage_recharged = 0

            # The lower the value of priority, the higher importance
            finance_periods = await database.fetch_all(
                select([finance])
                .where(
                    and_(
                        between(
                            recovery_month.first_day,
                            finance.c.date_from,
                            finance.c.date_to,
                        ),
                        finance.c.subscription_id == subscription_id,
                    )
                )
                .order_by(finance.c.priority)
            )

            # We divide the usage between the eligible finance periods
            for finance_period in finance_periods:

                cost_recovery_row = await database.fetch_one(
                    select([func.sum(cost_recovery.c.amount).label("the_sum")]).where(
                        cost_recovery.c.finance_id == finance_period["id"]
                    )
                )

                # This should always return a row, though the_sum can be NULL
                assert cost_recovery_row
                recovered_amount = cost_recovery_row["the_sum"] or 0.0

                recoverable_amount = min(
                    # The smallest of
                    # a) the amount remaining on the finance ID and
                    # b) the amount of usage yet to be charged
                    finance_period["amount"] - recovered_amount,
                    total_usage - usage_recharged,
                )

                # Keep track of how much of this subscription's usage
                # has been recharged
                usage_recharged += recoverable_amount

                cost_recovery_id = await database.execute(
                    insert(
                        cost_recovery,
                        {
                            "subscription_id": finance_period["subscription_id"],
                            "month": recovery_month.first_day,
                            "finance_code": finance_period["finance_code"],
                            "amount": recoverable_amount,
                            "date_recovered": None,
                            "finance_id": finance_period["id"],
                            "admin": admin,
                        },
                    )
                )
                cost_recovery_ids.append(cost_recovery_id)

        inserted_rows = await database.fetch_all(
            select([cost_recovery]).where(cost_recovery.c.id.in_(cost_recovery_ids))
        )

        # Note that we patch CostRecovery as a unit testing hack
        cost_recoveries = [CostRecovery(**dict(cr)) for cr in inserted_rows]

        if commit_transaction:
            await database.execute(
                insert(
                    cost_recovery_log,
                    {"month": recovery_month.first_day, "admin": admin},
                )
            )
            await transaction.commit()
        else:
            await transaction.rollback()

        return cost_recoveries

    except BaseException:
        await transaction.rollback()
        raise


@router.post("/app-cost-recovery", status_code=200)
async def calc_cost_recovery_app(
    recovery_period: CostRecoveryMonth,
    _: Dict[str, str] = Depends(authenticate_usage_app),
) -> Any:
    """Route for the usage app to trigger cost recovery calculation."""
    await calc_cost_recovery(
        recovery_period, commit_transaction=True, admin=UUID(ADMIN_OID)
    )

    return {"status": "success", "detail": "cost recovery calculated"}


@router.post("/cli-cost-recovery", response_model=List[CostRecovery])
async def post_calc_cost_recovery_cli(
    recovery_month: CostRecoveryMonth, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """Route for the CLI to trigger cost recovery calculation."""
    resp = await calc_cost_recovery(
        recovery_month, commit_transaction=True, admin=user.oid
    )

    return resp


@router.get("/cli-cost-recovery", response_model=List[CostRecovery])
async def get_calc_cost_recovery_cli(
    recovery_month: CostRecoveryMonth, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """Route for the CLI to do a dry-run of the cost recovery calculation."""
    result = await calc_cost_recovery(
        recovery_month, commit_transaction=False, admin=user.oid
    )
    return result
