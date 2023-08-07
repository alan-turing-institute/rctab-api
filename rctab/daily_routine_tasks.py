import contextlib
import logging
from asyncio import sleep
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Final, List, Optional, Type
from uuid import UUID

from sqlalchemy import desc, insert, select

from rctab.constants import ADMIN_OID, EMAIL_TYPE_SUMMARY
from rctab.crud.accounting_models import emails, failed_emails
from rctab.crud.models import database
from rctab.routers.accounting.abolishment import abolish_subscriptions
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    prepare_summary_email,
    send_with_sendgrid,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)

DESIRED_RUNTIME: Final = "16:00:00"


class FileLockContextManager(contextlib.AbstractContextManager):
    """Create a file on enter and remove that file on exit."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.lock_file = Path(self.filename)

    def __enter__(self) -> None:
        self.lock_file.touch(exist_ok=False)  # raises error if file exists

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        logger.warning("Deleting lock file")
        self.lock_file.unlink()


def datetime_utcnow() -> datetime:
    """Returns the current date and time in the UTC timezone.

    Returns
    -------
    datetime
        current UTC date and time
    """
    # This can be patched for testing more easily than datetime

    return datetime.now(timezone.utc)


def calc_how_long_to_sleep_for(desired_runtime: str) -> float:
    """
    Parameters
    ----------
    desired_runtime :  str
        Desired time of the day at which to perform a task e.g. 13:00:00
    Returns
    -------
    seconds_to_sleep : float
        Seconds until daily task has to be performed
    """
    # make sure all timestamps are UTC
    right_now = datetime_utcnow()
    date_today = right_now.strftime("%d/%m/%Y")
    sleep_until = datetime.strptime(
        f"{date_today} {desired_runtime}", "%d/%m/%Y %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    if sleep_until < right_now:
        sleep_until += timedelta(days=1)
    seconds_to_sleep = (sleep_until - right_now).total_seconds()
    seconds_to_sleep = max(seconds_to_sleep, 1)
    logger.info("Sleep for %s seconds until routine tasks", seconds_to_sleep)
    return seconds_to_sleep


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

    Parameters
    ----------
    recipients : List[str]
        list of email addresses of recipients
    since_this_datetime : Optional[datetime], optional
        include information since this date and time, by default None
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
        logger.error("Missing summary email recipient.")


async def routine_tasks() -> None:
    # pylint: disable=broad-except
    logger.info("Starting routine background tasks %s", datetime_utcnow())
    try:
        # Create a .lock file to make sure only one worker is running routine tasks
        with FileLockContextManager("routine_tasks.lock"):
            # Catch a wide array of Exceptions so that we can log them immediately
            # rather than them being printed at server shutdown.
            try:
                while True:
                    needs_to_send = True
                    recipients = get_settings().admin_email_recipients
                    time_last_summary_email = await get_timestamp_last_summary_email()
                    if not recipients:
                        # We should not send a summary email if we are testing
                        # as there are issues with the databases library
                        # that prohibit us from using the same databases object
                        # in multiple async tasks if force_rollback == True
                        # (see, amongst others, https://github.com/encode/databases/issues/456)
                        needs_to_send = False
                        logger.warning("No recipients for summary email found")

                    elif (
                        time_last_summary_email
                        and time_last_summary_email.date() == datetime_utcnow().date()
                    ):
                        needs_to_send = False
                        logger.info("No need to send another summary email today")

                    # Check whether it's time to run the background tasks
                    right_now = datetime_utcnow()
                    date_today = right_now.strftime("%d/%m/%Y")
                    scheduled_time = datetime.strptime(
                        f"{date_today} {DESIRED_RUNTIME}", "%d/%m/%Y %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if scheduled_time <= right_now:
                        logger.info("Time to run background tasks")
                        await abolish_subscriptions(UUID(ADMIN_OID))
                        if needs_to_send:
                            await send_summary_email(
                                recipients, time_last_summary_email
                            )
                    else:
                        logger.info(
                            "Too early for background tasks - sleep until %s UTC",
                            DESIRED_RUNTIME,
                        )
                    # We want to sleep for at least a second to avoid busy waiting
                    seconds_to_sleep = max(
                        1, calc_how_long_to_sleep_for(DESIRED_RUNTIME)
                    )
                    await sleep(seconds_to_sleep)

            except BaseException:
                logger.exception("Exception in routine_tasks")

    except FileExistsError:
        logger.exception("Exiting as we only need one routine tasks thread")


async def get_timestamp_last_summary_email() -> Optional[datetime]:
    """Returns timestamp of the last summary email that has been sent.

    Returns
    -------
    datetime
        timestamp of last summary email record in emails table
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
