"""Background tasks that run daily."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, insert, select

from rctab.constants import EMAIL_TYPE_SUMMARY
from rctab.crud.accounting_models import emails, failed_emails
from rctab.crud.models import database
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    prepare_summary_email,
    send_with_sendgrid,
)

logger = logging.getLogger(__name__)


async def send_summary_email(
    recipients: List[str], since_this_datetime: Optional[datetime] = None
) -> None:
    """Sends a summary email to the addresses in the recipients list.

    The summary email contains information about:
    - new subscriptions
    - status changes of subscriptions
    - notification emails sent
    within from the `since_this_datetime` until now.

    Items in the jinja2 template are replaced with those in template_data.

    Args:
        recipients : The email addresses to send summary emails to.
        since_this_datetime : Include information since this date and time, by default None.
    """
    # pylint: disable=invalid-name
    template_name = "daily_summary.html"
    template_data = await prepare_summary_email(database, since_this_datetime)
    subject = "Daily summary"
    if recipients:
        try:
            status = send_with_sendgrid(
                subject,
                template_name,
                template_data,
                recipients,
            )
            insert_statement = insert(emails).values(
                {
                    "status": status,
                    "type": EMAIL_TYPE_SUMMARY,
                    "recipients": ";".join(recipients),
                }
            )
            await database.execute(insert_statement)
            logger.info(
                "Status code summary email: %s",
                status,
            )
        except MissingEmailParamsError as error:
            insert_statement = (
                insert(failed_emails)
                .values(
                    {
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
        logger.error("Missing summary email recipient.")


async def get_timestamp_last_summary_email() -> Optional[datetime]:
    """Retrieve the timestamp from the emails table of the most recent summary email sent.

    Returns:
        The timestamp of the last summary email sent.
    """
    query = (
        select([emails])
        .where(emails.c.type == EMAIL_TYPE_SUMMARY)
        .order_by(desc(emails.c.id))
    )
    row = await database.fetch_one(query)
    if row:
        time_last_summary = row["time_created"]
        logger.info("Last summary email was sent at: %s", time_last_summary)
    else:
        time_last_summary = None
        logger.info("There's been no summary email so far.")
    return time_last_summary
