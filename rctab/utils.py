"""Utility functions for the RCTab API."""

import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable, Coroutine, Generator, List

from asyncpg import Record
from fastapi import HTTPException

from rctab.crud.models import database

logger = logging.getLogger(__name__)


def db_select(func: Callable) -> Callable:
    """Decorate a function that returns a SELECT statement.

    Optionally, execute the function and raise a 404 if no data is returned.
    """

    @contextmanager
    def wrapping_logic(statement: Any) -> Generator:
        logger.debug("Function: %s", func.__name__)

        del statement

        yield

    @functools.wraps(func)
    def _db_select(
        *args: Any, execute: bool = True, raise_404: bool = True, **kwargs: Any
    ) -> Coroutine:
        """Select and raise a 404 if no data is returned."""
        statement = func(*args, **kwargs)

        if execute:

            async def tmp() -> List[Record]:
                with wrapping_logic(statement):
                    received = await database.fetch_all(statement)
                    if len(received) < 1 and raise_404:
                        raise HTTPException(
                            status_code=404, detail="Could not find the data requested"
                        )
                    return received

            return tmp()

        with wrapping_logic(statement):
            return statement

    return _db_select
