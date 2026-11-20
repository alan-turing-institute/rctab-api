"""Utilities for logging to Azure Application Insights."""

import logging
import os
from functools import lru_cache

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry._logs import get_logger_provider
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from rctab.settings import get_settings

DEFAULT_SERVICE_NAME = "rctab-api"

# The logger that configure_azure_monitor() attaches its handler to.
APP_LOGGER_NAME = "rctab"

# Auto-instrumentation would add request and dependency telemetry, which is
# out of scope here. Disable every library the distro would otherwise patch.
DISABLED_INSTRUMENTATIONS = {
    lib_name: {"enabled": False}
    for lib_name in (
        "azure_sdk",
        "django",
        "fastapi",
        "flask",
        "httpx",
        "httpx2",
        "psycopg2",
        "requests",
        "urllib",
        "urllib3",
    )
}


class CodeAttributesFilter(logging.Filter):
    """Add the source location of each log record.

    The module, function and line number are standard LogRecord fields, which
    the OpenTelemetry handler excludes from the attributes it exports unless it
    is built with log_code_attributes=True. configure_azure_monitor() does not
    build it that way, so add them here under their OpenTelemetry names. They
    appear as customDimensions in Application Insights, as they did under the
    previous OpenCensus handler.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add the source location attributes to the current log record."""
        setattr(record, "code.file.path", record.pathname)
        setattr(record, "code.function.name", record.funcName)
        setattr(record, "code.line.number", record.lineno)

        return True


@lru_cache(maxsize=1)
def configure_telemetry(connection_string: str) -> None:
    """Configure Azure Monitor once per process.

    configure_azure_monitor() sets up process-wide state, so it must not be
    called more than once. Only logs are exported: tracing, metrics, live
    metrics and performance counters are all disabled.

    Args:
        connection_string: The Application Insights connection string.
    """
    service_name = os.environ.get("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)
    configure_azure_monitor(
        connection_string=connection_string,
        logger_name=APP_LOGGER_NAME,
        resource=Resource.create({SERVICE_NAME: service_name}),
        disable_tracing=True,
        disable_metrics=True,
        enable_live_metrics=False,
        enable_performance_counters=False,
        instrumentation_options=DISABLED_INSTRUMENTATIONS,
    )

    # Filter the handler rather than the logger, so that records arriving by
    # propagation from child loggers are covered too.
    for handler in logging.getLogger(APP_LOGGER_NAME).handlers:
        if isinstance(handler, LoggingHandler):
            handler.addFilter(CodeAttributesFilter())


def set_log_handler(name: str = APP_LOGGER_NAME) -> None:
    """Send logs from the named logger to Azure Application Insights.

    The log data is sent to the Application Insights instance associated with
    the connection string in settings. The name of the logger that emitted
    each record is added automatically as the logger_name custom dimension,
    which can be used to filter the log messages on Azure.

    Args:
        name: Name of the logger instance to which we add the log handler.
    """
    connection_string = get_settings().applicationinsights_connection_string
    if not connection_string:
        return

    configure_telemetry(connection_string)

    logger = logging.getLogger(name)
    # Only allow one LoggingHandler per logger, since each additional handler
    # would export every record again.
    if any(isinstance(handler, LoggingHandler) for handler in logger.handlers):
        return

    handler = LoggingHandler(logger_provider=get_logger_provider())
    handler.addFilter(CodeAttributesFilter())
    logger.addHandler(handler)
