"""Set and fetch approvals for subscriptions."""

import datetime
from datetime import timedelta
from typing import Any, List

from fastapi import Depends, HTTPException
from sqlalchemy import insert

from rctab.constants import EMAIL_TYPE_SUB_APPROVAL
from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import Approval, ApprovalListItem, UserRBAC
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import (
    SubscriptionItem,
    SubscriptionSummary,
    get_approvals,
    get_subscriptions_summary,
    router,
)


def check_positive_approval(
    approval: Approval,
    subscription_summary: SubscriptionSummary,
) -> None:
    """Checks whether a non-negative approval is valid."""
    if not approval.force:
        # After a subscription is cancelled, Microsoft waits 30 - 90 days before
        # permanently deleting it. This check ensures that you are not approving
        # a subscription that has already been cancelled for more than 30 days.
        if approval.date_from < datetime.date.today() - timedelta(days=30):
            raise HTTPException(
                status_code=400,
                detail=f"Date from ({str(approval.date_from)}) cannot be more than 30 days in the past. "
                "This check ensures that you are not approving a subscription that has already been cancelled "
                "for more than 30 days.",
            )

    if subscription_summary.approved_to:
        # Approval cannot end earlier than the latest existing approval
        if approval.date_to < subscription_summary.approved_to:
            raise HTTPException(
                status_code=400,
                detail=f"Date to ({str(approval.date_to)}) should be equal or greater than ({str(subscription_summary.approved_to)})",
            )

        # Approval cannot start after latest existing approval
        if approval.date_from > subscription_summary.approved_to:
            raise HTTPException(
                status_code=400,
                detail=f"Date from ({str(approval.date_from)}) should be equal or less than ({str(subscription_summary.approved_to)})",
            )


def check_negative_approval(
    approval: Approval,
    subscription_summary: SubscriptionSummary,
) -> None:
    """Checks whether a negative approval is valid."""
    if not subscription_summary.approved_to:
        raise HTTPException(
            status_code=400,
            detail="Cannot create a negative approval for non-existent budget.",
        )

    if (
        approval.date_from != subscription_summary.approved_from
        or approval.date_to != subscription_summary.approved_to
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Dates from and to ({str(approval.date_from)} - {str(approval.date_to)}) "
                f"must align with the min-max ({str(subscription_summary.approved_from)} - "
                f"{str(subscription_summary.approved_to)}) approval period."
            ),
        )

    # Check reduction is not more than unused budget
    unused_budget = subscription_summary.approved - subscription_summary.total_cost
    if unused_budget < abs(approval.amount):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The amount of unused budget ({unused_budget}) is less than the "
                f"negative allocation ({abs(approval.amount)}). "
                f"Can only remove ({subscription_summary.approved - subscription_summary.allocated})."
            ),
        )

    unallocated_budget = subscription_summary.approved - subscription_summary.allocated
    unallocated_budget -= approval.amount if approval.allocate else 0
    if unallocated_budget < abs(approval.amount):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The amount of unallocated_budget budget ({unallocated_budget})"
                f" is less than the negative allocation ({abs(approval.amount)})."
            ),
        )


async def check_approval(approval: Approval) -> None:
    """Checks whether approval is valid."""
    # Get complete summary of subscription
    subscription_summary = await get_subscriptions_summary(sub_id=approval.sub_id)

    # Get the first row (should only be one)
    # pylint: disable=protected-access
    subscription_summary = SubscriptionSummary(**subscription_summary[0]._mapping)
    # pylint: enable=protected-access

    current_date = datetime.date.today()

    if approval.date_to < current_date:
        raise HTTPException(
            status_code=400,
            detail=f"Date to ({str(approval.date_to)}) cannot be in the past",
        )

    if approval.date_from > approval.date_to:
        raise HTTPException(
            status_code=400,
            detail=f"Date from ({str(approval.date_from)}) cannot be greater than date to ({str(approval.date_to)})",
        )

    if approval.currency != "GBP":
        raise HTTPException(
            status_code=400,
            detail="Other type of currency than GBP is not implemented yet.",
        )

    if approval.amount >= 0.0:
        check_positive_approval(approval, subscription_summary)
    else:
        check_negative_approval(approval, subscription_summary)


@router.get("/approvals", response_model=List[ApprovalListItem])
async def get_subscription_approvals(
    subscription: SubscriptionItem, _: UserRBAC = Depends(token_admin_verified)
) -> List[ApprovalListItem]:
    """Returns a list approvals for a subscription."""
    rows = await get_approvals(subscription.sub_id)
    return [ApprovalListItem(**dict(x)) for x in rows]


@router.post("/approve", status_code=200)
async def post_approval(
    approval: Approval, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """Creates a new approval.

    If the allocate flag is on, a corresponding allocation entry is created as well.
    """
    await check_approval(approval)

    async with database.transaction():
        if approval.force:
            ticket = approval.ticket + " (forced)"
        else:
            ticket = approval.ticket

        await database.execute(
            insert(accounting_models.approvals),
            {
                "subscription_id": approval.sub_id,
                "admin": user.oid,
                "ticket": ticket,
                "amount": approval.amount,
                "currency": approval.currency,
                "date_from": approval.date_from,
                "date_to": approval.date_to,
            },
        )

        if approval.allocate:
            await database.execute(
                insert(accounting_models.allocations),
                {
                    "subscription_id": approval.sub_id,
                    "admin": user.oid,
                    "ticket": approval.ticket,
                    "amount": approval.amount,
                    "currency": approval.currency,
                },
            )

    await send_emails.send_generic_email(
        database,
        approval.sub_id,
        "new_approval.html",
        "New approval for your Azure subscription:",
        EMAIL_TYPE_SUB_APPROVAL,
        approval.dict(),
    )

    await refresh_desired_states(user.oid, [approval.sub_id])

    return {"status": "success", "detail": "approval created"}
