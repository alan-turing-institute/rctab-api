"""Miscellaneous queries for the accounting schema."""

import datetime
import uuid
from typing import List, Optional, Union
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import desc, func, select, true
from sqlalchemy.sql import Select

from rctab.crud.accounting_models import (
    allocations,
    approvals,
    cost_recovery,
    finance,
    persistence,
    status,
    subscription,
    subscription_details,
    usage,
    usage_view,
)
from rctab.utils import db_select

router = APIRouter()

PREFIX = "/accounting"


class SubscriptionItem(BaseModel):
    """A wrapper for a subscription id."""

    sub_id: UUID


class SubscriptionSummary(BaseModel):
    """A summary of a subscription."""

    subscription_id: UUID
    approved_from: Optional[datetime.date]
    approved_to: Optional[datetime.date]
    approved: float
    allocated: float
    cost: float
    amortised_cost: float
    total_cost: float
    first_usage: Optional[datetime.date]
    latest_usage: Optional[datetime.date]


@db_select
def get_subscriptions() -> Select:
    """Returns all subscriptions."""
    return select([subscription.c.subscription_id, subscription.c.abolished])


@db_select
def get_subscription_details(sub_id: Optional[UUID] = None) -> Select:
    """Returns latest information from subscription details."""
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    lateral = (
        select(
            [
                subscription_details.c.display_name.label("name"),
                subscription_details.c.role_assignments,
                subscription_details.c.state.label("status"),
            ]
        )
        .where(subscription_details.c.subscription_id == all_subs_sq.c.subscription_id)
        .order_by(subscription_details.c.id.desc())
        .limit(1)
        .lateral("o2")
    )

    query = select([all_subs_sq.c.subscription_id, lateral]).select_from(
        all_subs_sq.join(lateral, true(), isouter=True)
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query


@db_select
def get_sub_allocations_summary(sub_id: Optional[UUID] = None) -> Select:
    """Returns an allocations summary for subscriptions.

    Can filter by sub_id.
    """
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    query = select(
        [
            all_subs_sq.c.subscription_id,
            func.coalesce(func.sum(allocations.c.amount), 0.0).label("allocated"),
        ]
    ).select_from(
        all_subs_sq.join(
            allocations,
            all_subs_sq.c.subscription_id == allocations.c.subscription_id,
            isouter=True,
        )
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query.group_by(all_subs_sq.c.subscription_id)


@db_select
def get_sub_approvals_summary(sub_id: Optional[UUID] = None) -> Select:
    """Get total approved amount for each subscription.

    If there are no approvals budget amount will be shown as 0.

    Args:
        sub_id: Filter by a single subscription. Defaults to None.

    Returns:
        A SELECT query to get the approved amount and time
        period for each subscription.
    """
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    query = select(
        [
            all_subs_sq.c.subscription_id,
            func.min(approvals.c.date_from).label("approved_from"),
            func.max(approvals.c.date_to).label("approved_to"),
            func.coalesce(func.sum(approvals.c.amount), 0.0).label("approved"),
        ]
    ).select_from(
        all_subs_sq.join(
            approvals,
            all_subs_sq.c.subscription_id == approvals.c.subscription_id,
            isouter=True,
        )
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query.group_by(
        all_subs_sq.c.subscription_id,
    )


@db_select
def get_sub_usage_summary(
    sub_id: Optional[UUID] = None,
) -> Select:
    """Summarise usage for subscriptions.

    Args:
        sub_id: Filter by sub_id. Defaults to None.
    """
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    query = select(
        [
            all_subs_sq.c.subscription_id,
            usage_view.c.first_usage,
            usage_view.c.latest_usage,
            func.coalesce(usage_view.c.total_cost, 0.0).label("total_cost"),
            func.coalesce(usage_view.c.amortised_cost, 0.0).label("amortised_cost"),
            func.coalesce(usage_view.c.cost, 0.0).label("cost"),
        ]
    ).select_from(
        all_subs_sq.join(
            usage_view,
            all_subs_sq.c.subscription_id == usage_view.c.subscription_id,
            isouter=True,
        )
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query


@db_select
def sub_persistency_status(sub_id: Optional[UUID] = None) -> Select:
    """Returns the latest value of the always_on record for a subscription."""
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    lateral = (
        select([persistence.c.always_on])
        .where(persistence.c.subscription_id == all_subs_sq.c.subscription_id)
        .order_by(persistence.c.id.desc())
        .limit(1)
        .lateral("o2")
    )

    query = select([all_subs_sq.c.subscription_id, lateral]).select_from(
        all_subs_sq.join(lateral, true(), isouter=True)
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query


@db_select
def get_desired_status(sub_id: Optional[Union[UUID, List[UUID]]] = None) -> Select:
    """Returns the latest value of the desired status record for a subscription."""
    # pylint: disable=unexpected-keyword-arg
    all_subs_sq = get_subscriptions(execute=False).alias()

    lateral = (
        select(
            [
                status.c.active.label("desired_status"),
                status.c.reason.label("desired_status_info"),
            ]
        )
        .where(status.c.subscription_id == all_subs_sq.c.subscription_id)
        .order_by(status.c.id.desc())
        .limit(1)
        .lateral("o2")
    )

    query = select([all_subs_sq.c.subscription_id, lateral]).select_from(
        all_subs_sq.join(lateral, true(), isouter=True)
    )

    if sub_id:
        if isinstance(sub_id, uuid.UUID):
            query = query.where(all_subs_sq.c.subscription_id == str(sub_id))
        elif isinstance(sub_id, list):
            query = query.where(
                all_subs_sq.c.subscription_id.in_([str(i) for i in sub_id])
            )
        else:
            raise TypeError(
                f"sub_id must be type UUID or List[UUID]. Received {type(sub_id)}",
            )

    return query


# pylint: disable=unexpected-keyword-arg
@db_select
def get_subscriptions_summary(
    sub_id: Optional[UUID] = None,
) -> Select:
    """Returns a summary of one or all subscriptions."""
    # Get all subscriptions
    all_subs_sq = get_subscriptions(execute=False).alias()

    # Get all subscription details
    all_details_sq = get_subscription_details(execute=False).alias()

    # Get desired subscription status
    all_desired_status_sq = get_desired_status(execute=False).alias()

    # Get all usage
    all_usage_sq = get_sub_usage_summary(execute=False).alias()

    # Get all approval summary
    all_approvals_sq = get_sub_approvals_summary(execute=False).alias()

    # Get all allocations
    all_allocations_sq = get_sub_allocations_summary(execute=False).alias()

    all_persistence_sq = sub_persistency_status(execute=False).alias()

    query = select(
        [
            all_subs_sq.c.subscription_id,
            all_subs_sq.c.abolished,
            all_details_sq.c.name,
            all_details_sq.c.role_assignments,
            all_details_sq.c.status,
            all_approvals_sq.c.approved_from,
            all_approvals_sq.c.approved_to,
            all_approvals_sq.c.approved,
            all_allocations_sq.c.allocated,
            all_usage_sq.c.cost,
            all_usage_sq.c.amortised_cost,
            all_usage_sq.c.total_cost,
            all_usage_sq.c.first_usage,
            all_usage_sq.c.latest_usage,
            all_persistence_sq.c.always_on,
            all_desired_status_sq.c.desired_status,
            all_desired_status_sq.c.desired_status_info,
        ]
    ).select_from(
        all_subs_sq.join(
            all_details_sq,
            all_subs_sq.c.subscription_id == all_details_sq.c.subscription_id,
            isouter=True,
        )
        .join(
            all_usage_sq,
            all_subs_sq.c.subscription_id == all_usage_sq.c.subscription_id,
            isouter=True,
        )
        .join(
            all_approvals_sq,
            all_subs_sq.c.subscription_id == all_approvals_sq.c.subscription_id,
            isouter=True,
        )
        .join(
            all_allocations_sq,
            all_subs_sq.c.subscription_id == all_allocations_sq.c.subscription_id,
            isouter=True,
        )
        .join(
            all_persistence_sq,
            all_subs_sq.c.subscription_id == all_persistence_sq.c.subscription_id,
            isouter=True,
        )
        .join(
            all_desired_status_sq,
            all_subs_sq.c.subscription_id == all_desired_status_sq.c.subscription_id,
            isouter=True,
        )
    )

    if sub_id:
        query = query.where(all_subs_sq.c.subscription_id == str(sub_id))

    return query


@db_select
def get_subscriptions_with_disable(
    sub_id: Optional[UUID] = None,
) -> Select:
    """Get a query summarising the subscription and its remaining budget."""
    # pylint: disable unexpected-keyword-arg
    subscription_summary_sq = get_subscriptions_summary(
        sub_id=sub_id, execute=False
    ).alias()

    return select(
        [
            subscription_summary_sq,
            (
                subscription_summary_sq.c.allocated
                - subscription_summary_sq.c.total_cost
            ).label("remaining"),
        ]
    )


@db_select
def get_total_usage(
    start_date: Optional[datetime.date] = None, end_date: Optional[datetime.date] = None
) -> Select:
    """Get the total usage on the system between start_date and end_date.

    Args:
        start_date (datetime.date): First date to request usage for
        end_date (datetime.date): Last date (exclusive) to request usage for

    Returns:
        Select: [description]
    """
    query = select(
        [
            func.min(usage_view.c.first_usage).label("first_usage"),
            func.max(usage_view.c.latest_usage).label("latest_usage"),
            func.sum(usage_view.c.cost).label("cost"),
            func.sum(usage_view.c.amortised_cost).label("amortised_cost"),
            func.sum(usage_view.c.total_cost).label("total_cost"),
        ]
    )

    if start_date:
        query = query.where(usage_view.c.date >= start_date)

    if end_date:
        query = query.where(usage_view.c.date < end_date)

    return query


@db_select
def get_allocations(sub_id: UUID) -> Select:
    """Get all allocations for a subscription."""
    return (
        select(
            [
                allocations.c.ticket,
                allocations.c.amount,
                allocations.c.currency,
                allocations.c.time_created,
            ]
        )
        .where(allocations.c.subscription_id == sub_id)
        .order_by(desc(allocations.c.time_created))
    )


@db_select
def get_approvals(sub_id: UUID) -> Select:
    """Get all approvals for a subscription."""
    return (
        select(
            [
                approvals.c.ticket,
                approvals.c.amount,
                approvals.c.currency,
                approvals.c.date_from,
                approvals.c.date_to,
                approvals.c.time_created,
            ]
        )
        .where(approvals.c.subscription_id == sub_id)
        .order_by(desc(approvals.c.date_to))
    )


@db_select
def get_finance(sub_id: UUID) -> Select:
    """Get all finance items."""
    return (
        select(
            [
                finance.c.ticket,
                finance.c.amount,
                finance.c.priority,
                finance.c.finance_code,
                finance.c.date_from,
                finance.c.date_to,
                finance.c.time_created,
            ]
        )
        .where(finance.c.subscription_id == sub_id)
        .order_by(desc(finance.c.date_to))
    )


@db_select
def get_costrecovery(sub_id: UUID) -> Select:
    """Get all cost recovery items for a subscription in asc date order."""
    # order by month asc
    return (
        select(
            [
                cost_recovery.c.subscription_id,
                cost_recovery.c.finance_id,
                cost_recovery.c.month,
                cost_recovery.c.finance_code,
                cost_recovery.c.amount,
                cost_recovery.c.date_recovered,
            ]
        )
        .where(cost_recovery.c.subscription_id == sub_id)
        .order_by(desc(cost_recovery.c.month))
    )


@db_select
def get_usage(sub_id: UUID, target_date: datetime.datetime) -> Select:
    """Get all of the usage items."""
    return (
        select(
            [
                usage.c.id,
                usage.c.name,
                usage.c.type,
                usage.c.tags,
                usage.c.billing_account_id,
                usage.c.billing_account_name,
                usage.c.billing_period_start_date,
                usage.c.billing_period_end_date,
                usage.c.billing_profile_id,
                usage.c.billing_profile_name,
                usage.c.account_owner_id,
                usage.c.account_name,
                usage.c.subscription_id,
                usage.c.subscription_name,
                usage.c.date,
                usage.c.product,
                usage.c.part_number,
                usage.c.meter_id,
                usage.c.quantity,
                usage.c.effective_price,
                usage.c.cost,
                usage.c.amortised_cost,
                usage.c.total_cost,
                usage.c.unit_price,
                usage.c.billing_currency,
                usage.c.resource_location,
                usage.c.consumed_service,
                usage.c.resource_id,
                usage.c.resource_name,
                usage.c.service_info1,
                usage.c.service_info2,
                usage.c.additional_info,
                usage.c.invoice_section,
                usage.c.cost_center,
                usage.c.resource_group,
                usage.c.reservation_id,
                usage.c.reservation_name,
                usage.c.product_order_id,
                usage.c.offer_id,
                usage.c.is_azure_credit_eligible,
                usage.c.term,
                usage.c.publisher_name,
                usage.c.publisher_type,
                usage.c.plan_name,
                usage.c.charge_type,
                usage.c.frequency,
                usage.c.monthly_upload,
            ]
        )
        .where((usage.c.subscription_id == sub_id) & (usage.c.date >= target_date))
        .order_by(
            desc(usage.c.date),
        )
    )


@db_select
def get_subscription_name(sub_id: Optional[UUID] = None) -> Select:
    """Make a query to find the display name(s) of a subscription.

    Args:
        sub_id: A subscription id.

    Returns:
        A SELECT query for all current and former names of the subscription.
    """
    return select([subscription_details.c.display_name.label("name")]).where(
        subscription_details.c.subscription_id == sub_id
    )
