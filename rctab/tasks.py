"""Tasks that run in the background."""
import asyncio
from typing import Any, Final
from uuid import UUID

from celery import Celery
from celery.schedules import crontab

from rctab.constants import ADMIN_OID
from rctab.crud.models import database
from rctab.daily_routine_tasks import (
    get_timestamp_last_summary_email,
    send_summary_email,
)
from rctab.routers.accounting.abolishment import abolish_subscriptions
from rctab.settings import get_settings

# todo shut down celery and redis on exit
# todo redis config file
# todo set timezone to London


CELERY_BROKER_URL: Final = "redis://localhost:6379/0"

celery_app = Celery(
    "rctab.tasks",
    broker=CELERY_BROKER_URL,
)


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender: Any, **_) -> None:  # type: ignore[no-untyped-def]
    """Schedule periodic tasks."""
    sender.add_periodic_task(
        crontab(hour="16", minute="00"), run_send_summary_email.s()
    )
    sender.add_periodic_task(
        crontab(hour="01", minute="00"), run_abolish_subscriptions.s()
    )


async def send() -> None:
    """Connect to the database and send the daily summary email."""
    await database.connect()
    try:
        recipients = get_settings().admin_email_recipients
        time_last_summary_email = await get_timestamp_last_summary_email()
        await send_summary_email(recipients, time_last_summary_email)
    finally:
        await database.disconnect()


@celery_app.task
def run_send_summary_email() -> None:
    """A synchronous wrapper for the async send function."""
    asyncio.run(send())


async def abolish() -> None:
    """Connect to the database and run the abolish function."""
    await database.connect()
    try:
        await abolish_subscriptions(UUID(ADMIN_OID))
    finally:
        await database.disconnect()


@celery_app.task
def run_abolish_subscriptions() -> None:
    """A synchronous wrapper for the async abolish function."""
    asyncio.run(abolish())
