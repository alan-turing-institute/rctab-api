"""PostgreSQL advisory lock utilities for preventing race conditions."""

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import databases
from fastapi import HTTPException

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
    database: databases.Database,
    lock_name: str,
    timeout_seconds: int = 30,  # noqa: ARG001
) -> AsyncGenerator[None, None]:
    """Acquire a PostgreSQL advisory lock for the duration of the context.

    Args:
        database: Database connection
        lock_name: Unique string identifier for the lock
        timeout_seconds: Maximum time to wait for lock acquisition

    Raises:
        HTTPException: If lock cannot be acquired within timeout

    Example:
        async with advisory_lock(database, "usage_upload"):
            # Critical section - only one process can execute this
            await perform_critical_operation()
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info("Attempting to acquire advisory lock: %s (id: %d)", lock_name, lock_id)

    # Try to acquire lock with timeout
    try:
        # pg_try_advisory_lock returns true if lock acquired, false if not available
        # We use a timeout approach by checking periodically
        acquired = await database.fetch_val(
            "SELECT pg_try_advisory_lock($1)", values=[lock_id]
        )

        if not acquired:
            # If immediate acquisition fails, try with timeout
            acquired = await database.fetch_val(
                "SELECT pg_advisory_lock($1)", values=[lock_id]
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
            await database.execute("SELECT pg_advisory_unlock($1)", values=[lock_id])
            logger.info("Released advisory lock: %s", lock_name)
        except Exception as e:
            logger.error("Failed to release advisory lock %s: %s", lock_name, e)
            # Don't raise here as we don't want to mask the original exception


@asynccontextmanager
async def advisory_lock_nowait(
    database: databases.Database, lock_name: str
) -> AsyncGenerator[None, None]:
    """Acquire a PostgreSQL advisory lock without waiting.

    Args:
        database: Database connection
        lock_name: Unique string identifier for the lock

    Raises:
        HTTPException: If lock cannot be acquired immediately

    Example:
        async with advisory_lock_nowait(database, "cost_recovery"):
            # Critical section - fails fast if another process is running
            await perform_operation()
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info(
        "Attempting to acquire advisory lock (no-wait): %s (id: %d)", lock_name, lock_id
    )

    # Try to acquire lock without waiting
    acquired = await database.fetch_val(
        "SELECT pg_try_advisory_lock($1)", values=[lock_id]
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
        await database.execute("SELECT pg_advisory_unlock($1)", values=[lock_id])
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
