"""Deciding who to charge for a subscription's spending."""

import calendar
import datetime
from typing import Any, List

from asyncpg import ForeignKeyViolationError
from fastapi import Depends, HTTPException
from sqlalchemy import delete, desc, insert, select, update

from rctab.crud import accounting_models
from rctab.crud.accounting_models import cost_recovery, cost_recovery_log, finance
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import Finance, FinanceWithID, UserRBAC
from rctab.routers.accounting.routes import SubscriptionItem, router


async def check_create_finance(
    new_finance: Finance,  # pylint: disable=redefined-outer-name
) -> None:
    """Check whether the new finance row is valid."""
    new_finance.date_from = get_start_month(new_finance.date_from)
    new_finance.date_to = get_end_month(new_finance.date_to)

    if new_finance.date_from > new_finance.date_to:
        raise HTTPException(
            status_code=400,
            detail=f"Date from ({str(new_finance.date_from)}) cannot be greater than date to ({str(new_finance.date_to)})",
        )

    if new_finance.amount < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Amount should not be negative but was {new_finance.amount}",
        )

    query = (
        select([cost_recovery])
        .where(cost_recovery.c.subscription_id == new_finance.subscription_id)
        .order_by(desc(cost_recovery.c.id))
    )
    last_cost_recovery = await database.fetch_one(query)
    if last_cost_recovery:
        last_cost_recovery_dict = {**dict(last_cost_recovery)}
        last_recovery_month = last_cost_recovery_dict["month"]

        # we can't add new finance row for a time period that has been recovered already
        if new_finance.date_from <= last_recovery_month:
            raise HTTPException(
                status_code=400,
                detail=f"We have already recovered costs until {str(last_cost_recovery['month'])} "
                + f"for the subscription {str(new_finance.subscription_id)}, "
                + "please choose a later start date",
            )


@router.get("/finance", response_model=List[FinanceWithID])
async def get_subscription_finances(
    subscription: SubscriptionItem, _: UserRBAC = Depends(token_admin_verified)
) -> List[FinanceWithID]:
    """Return a list of Finance objects for a subscription."""
    return [
        FinanceWithID(**dict(x))
        for x in await database.fetch_all(
            select([finance]).where(finance.c.subscription_id == subscription.sub_id)
        )
    ]


@router.post("/finances", status_code=201, response_model=FinanceWithID)
async def post_finance(
    new_finance: Finance, user: UserRBAC = Depends(token_admin_verified)
) -> FinanceWithID:
    """Create a new finance record."""
    await check_create_finance(new_finance)

    async with database.transaction():
        new_primary_key = await database.execute(
            insert(accounting_models.finance), {"admin": user.oid, **new_finance.dict()}
        )
        new_row = await database.fetch_one(
            select([finance]).where(finance.c.id == new_primary_key)
        )
        assert new_row
        newly_created_finance = FinanceWithID(**dict(new_row))

    return newly_created_finance


async def check_update_finance(new_finance: FinanceWithID) -> None:
    """Check that updating a finance row is allowed."""
    if new_finance.date_to <= new_finance.date_from:
        raise HTTPException(status_code=400, detail="date_to <= date_from")

    if new_finance.amount < 0:
        raise HTTPException(status_code=400, detail="amount < 0")

    old_finance_row = await database.fetch_one(
        select([finance]).where(finance.c.id == new_finance.id)
    )
    assert old_finance_row
    old_finance = FinanceWithID(**dict(old_finance_row))

    if old_finance.subscription_id != new_finance.subscription_id:
        raise HTTPException(status_code=400, detail="Subscription IDs should match")

    query = select([cost_recovery_log]).order_by(desc(cost_recovery_log.c.month))
    last_cost_recovery = await database.fetch_one(query)
    if last_cost_recovery:
        last_cost_recovery_dict = {**dict(last_cost_recovery)}
        last_recovery_month = last_cost_recovery_dict["month"]

        if new_finance.date_from != old_finance.date_from:
            if old_finance.date_from <= last_recovery_month:
                raise HTTPException(
                    status_code=400, detail="old.date_from has been recovered"
                )
            if new_finance.date_from <= last_recovery_month:
                raise HTTPException(
                    status_code=400, detail="new.date_from has been recovered"
                )

        if new_finance.date_to != old_finance.date_to:
            if new_finance.date_to <= last_recovery_month:
                raise HTTPException(
                    status_code=400, detail="new.date_to has been recovered"
                )
            if old_finance.date_to <= last_recovery_month:
                # Note that if old.date_to is June 30th, and we have
                # recovered June, we can still move the new.date_to
                # to July 31st.
                raise HTTPException(
                    status_code=400, detail="old.date_to has been recovered"
                )


@router.put("/finances/{finance_id}")
async def update_finance(
    finance_id: int,
    new_finance: FinanceWithID,
    user: UserRBAC = Depends(token_admin_verified),
) -> Any:
    """Update an existing Finance record."""
    assert finance_id == new_finance.id

    await check_update_finance(new_finance)

    async with database.transaction():
        await database.execute(
            update(finance)
            .where(finance.c.id == finance_id)
            .where(finance.c.subscription_id == new_finance.subscription_id)
            .values({**new_finance.dict(), **{"admin": user.oid}})
        )

    return {"status": "success", "detail": "finance updated"}


@router.get("/finances/{finance_id}", response_model=FinanceWithID)
async def get_finance(
    finance_id: int, _: UserRBAC = Depends(token_admin_verified)
) -> FinanceWithID:
    """Returns a Finance if given a finance table ID."""
    row = await database.fetch_one(select([finance]).where(finance.c.id == finance_id))
    if not row:
        raise HTTPException(status_code=404, detail="Finance not found")
    return FinanceWithID(**dict(row))


@router.delete("/finances/{finance_id}")
async def delete_finance(
    finance_id: int,
    subscription: SubscriptionItem,
    _: UserRBAC = Depends(token_admin_verified),
) -> FinanceWithID:
    """Deletes a Finance record."""
    finance_row = await database.fetch_one(
        select([finance]).where(finance.c.id == finance_id)
    )

    # Check that we recognise this finance row
    if not finance_row:
        raise HTTPException(status_code=404, detail="Finance not found")

    # Check that the finance row belongs to the subscription we think it does
    if finance_row["subscription_id"] != subscription.sub_id:
        raise HTTPException(status_code=404, detail="Subscription ID does not match")

    try:
        await database.execute(delete(finance).where(finance.c.id == finance_id))
    except ForeignKeyViolationError:
        # This is almost certainly the reason and is a more helpful message
        raise HTTPException(status_code=409, detail="Costs have already been recovered")

    return FinanceWithID(**dict(finance_row))


def get_start_month(date: datetime.date) -> datetime.date:
    """Return the start of the month of the provided date."""
    start_date = date.replace(day=1)
    return start_date


def get_end_month(date: datetime.date) -> datetime.date:
    """Return the end of the month of the provided date."""
    month_range = calendar.monthrange(date.year, date.month)
    return datetime.date(date.year, date.month, month_range[1])
