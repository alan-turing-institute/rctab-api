import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, insert, select

from rctab.constants import ABOLISHMENT_ADJUSTMENT_MSG, ADJUSTMENT_DELTA
from rctab.crud.accounting_models import allocations as allocations_table
from rctab.crud.accounting_models import approvals as approvals_table
from rctab.crud.accounting_models import emails, failed_emails
from rctab.crud.accounting_models import subscription as subscription_table
from rctab.crud.accounting_models import subscription_details
from rctab.crud.models import database
from rctab.crud.schema import DEFAULT_CURRENCY, SubscriptionState
from rctab.routers.accounting.routes import get_subscriptions_summary
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    send_with_sendgrid,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)


async def get_inactive_subs() -> Optional[List[UUID]]:
    """Returns a list of subscriptions which have been inactive for more than 90 days."""
    ninety_days_ago = datetime.now() - timedelta(days=90)

    # The most recent time_created for each subscription's subscription_detail
    query_1 = (
        select(
            [
                subscription_details.c.subscription_id,
                func.max(subscription_details.c.time_created).label("time_created"),
            ]
        ).group_by(subscription_details.c.subscription_id)
    ).alias()

    # The most recent subscription_detail for each subscription
    query_2 = subscription_details.join(
        query_1,
        and_(
            query_1.c.subscription_id == subscription_details.c.subscription_id,
            query_1.c.time_created == subscription_details.c.time_created,
        ),
    ).join(
        subscription_table,
        query_1.c.subscription_id == subscription_table.c.subscription_id,
    )

    # subscriptions that have been inactive for more than 90 days
    # and have not been abolished yet
    query_2_result = await database.fetch_all(
        select([subscription_details.c.subscription_id])
        .select_from(query_2)
        .where(
            and_(
                subscription_details.c.time_created < ninety_days_ago,
                subscription_details.c.state == SubscriptionState.DISABLED,
                subscription_table.c.abolished.is_(False),
            )
        )
    )

    return [i["subscription_id"] for i in query_2_result]


async def adjust_budgets_to_zero(admin_oid: UUID, sub_ids: List[UUID]) -> List[dict]:
    """Adjusts allocation and approval budgets to zero for the given subscriptions."""
    adjustments: List = []

    if not sub_ids:
        return adjustments

    sub_query = get_subscriptions_summary(execute=False).alias()

    summaries = (
        select([sub_query])
        .where(sub_query.c.subscription_id.in_([str(sub_id) for sub_id in sub_ids]))
        .alias()
    )

    # Adjusting approvals and allocations for subscriptions
    for row in await database.fetch_all(summaries):

        allocation_diff = row["total_cost"] - row["allocated"]
        approval_diff = row["total_cost"] - row["approved"]

        # Only negate allocations and approvals if there is at least one approval
        if row["approved_from"]:

            if abs(allocation_diff) >= ADJUSTMENT_DELTA:
                insert_allocation = allocations_table.insert().values(
                    subscription_id=row["subscription_id"],
                    admin=admin_oid,
                    ticket=ABOLISHMENT_ADJUSTMENT_MSG,
                    amount=allocation_diff,
                    currency=DEFAULT_CURRENCY,
                )
                await database.execute(insert_allocation)

            if abs(approval_diff) >= ADJUSTMENT_DELTA:
                insert_approval = approvals_table.insert().values(
                    subscription_id=row["subscription_id"],
                    admin=admin_oid,
                    ticket=ABOLISHMENT_ADJUSTMENT_MSG,
                    amount=approval_diff,
                    currency=DEFAULT_CURRENCY,
                    date_from=row["approved_from"],
                    date_to=row["approved_to"],
                )
                await database.execute(insert_approval)

        adjustments.append(
            {
                "subscription_id": row["subscription_id"],
                "name": row["name"],
                "allocation": allocation_diff,
                "approval": approval_diff,
            }
        )

    return adjustments


async def set_abolished_flag(sub_ids: List[UUID]) -> None:
    """Sets the abolished flag to true for the given subscriptions."""
    if sub_ids is None or len(sub_ids) < 1:
        return

    query = (
        subscription_table.update()
        .where(
            subscription_table.c.subscription_id.in_(
                [str(sub_id) for sub_id in sub_ids]
            )
        )
        .values(abolished=True)
    )

    await database.execute(query)


async def send_abolishment_email(
    recipients: List[str], adjustments: List[dict]
) -> None:
    """Sends an email to the given recipients with the given adjustments.

    Items in the jinja2 template are replaced with those in template_data.
    """
    template_name = "abolishment.html"
    template_data = {"abolishments": adjustments}
    subject = "Abolishment of subscriptions"

    if recipients:
        try:
            status = send_with_sendgrid(
                subject,
                template_name,
                template_data,
                recipients,
            )
            logger.warning("Abolishment emails sent with status %s", status)
            insert_statement = insert(emails).values(
                {
                    "status": status,
                    "type": "abolishment",
                    "recipients": ";".join(recipients),
                }
            )
            await database.execute(insert_statement)
            logger.warning("Sent an email to %s with subject=%s", recipients, subject)
        except MissingEmailParamsError as error:
            insert_statement = (
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
            row = await database.execute(insert_statement)
            logger.error(
                "'%s' email failed to send due to missing "
                "api_key or send email address.\n"
                "It has been logged in the 'failed_emails' table with id=%s.\n"
                "Use 'get_failed_emails.py' to retrieve it to send manually.",
                subject,
                row,
            )
    else:
        logger.warning("Nobody to send abolishments email to.")


async def abolish_subscriptions(admin_oid: UUID) -> None:
    """Abolishes subscriptions that have been inactive for more than 90 days."""
    # find subscriptions which have been inactive for more than 90 days
    inactive_subs = await get_inactive_subs()

    if not inactive_subs:
        return

    # adjust budgets to zero for inactive subscriptions
    adjustments = await adjust_budgets_to_zero(admin_oid, inactive_subs)

    # set the abolish flag to true for these subscriptions
    await set_abolished_flag(inactive_subs)

    # send an email to the admins
    recipients = get_settings().admin_email_recipients
    await send_abolishment_email(recipients, adjustments)
