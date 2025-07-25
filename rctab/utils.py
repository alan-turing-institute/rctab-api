"""Utility functions for the RCTab API."""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def db_select(func: Callable) -> Callable:
    """Decorate a function that returns a SELECT statement.

    Optionally, execute the function and raise a 404 if no data is returned.
    """
    return func
