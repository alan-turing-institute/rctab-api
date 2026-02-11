"""Deciding who to charge for a subscription's spending."""

import calendar
import datetime
from typing import Any, List

from fastapi import Depends, HTTPException
from rctab_models.models import Finance, FinanceWithID, UserRBAC
from sqlalchemy import delete, desc, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud import accounting_models
from rctab.crud.accounting_models import cost_recovery, cost_recovery_log, finance
from rctab.crud.auth import token_admin_verified
from rctab.db import get_async_connection
from rctab.routers.accounting.routes import SubscriptionItem, router


async def check_create_finance(
    new_finance: Finance,  # pylint: disable=redefined-outer-name
    conn: AsyncConnection,
) -> Finance:
    """Check whether the new finance row is valid."""
    normalized_finance = Finance(**new_finance.model_dump())
    normalized_finance.date_from = get_start_month(normalized_finance.date_from)
    normalized_finance.date_to = get_end_month(normalized_finance.date_to)

    if normalized_finance.date_from > normalized_finance.date_to:
        raise HTTPException(
            status_code=400,
            detail=f"Date from ({str(normalized_finance.date_from)}) cannot be greater than date to ({str(normalized_finance.date_to)})",
        )

    if normalized_finance.amount < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Amount should not be negative but was {normalized_finance.amount}",
        )

    query = (
        select(cost_recovery)
        .where(cost_recovery.c.subscription_id == normalized_finance.subscription_id)
        .order_by(desc(cost_recovery.c.id))
    )
    last_cost_recovery = (await conn.execute(query)).mappings().first()
    if last_cost_recovery:
        last_cost_recovery_dict = {**dict(last_cost_recovery)}
        last_recovery_month = last_cost_recovery_dict["month"]

        # we can't add new finance row for a time period that has been recovered already
        if normalized_finance.date_from <= last_recovery_month:
            raise HTTPException(
                status_code=400,
                detail=f"We have already recovered costs until {str(last_cost_recovery['month'])} "
                + f"for the subscription {str(normalized_finance.subscription_id)}, "
                + "please choose a later start date",
            )
    return normalized_finance


@router.get("/finance", response_model=List[FinanceWithID])
async def get_subscription_finances(
    subscription: SubscriptionItem,
    _: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> List[FinanceWithID]:
    """Return a list of Finance objects for a subscription."""
    rows = (
        (
            await conn.execute(
                select(finance).where(finance.c.subscription_id == subscription.sub_id)
            )
        )
        .mappings()
        .all()
    )
    return [FinanceWithID(**dict(x)) for x in rows]


@router.post("/finances", status_code=201, response_model=FinanceWithID)
async def post_finance(
    new_finance: Finance,
    user: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> FinanceWithID:
    """Create a new finance record."""
    normalized_finance = await check_create_finance(new_finance, conn)

    async with conn.begin_nested():
        new_primary_key = (
            await conn.execute(
                insert(accounting_models.finance)
                .values({"admin": user.oid, **normalized_finance.model_dump()})
                .returning(finance.c.id)
            )
        ).scalar_one()
        new_row = (
            (await conn.execute(select(finance).where(finance.c.id == new_primary_key)))
            .mappings()
            .first()
        )
        assert new_row
        newly_created_finance = FinanceWithID(**dict(new_row))

    return newly_created_finance


async def check_update_finance(
    new_finance: FinanceWithID, conn: AsyncConnection
) -> None:
    """Check that updating a finance row is allowed."""
    if new_finance.date_to <= new_finance.date_from:
        raise HTTPException(status_code=400, detail="date_to <= date_from")

    if new_finance.amount < 0:
        raise HTTPException(status_code=400, detail="amount < 0")

    old_finance_row = (
        (await conn.execute(select(finance).where(finance.c.id == new_finance.id)))
        .mappings()
        .first()
    )
    assert old_finance_row
    old_finance = FinanceWithID(**dict(old_finance_row))

    if old_finance.subscription_id != new_finance.subscription_id:
        raise HTTPException(status_code=400, detail="Subscription IDs should match")

    query = select(cost_recovery_log).order_by(desc(cost_recovery_log.c.month))
    last_cost_recovery = (await conn.execute(query)).mappings().first()
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
    conn: AsyncConnection = Depends(get_async_connection),
) -> Any:
    """Update an existing Finance record."""
    assert finance_id == new_finance.id

    await check_update_finance(new_finance, conn)

    async with conn.begin_nested():
        await conn.execute(
            update(finance)
            .where(finance.c.id == finance_id)
            .where(finance.c.subscription_id == new_finance.subscription_id)
            .values({**new_finance.model_dump(), **{"admin": user.oid}})
        )

    return {"status": "success", "detail": "finance updated"}


@router.get("/finances/{finance_id}", response_model=FinanceWithID)
async def get_finance(
    finance_id: int,
    _: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> FinanceWithID:
    """Returns a Finance if given a finance table ID."""
    row = (
        (await conn.execute(select(finance).where(finance.c.id == finance_id)))
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Finance not found")
    return FinanceWithID(**dict(row))


@router.delete("/finances/{finance_id}")
async def delete_finance(
    finance_id: int,
    subscription: SubscriptionItem,
    _: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> FinanceWithID:
    """Deletes a Finance record."""
    finance_row = (
        (await conn.execute(select(finance).where(finance.c.id == finance_id)))
        .mappings()
        .first()
    )

    # Check that we recognise this finance row
    if not finance_row:
        raise HTTPException(status_code=404, detail="Finance not found")

    # Check that the finance row belongs to the subscription we think it does
    if finance_row["subscription_id"] != subscription.sub_id:
        raise HTTPException(status_code=404, detail="Subscription ID does not match")

    try:
        await conn.execute(delete(finance).where(finance.c.id == finance_id))
    except IntegrityError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "23503":
            # Foreign key violation; this finance row has related cost_recovery rows.
            raise HTTPException(
                status_code=409, detail="Costs have already been recovered"
            ) from exc
        raise

    return FinanceWithID(**dict(finance_row))


def get_start_month(date: datetime.date) -> datetime.date:
    """Return the start of the month of the provided date."""
    start_date = date.replace(day=1)
    return start_date


def get_end_month(date: datetime.date) -> datetime.date:
    """Return the end of the month of the provided date."""
    month_range = calendar.monthrange(date.year, date.month)
    return datetime.date(date.year, date.month, month_range[1])
