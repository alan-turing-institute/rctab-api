"""Mark subscriptions as "abolished" if they have been inactive for >90 days."""

import logging
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import UUID

from rctab_models.models import DEFAULT_CURRENCY, SubscriptionState
from sqlalchemy import and_, func, insert, select

from rctab.constants import ABOLISHMENT_ADJUSTMENT_MSG, ADJUSTMENT_DELTA
from rctab.crud.accounting_models import allocations as allocations_table
from rctab.crud.accounting_models import approvals as approvals_table
from rctab.crud.accounting_models import emails, failed_emails
from rctab.crud.accounting_models import subscription as subscription_table
from rctab.crud.accounting_models import subscription_details
from rctab.db import AsyncConnection
from rctab.routers.accounting.routes import get_subscriptions_summary
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    send_with_sendgrid,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)


class AbolishmentAdjustment(TypedDict):
    """Abolishment adjustment summary for one subscription."""

    subscription_id: UUID
    name: str | None
    allocation: float
    approval: float


async def get_inactive_subs(conn: AsyncConnection) -> list[UUID]:
    """Returns subscriptions inactive for more than 90 days and not yet abolished."""
    ninety_days_ago = datetime.now() - timedelta(days=90)

    latest_detail_sq = (
        select(
            subscription_details.c.subscription_id,
            func.max(subscription_details.c.time_created).label("time_created"),
        ).group_by(subscription_details.c.subscription_id)
    ).alias()

    latest_details = subscription_details.join(
        latest_detail_sq,
        and_(
            latest_detail_sq.c.subscription_id
            == subscription_details.c.subscription_id,
            latest_detail_sq.c.time_created == subscription_details.c.time_created,
        ),
    ).join(
        subscription_table,
        latest_detail_sq.c.subscription_id == subscription_table.c.subscription_id,
    )

    result = await conn.execute(
        select(subscription_details.c.subscription_id)
        .select_from(latest_details)
        .where(
            and_(
                subscription_details.c.time_created < ninety_days_ago,
                subscription_details.c.state == SubscriptionState.DISABLED,
                subscription_table.c.abolished.is_(False),
            )
        )
    )
    rows = result.mappings().all()
    return [row["subscription_id"] for row in rows]


async def adjust_budgets_to_zero(
    conn: AsyncConnection, admin_oid: UUID, sub_ids: list[UUID]
) -> list[AbolishmentAdjustment]:
    """Adjust allocation and approval totals to align with usage totals."""
    adjustments: list[AbolishmentAdjustment] = []

    if not sub_ids:
        return adjustments

    sub_query = get_subscriptions_summary().alias()
    summaries = select(sub_query).where(
        sub_query.c.subscription_id.in_([str(sub_id) for sub_id in sub_ids])
    )

    result = await conn.execute(summaries)
    for row in result.mappings().all():
        allocation_diff = row["total_cost"] - row["allocated"]
        approval_diff = row["total_cost"] - row["approved"]

        if row["approved_from"]:
            if abs(allocation_diff) >= ADJUSTMENT_DELTA:
                await conn.execute(
                    allocations_table.insert().values(
                        subscription_id=row["subscription_id"],
                        admin=admin_oid,
                        ticket=ABOLISHMENT_ADJUSTMENT_MSG,
                        amount=allocation_diff,
                        currency=DEFAULT_CURRENCY,
                    )
                )

            if abs(approval_diff) >= ADJUSTMENT_DELTA:
                await conn.execute(
                    approvals_table.insert().values(
                        subscription_id=row["subscription_id"],
                        admin=admin_oid,
                        ticket=ABOLISHMENT_ADJUSTMENT_MSG,
                        amount=approval_diff,
                        currency=DEFAULT_CURRENCY,
                        date_from=row["approved_from"],
                        date_to=row["approved_to"],
                    )
                )

        adjustments.append(
            {
                "subscription_id": row["subscription_id"],
                "name": row["name"],
                "allocation": allocation_diff,
                "approval": approval_diff,
            }
        )

    return adjustments


async def set_abolished_flag(conn: AsyncConnection, sub_ids: list[UUID]) -> None:
    """Set the abolished flag to true for the given subscriptions."""
    if not sub_ids:
        return

    await conn.execute(
        subscription_table.update()
        .where(
            subscription_table.c.subscription_id.in_(
                [str(sub_id) for sub_id in sub_ids]
            )
        )
        .values(abolished=True)
    )


async def send_abolishment_email(
    conn: AsyncConnection,
    recipients: list[str],
    adjustments: list[AbolishmentAdjustment],
) -> None:
    """Send abolishment summary email and record the result."""
    template_name = "abolishment.html"
    template_data = {"abolishments": adjustments}
    subject = "Abolishment of subscriptions"

    if recipients:
        try:
            status = send_with_sendgrid(
                subject, template_name, template_data, recipients
            )
            logger.warning("Abolishment emails sent with status %s", status)
            await conn.execute(
                insert(emails).values(
                    {
                        "status": status,
                        "type": "abolishment",
                        "recipients": ";".join(recipients),
                    }
                )
            )
            logger.warning("Sent an email to %s with subject=%s", recipients, subject)
        except MissingEmailParamsError as error:
            result = await conn.execute(
                insert(failed_emails)
                .values(
                    {
                        "subscription_id": UUID(int=0),
                        "type": subject,
                        "subject": error.subject,
                        "recipients": ";".join(error.recipients),
                        "from_email": error.from_email,
                        "message": error.message,
                    }
                )
                .returning(failed_emails.c.id)
            )
            logger.error(
                "'%s' email failed to send due to missing "
                "api_key or send email address.\n"
                "It has been logged in the 'failed_emails' table with id=%s.\n"
                "Use 'get_failed_emails.py' to retrieve it to send manually.",
                subject,
                result.scalar_one_or_none(),
            )
    else:
        logger.warning("Nobody to send abolishments email to.")


async def abolish_subscriptions(conn: AsyncConnection, admin_oid: UUID) -> None:
    """Abolish subscriptions that have been inactive for more than 90 days."""
    inactive_subs = await get_inactive_subs(conn)
    if not inactive_subs:
        return

    adjustments = await adjust_budgets_to_zero(conn, admin_oid, inactive_subs)
    await set_abolished_flag(conn, inactive_subs)

    recipients = get_settings().admin_email_recipients
    await send_abolishment_email(conn, recipients, adjustments)
