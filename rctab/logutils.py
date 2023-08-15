"""Utilities for logging to a central log workspace."""
import logging
from typing import Optional

from opencensus.ext.azure.log_exporter import AzureLogHandler

from rctab.settings import get_settings


class CustomDimensionsFilter(logging.Filter):
    """Add application-wide properties to AzureLogHandler records."""

    def __init__(self, custom_dimensions: Optional[dict] = None) -> None:
        """Initialize the filter with the given custom_dimensions."""
        super().__init__()
        self.custom_dimensions = custom_dimensions or {}

    def filter(self, record: logging.LogRecord) -> bool:
        """Adds the default custom_dimensions to the current log record."""
        custom_dimensions = self.custom_dimensions.copy()
        custom_dimensions.update(getattr(record, "custom_dimensions", {}))
        record.custom_dimensions = custom_dimensions  # type: ignore

        return True


def set_log_handler(name: str = "rctab") -> None:
    """Adds an Azure log handler to the logger with provided name.

    The log data is sent to the Azure Application Insights instance associated with the connection string in settings.
    Additional properties are added to log messages in form of a key-value
    pair which can be used to filter the log messages on Azure.

    Args:
        name: Name of the logger instance to which we add the log handler.
    """
    logger = logging.getLogger(name)
    settings = get_settings()
    if settings.central_logging_connection_string:
        custom_dimensions = {"logger_name": "logger_rctab"}
        handler = AzureLogHandler(
            connection_string=settings.central_logging_connection_string
        )
        handler.addFilter(CustomDimensionsFilter(custom_dimensions))
        logger.addHandler(handler)
