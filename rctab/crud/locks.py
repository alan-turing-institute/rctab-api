"""PostgreSQL advisory lock utilities for preventing race conditions.

The locks are transaction-scoped: they are held until the surrounding
transaction commits or rolls back. Each request runs in a single transaction
(see :func:`rctab.db.get_async_connection`), so a lock taken in a route
protects all of that request's writes until they are committed and visible
to other requests. There is no explicit unlock, so a lock cannot leak onto a
pooled connection.
"""

import hashlib
import logging
from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio.engine import AsyncConnection

logger = logging.getLogger(__name__)


class LockNames(StrEnum):
    """Names of the operations protected by advisory locks."""

    USAGE_UPLOAD = "usage_upload"
    COST_RECOVERY = "cost_recovery"


def _string_to_lock_id(lock_name: str) -> int:
    """Convert a string to a 64-bit signed integer for PostgreSQL advisory locks.

    PostgreSQL advisory locks use bigint (64-bit signed integer) keys.
    We hash the string and convert to ensure it fits in the valid range.
    """
    hash_bytes = hashlib.md5(lock_name.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big", signed=True)


async def advisory_xact_lock(connection: AsyncConnection, lock_name: str) -> None:
    """Acquire an advisory lock until the current transaction ends.

    Blocks until the lock is available.

    Args:
        connection: Async database connection with an open transaction.
        lock_name: Unique string identifier for the lock.
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info("Acquiring advisory lock: %s (id: %d)", lock_name, lock_id)
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
    )
    logger.info("Acquired advisory lock: %s", lock_name)


async def try_advisory_xact_lock(connection: AsyncConnection, lock_name: str) -> None:
    """Acquire an advisory lock until the current transaction ends, without waiting.

    Args:
        connection: Async database connection with an open transaction.
        lock_name: Unique string identifier for the lock.

    Raises:
        HTTPException: 409 if another transaction holds the lock.
    """
    lock_id = _string_to_lock_id(lock_name)
    logger.info("Trying to acquire advisory lock: %s (id: %d)", lock_name, lock_id)
    acquired = await connection.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
    )
    if not acquired:
        logger.warning("Advisory lock is held by another transaction: %s", lock_name)
        raise HTTPException(
            status_code=409,
            detail=f"Operation '{lock_name}' is already in progress. "
            "Please try again later.",
        )
    logger.info("Acquired advisory lock: %s", lock_name)
