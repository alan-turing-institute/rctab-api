"""Tests for the rctab.tasks module."""
import logging
import os
import subprocess
from typing import Generator, List
from uuid import UUID

import pytest
from pytest_mock import MockerFixture

from rctab.constants import ADMIN_OID
from rctab.tasks import (
    abolish,
    run_abolish_subscriptions,
    run_send_summary_email,
    send,
    setup_logger,
    setup_periodic_tasks,
    setup_task_logger,
)

# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def my_celery_worker() -> Generator[None, None, None]:
    """Start/stop a celery worker for testing."""
    with subprocess.Popen(
        [
            "celery",
            "-A",
            "rctab.tasks",
            "worker",
            "--loglevel=info",
            "--concurrency",
            "1",
            "--hostname",
            "rctab-api-testworker",
        ]
    ) as worker_process:
        yield None
        worker_process.terminate()


@pytest.mark.skipif(
    os.environ.get("CELERY_RESULT_BACKEND") is None,
    reason="Start a celery backend and set env var to enable.",
)
def test_abolish_subscriptions_task(my_celery_worker: None) -> None:
    """Check that we can run the abolish subscriptions task."""
    result = run_abolish_subscriptions.delay()
    return_value = result.wait(timeout=5)
    assert return_value is None


@pytest.mark.skipif(
    os.environ.get("CELERY_RESULT_BACKEND") is None,
    reason="Start a celery backend and set env var to enable.",
)
def test_send_summary_email_task(my_celery_worker: None) -> None:
    """Check that we can run the summary email task."""
    result = run_send_summary_email.delay()
    return_value = result.wait(timeout=5)
    assert return_value is None


def test_setup_periodic_tasks(
    mocker: MockerFixture,
) -> None:
    """Check that we can set up periodic tasks."""
    sender = mocker.MagicMock()
    # https://docs.celeryq.dev/en/main/userguide/periodic-tasks.html#entries
    setup_periodic_tasks(sender=sender)


def test_setup_logger() -> None:
    """Check that we can set up logging."""
    logger = logging.getLogger(__name__)
    # https://docs.celeryq.dev/en/stable/userguide/signals.html#after-setup-logger
    setup_logger(logger=logger, loglevel=None, logfile=None, format=None, colorize=None)


def test_setup_task_logger() -> None:
    """Check that we can set up task logging."""
    logger = logging.getLogger(__name__)
    # https://docs.celeryq.dev/en/stable/userguide/signals.html#after-setup-task-logger
    setup_task_logger(
        logger=logger, loglevel=None, logfile=None, format=None, colorize=None
    )


@pytest.mark.asyncio
async def test_send(
    mocker: MockerFixture,
) -> None:
    """Check that we can send summary emails."""
    mock_send = mocker.patch("rctab.tasks.send_summary_email")
    mock_get_settings = mocker.patch("rctab.tasks.get_settings")

    recipients = ["me@my.org"]
    mock_get_settings.return_value.admin_email_recipients = recipients
    await send()
    mock_send.assert_called_once_with(recipients, None)


@pytest.mark.asyncio
async def test_send_no_recipients(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Check that we only send summary emails if we have recipients."""
    mock_get_settings = mocker.patch("rctab.tasks.get_settings")

    recipients: List[str] = []
    mock_get_settings.return_value.admin_email_recipients = recipients
    await send()
    assert "No recipients for summary email found" in caplog.text


@pytest.mark.asyncio
async def test_abolish(
    mocker: MockerFixture,
) -> None:
    """Check that we can abolish subscriptions."""
    mock_abolish = mocker.patch("rctab.tasks.abolish_subscriptions")

    await abolish()
    mock_abolish.assert_called_once_with(UUID(ADMIN_OID))
