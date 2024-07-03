"""Allocate some approved budget to a subscription."""

from typing import Any, List

from fastapi import Depends, HTTPException
from sqlalchemy import insert

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import Allocation, AllocationListItem, UserRBAC
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import (
    SubscriptionItem,
    SubscriptionSummary,
    get_allocations,
    get_subscriptions_summary,
    router,
)


async def check_allocation(allocation: Allocation) -> None:
    """Check whether allocation is valid."""
    # Get complete summary of subscription
    subscription_summary = await get_subscriptions_summary(sub_id=allocation.sub_id)

    # Get the first row (should only be one)
    # pylint: disable=protected-access
    subscription_summary = SubscriptionSummary(**subscription_summary[0]._mapping)
    # pylint: enable=protected-access

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
    allocation: Allocation, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """Create a new allocation."""
    await check_allocation(allocation)

    async with database.transaction():
        await database.execute(
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
        database,
        allocation.sub_id,
        "new_allocation.html",
        "New allocation for your Azure subscription:",
        "subscription allocation",
        allocation.dict(),
    )

    await refresh_desired_states(user.oid, [allocation.sub_id])

    return {
        "status": "success",
        "detail": f"Allocated {allocation.amount} to {allocation.amount}",
    }


@router.get("/allocations", response_model=List[AllocationListItem])
async def get_subscription_allocations(
    subscription: SubscriptionItem, _: UserRBAC = Depends(token_admin_verified)
) -> List[AllocationListItem]:
    """Return a list of allocations for a subscription."""
    rows = await get_allocations(subscription.sub_id)
    return [AllocationListItem(**dict(x)) for x in rows]
