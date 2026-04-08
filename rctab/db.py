"""Module for database connections."""

from typing import AsyncGenerator, Final

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncConnection
from sqlalchemy.pool import NullPool

from rctab.settings import get_settings

SETTINGS: Final = get_settings()

ENGINE_KWARGS: dict[str, object] = {}
if SETTINGS.testing:
    # Avoid sharing asyncpg pooled connections across event loops in tests.
    ENGINE_KWARGS["poolclass"] = NullPool

ENGINE: Final = create_async_engine(str(SETTINGS.postgres_dsn), **ENGINE_KWARGS)


async def get_async_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Yield an async connection with a request-scoped transaction.

    The transaction is committed on successful request completion and
    rolled back on exceptions.
    """
    async with ENGINE.begin() as conn:
        yield conn
