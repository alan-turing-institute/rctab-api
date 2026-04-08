"""Allocate some approved budget to a subscription."""

from typing import Any, List

from fastapi import Depends, HTTPException
from rctab_models.models import Allocation, AllocationListItem, UserRBAC
from sqlalchemy import insert

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.db import AsyncConnection, get_async_connection
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import (
    SubscriptionItem,
    SubscriptionSummary,
    get_allocations,
    get_subscriptions_summary,
    router,
)


async def check_allocation(conn: AsyncConnection, allocation: Allocation) -> None:
    """Check whether allocation is valid."""
    result = await conn.execute(get_subscriptions_summary(sub_id=allocation.sub_id))
    subscription_summary_row = result.mappings().first()
    if subscription_summary_row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription_summary = SubscriptionSummary(**dict(subscription_summary_row))

    if not subscription_summary.approved_to:
        raise HTTPException(
            status_code=400,
            detail="Subscription doesn't have any approvals.",
        )

    if allocation.currency != "GBP":
        raise HTTPException(
            status_code=400,
            detail="Other type of currency than GBP is not implemented yet.",
        )

    if allocation.amount == 0.0:
        raise HTTPException(
            status_code=400,
            detail="Allocation cannot be equal to zero.",
        )

    if allocation.amount > 0.0:
        unallocated_budget = (
            subscription_summary.approved - subscription_summary.allocated
        )

        if allocation.amount > unallocated_budget:
            raise HTTPException(
                status_code=400,
                detail=f"Allocation ({allocation.amount}) cannot be bigger than the unallocated budget ({unallocated_budget}).",
            )

    else:
        unused_budget = subscription_summary.allocated - subscription_summary.total_cost

        if abs(allocation.amount) > unused_budget:
            raise HTTPException(
                status_code=400,
                detail=f"Negative allocation ({abs(allocation.amount)}) cannot be bigger than the unused budget ({unused_budget}).",
            )


@router.post("/topup")
async def post_subscription_allocation(
    allocation: Allocation,
    user: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> Any:
    """Create a new allocation."""
    await check_allocation(conn, allocation)

    async with conn.begin_nested():
        await conn.execute(
            insert(accounting_models.allocations),
            {
                "subscription_id": allocation.sub_id,
                "admin": user.oid,
                "ticket": allocation.ticket,
                "amount": allocation.amount,
                "currency": allocation.currency,
            },
        )

    await send_emails.send_generic_email(
        conn,
        allocation.sub_id,
        "new_allocation.html",
        "New allocation for your Azure subscription:",
        "subscription allocation",
        allocation.model_dump(),
    )

    await refresh_desired_states(conn, user.oid, [allocation.sub_id])

    return {
        "status": "success",
        "detail": f"Allocated {allocation.amount} to {allocation.amount}",
    }


@router.get("/allocations", response_model=List[AllocationListItem])
async def get_subscription_allocations(
    subscription: SubscriptionItem,
    _: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> List[AllocationListItem]:
    """Return a list of allocations for a subscription."""
    rows = (await conn.execute(get_allocations(subscription.sub_id))).mappings().all()
    return [AllocationListItem(**dict(x)) for x in rows]
