"""PostgreSQL advisory lock utilities for preventing race conditions."""

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio.engine import AsyncConnection

logger = logging.getLogger(__name__)


def _string_to_lock_id(lock_name: str) -> int:
    """Convert a string to a 64-bit signed integer for PostgreSQL advisory locks.

    PostgreSQL advisory locks use bigint (64-bit signed integer) keys.
    We hash the string and convert to ensure it fits in the valid range.
    """
    hash_bytes = hashlib.md5(lock_name.encode()).digest()
    # Convert first 8 bytes to signed 64-bit integer
    lock_id = int.from_bytes(hash_bytes[:8], byteorder="big", signed=True)
    return lock_id


@asynccontextmanager
async def advisory_lock(
    connection: AsyncConnection,
    lock_name: str,
) -> AsyncGenerator[None, None]:
    """Acquire a PostgreSQL advisory lock for the duration of the context.

    The lock is acquired on ``connection`` so that it shares the request's
    session with the protected work. ``pg_advisory_lock`` blocks until the
    lock becomes available.

    Args:
        connection: Async database connection
        lock_name: Unique string identifier for the lock

    Raises:
        HTTPException: If the lock cannot be acquired

    Example:
        async with advisory_lock(conn, "usage_upload"):
            # Critical section - only one process can execute this
            await perform_critical_operation()
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info("Attempting to acquire advisory lock: %s (id: %d)", lock_name, lock_id)

    try:
        # pg_advisory_lock blocks until the (session-level) lock is acquired.
        await connection.execute(
            text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id}
        )
        logger.info("Successfully acquired advisory lock: %s", lock_name)
    except Exception as e:
        logger.error("Failed to acquire advisory lock %s: %s", lock_name, e)
        raise HTTPException(
            status_code=503,
            detail=f"Could not acquire lock for operation '{lock_name}'. "
            f"Another process may be performing the same operation.",
        )

    # Lock acquired successfully, now execute the protected section
    try:
        yield
    finally:
        # Always release the lock, even on exceptions in the protected section
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
            )
            logger.info("Released advisory lock: %s", lock_name)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to release advisory lock %s: %s", lock_name, e)
            # Don't raise here as we don't want to mask the original exception


@asynccontextmanager
async def advisory_lock_nowait(
    connection: AsyncConnection, lock_name: str
) -> AsyncGenerator[None, None]:
    """Acquire a PostgreSQL advisory lock without waiting.

    Args:
        connection: Async database connection
        lock_name: Unique string identifier for the lock

    Raises:
        HTTPException: If lock cannot be acquired immediately

    Example:
        async with advisory_lock_nowait(conn, "cost_recovery"):
            # Critical section - fails fast if another process is running
            await perform_operation()
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info(
        "Attempting to acquire advisory lock (no-wait): %s (id: %d)", lock_name, lock_id
    )

    # Try to acquire lock without waiting
    acquired = await connection.scalar(
        text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}
    )

    if not acquired:
        logger.warning("Could not acquire advisory lock immediately: %s", lock_name)
        raise HTTPException(
            status_code=409,
            detail=f"Operation '{lock_name}' is already in progress. Please try again later.",
        )

    logger.info("Successfully acquired advisory lock (no-wait): %s", lock_name)

    try:
        yield
    finally:
        # Always release the lock
        await connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
        )
        logger.info("Released advisory lock: %s", lock_name)


# Predefined lock names for common operations
class LockNames:
    """Centralized lock name constants to prevent conflicts."""

    USAGE_UPLOAD = "usage_upload"
    USAGE_MONTHLY_UPLOAD = "usage_monthly_upload"
    COST_RECOVERY = "cost_recovery"
    MATERIALIZED_VIEW_REFRESH = "materialized_view_refresh"
    SUBSCRIPTION_CREATION = "subscription_creation"

    @classmethod
    def usage_upload_by_date_range(cls, start_date: str, end_date: str) -> str:
        """Generate lock name for usage upload scoped to date range."""
        return f"usage_upload_{start_date}_{end_date}"

    @classmethod
    def cost_recovery_by_month(cls, year: int, month: int) -> str:
        """Generate lock name for cost recovery scoped to specific month."""
        return f"cost_recovery_{year}_{month:02d}"
