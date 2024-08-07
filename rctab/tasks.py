"""Tasks that run in the background.

Be sure to test any changes to these tasks locally by running:
`celery -A rctab.tasks worker --loglevel=info`
and either calling the task manually from Python with:
`taskname.delay()`
or running Celery Beat in a shell and waiting
for the task to run on schedule:
`celery -A rctab.tasks beat --loglevel=info`
"""

import asyncio
import logging
from typing import Any, Final
from uuid import UUID

from celery import Celery
from celery.schedules import crontab
from celery.signals import after_setup_logger, after_setup_task_logger
from opencensus.ext.azure.log_exporter import AzureLogHandler

from rctab.constants import ADMIN_OID
from rctab.crud.models import database
from rctab.logutils import CustomDimensionsFilter
from rctab.routers.accounting.abolishment import abolish_subscriptions
from rctab.routers.accounting.summary_emails import (
    get_timestamp_last_summary_email,
    send_summary_email,
)
from rctab.settings import get_settings

my_logger = logging.getLogger(__name__)

CELERY_BROKER_URL: Final = "redis://localhost:6379/0"

celery_app = Celery(
    "rctab.tasks",
    broker=CELERY_BROKER_URL,
)

celery_app.conf.timezone = "Europe/London"


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender: Any, **_) -> None:  # type: ignore[no-untyped-def]
    """Schedule periodic tasks."""
    sender.add_periodic_task(
        crontab(hour="16", minute="00"), run_send_summary_email.s()
    )
    sender.add_periodic_task(
        crontab(hour="01", minute="00"), run_abolish_subscriptions.s()
    )


@after_setup_logger.connect
def setup_logger(logger: Any, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
    """Set up celery logger."""
    settings = get_settings()
    if settings.central_logging_connection_string:
        custom_dimensions = {"logger_name": "logger_celery"}
        handler = AzureLogHandler(
            connection_string=settings.central_logging_connection_string
        )
        handler.addFilter(CustomDimensionsFilter(custom_dimensions))
        logger.addHandler(handler)


@after_setup_task_logger.connect
def setup_task_logger(logger: Any, *_: Any, **__: Any) -> None:  # type: ignore[no-untyped-def]
    """Set up celery task logger."""
    settings = get_settings()
    if settings.central_logging_connection_string:
        custom_dimensions = {"logger_name": "logger_celery_worker"}
        handler = AzureLogHandler(
            connection_string=settings.central_logging_connection_string
        )
        handler.addFilter(CustomDimensionsFilter(custom_dimensions))
        logger.addHandler(handler)


async def send() -> None:
    """Connect to the database and send the daily summary email."""
    await database.connect()
    try:
        recipients = get_settings().admin_email_recipients
        if recipients:
            time_last_summary_email = await get_timestamp_last_summary_email()
            await send_summary_email(recipients, time_last_summary_email)
        else:
            my_logger.warning("No recipients for summary email found")
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
