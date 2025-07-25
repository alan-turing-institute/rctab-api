"""Module for database connections."""

from typing import AsyncGenerator, Final

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.settings import get_settings

SETTINGS: Final = get_settings()

ENGINE: Final = create_async_engine(str(SETTINGS.postgres_dsn))


async def get_async_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Yields an asynchronous database connection."""
    async with ENGINE.begin() as conn:
        yield conn
