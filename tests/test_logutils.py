"""Tests for the rctab.logutils module."""

import logging
from typing import Generator
from unittest.mock import MagicMock

import pytest
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from pytest_mock import MockerFixture

from rctab import logutils

# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name


@pytest.fixture()
def mock_configure(mocker: MockerFixture) -> Generator[MagicMock, None, None]:
    """Stub out Azure Monitor and provide a connection string."""
    logutils.configure_telemetry.cache_clear()
    mocker.patch(
        "rctab.logutils.get_settings"
    ).return_value.applicationinsights_connection_string = "my-str"
    mock = mocker.patch("rctab.logutils.configure_azure_monitor")

    yield mock

    logutils.configure_telemetry.cache_clear()


def remove_handlers(name: str) -> None:
    """Remove any LoggingHandlers a test added to the named logger."""
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
        if isinstance(handler, LoggingHandler):
            logger.removeHandler(handler)


def test_no_connection_string(mocker: MockerFixture) -> None:
    """Without a connection string we should not configure anything."""
    mocker.patch(
        "rctab.logutils.get_settings"
    ).return_value.applicationinsights_connection_string = None
    mock_configure = mocker.patch("rctab.logutils.configure_azure_monitor")

    logutils.set_log_handler("no_conn_str")

    mock_configure.assert_not_called()
    assert logging.getLogger("no_conn_str").handlers == []


def test_called_twice(mock_configure: MagicMock) -> None:
    """Adding multiple handlers could cause large storage bills."""
    try:
        logutils.set_log_handler("twice")
        logutils.set_log_handler("twice")

        handlers = logging.getLogger("twice").handlers
        assert len(handlers) == 1
    finally:
        remove_handlers("twice")


def test_configured_once(mock_configure: MagicMock) -> None:
    """configure_azure_monitor() sets up process-wide state.

    Calling it more than once would duplicate the exporting machinery, so it
    must happen once however many loggers we add handlers to.
    """
    try:
        logutils.set_log_handler("first")
        logutils.set_log_handler("second")

        mock_configure.assert_called_once()
        assert len(logging.getLogger("first").handlers) == 1
        assert len(logging.getLogger("second").handlers) == 1
    finally:
        remove_handlers("first")
        remove_handlers("second")


def test_logs_only(mock_configure: MagicMock) -> None:
    """Request and dependency telemetry are out of scope."""
    logutils.set_log_handler(logutils.APP_LOGGER_NAME)

    kwargs = mock_configure.call_args.kwargs
    assert kwargs["logger_name"] == logutils.APP_LOGGER_NAME
    assert kwargs["disable_tracing"] is True
    assert kwargs["disable_metrics"] is True
    assert kwargs["enable_live_metrics"] is False
    assert kwargs["enable_performance_counters"] is False
    assert all(
        not options["enabled"] for options in kwargs["instrumentation_options"].values()
    )


def test_exports_code_attributes(
    mocker: MockerFixture, mock_configure: MagicMock
) -> None:
    """Records should be exported with their source location.

    This also checks that logging through a real handler does not raise, which
    the OpenCensus handler did from Python 3.13 onwards.
    """
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    mocker.patch("rctab.logutils.get_logger_provider", return_value=provider)

    try:
        logutils.set_log_handler("code_attributes")
        logging.getLogger("code_attributes").error("Hello")
    finally:
        remove_handlers("code_attributes")

    exported = exporter.get_finished_logs()
    assert len(exported) == 1
    attributes = exported[0].log_record.attributes
    assert attributes is not None
    assert attributes["code.function.name"] == "test_exports_code_attributes"
    assert attributes["code.file.path"] == __file__
    assert isinstance(attributes["code.line.number"], int)
