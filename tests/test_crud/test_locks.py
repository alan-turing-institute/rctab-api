"""Tests for PostgreSQL advisory lock utilities."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from rctab.crud.locks import (
    LockNames,
    _string_to_lock_id,
    advisory_lock,
    advisory_lock_nowait,
)


class TestStringToLockId:
    """Test lock ID generation from strings."""

    def test_consistent_lock_ids(self) -> None:
        """Test that same strings produce same lock IDs."""
        lock_name = "test_lock"
        id1 = _string_to_lock_id(lock_name)
        id2 = _string_to_lock_id(lock_name)
        assert id1 == id2

    def test_different_strings_different_ids(self) -> None:
        """Test that different strings produce different lock IDs."""
        id1 = _string_to_lock_id("lock1")
        id2 = _string_to_lock_id("lock2")
        assert id1 != id2

    def test_lock_id_in_valid_range(self) -> None:
        """Test that lock IDs are valid 64-bit signed integers."""
        lock_id = _string_to_lock_id("test")
        # PostgreSQL bigint range: -9223372036854775808 to 9223372036854775807
        assert -9223372036854775808 <= lock_id <= 9223372036854775807


class TestAdvisoryLock:
    """Test advisory_lock context manager."""

    @pytest.mark.asyncio
    async def test_successful_lock_acquisition(self) -> None:
        """Test successful lock acquisition and release."""
        mock_conn = AsyncMock()

        async with advisory_lock(mock_conn, "test_lock"):
            pass

        # Acquire and release are both run via execute().
        assert mock_conn.execute.call_count == 2

        acquire_call, release_call = mock_conn.execute.call_args_list
        assert "pg_advisory_lock" in str(acquire_call.args[0])
        assert "pg_advisory_unlock" in str(release_call.args[0])

    @pytest.mark.asyncio
    async def test_lock_always_released_on_exception(self) -> None:
        """Test that locks are released even when exceptions occur."""
        mock_conn = AsyncMock()

        with pytest.raises(ValueError):
            async with advisory_lock(mock_conn, "test_lock"):
                raise ValueError("Test exception")

        # Lock should still be released (acquire + release).
        assert mock_conn.execute.call_count == 2
        release_call = mock_conn.execute.call_args_list[-1]
        assert "pg_advisory_unlock" in str(release_call.args[0])

    @pytest.mark.asyncio
    async def test_database_error_handling(self) -> None:
        """Test handling of database errors during lock acquisition."""
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            async with advisory_lock(mock_conn, "test_lock"):
                pass

        assert exc_info.value.status_code == 503
        assert "Could not acquire lock" in exc_info.value.detail


class TestAdvisoryLockNoWait:
    """Test advisory_lock_nowait context manager."""

    @pytest.mark.asyncio
    async def test_successful_immediate_lock(self) -> None:
        """Test successful immediate lock acquisition."""
        mock_conn = AsyncMock()
        mock_conn.scalar.return_value = True

        async with advisory_lock_nowait(mock_conn, "test_lock"):
            pass

        # Acquire uses scalar(pg_try_advisory_lock); release uses execute(unlock).
        assert mock_conn.scalar.call_count == 1
        assert "pg_try_advisory_lock" in str(mock_conn.scalar.call_args.args[0])
        assert mock_conn.execute.call_count == 1
        assert "pg_advisory_unlock" in str(mock_conn.execute.call_args.args[0])

    @pytest.mark.asyncio
    async def test_failed_immediate_lock(self) -> None:
        """Test failure when lock cannot be acquired immediately."""
        mock_conn = AsyncMock()
        mock_conn.scalar.return_value = False  # Lock not available

        with pytest.raises(HTTPException) as exc_info:
            async with advisory_lock_nowait(mock_conn, "test_lock"):
                pass

        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.detail

        # Should not call unlock if lock was not acquired.
        assert mock_conn.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self) -> None:
        """Test that acquired locks are released on exceptions."""
        mock_conn = AsyncMock()
        mock_conn.scalar.return_value = True

        with pytest.raises(ValueError):
            async with advisory_lock_nowait(mock_conn, "test_lock"):
                raise ValueError("Test exception")

        # Lock should be released.
        assert mock_conn.execute.call_count == 1
        assert "pg_advisory_unlock" in str(mock_conn.execute.call_args.args[0])


class TestLockNames:
    """Test lock name generation utilities."""

    def test_predefined_constants(self) -> None:
        """Test that predefined lock name constants exist."""
        assert hasattr(LockNames, "USAGE_UPLOAD")
        assert hasattr(LockNames, "COST_RECOVERY")
        assert hasattr(LockNames, "MATERIALIZED_VIEW_REFRESH")
        assert isinstance(LockNames.USAGE_UPLOAD, str)

    def test_usage_upload_by_date_range(self) -> None:
        """Test date range lock name generation."""
        lock_name = LockNames.usage_upload_by_date_range("2021-01-01", "2021-01-31")
        assert "2021-01-01" in lock_name
        assert "2021-01-31" in lock_name
        assert "usage_upload" in lock_name

    def test_cost_recovery_by_month(self) -> None:
        """Test monthly cost recovery lock name generation."""
        lock_name = LockNames.cost_recovery_by_month(2021, 3)
        assert "2021" in lock_name
        assert "03" in lock_name  # Should be zero-padded
        assert "cost_recovery" in lock_name

    def test_different_months_different_locks(self) -> None:
        """Test that different months generate different lock names."""
        lock1 = LockNames.cost_recovery_by_month(2021, 1)
        lock2 = LockNames.cost_recovery_by_month(2021, 2)
        assert lock1 != lock2

    def test_different_date_ranges_different_locks(self) -> None:
        """Test that different date ranges generate different lock names."""
        lock1 = LockNames.usage_upload_by_date_range("2021-01-01", "2021-01-31")
        lock2 = LockNames.usage_upload_by_date_range("2021-02-01", "2021-02-28")
        assert lock1 != lock2


class TestLockNoWaitConcurrency:
    """Test no-wait lock behaviour across simulated callers."""

    @pytest.mark.asyncio
    async def test_second_caller_fails_fast(self) -> None:
        """A second caller that cannot acquire the lock should get a 409."""
        mock_conn1 = AsyncMock()
        mock_conn1.scalar.return_value = True

        mock_conn2 = AsyncMock()
        mock_conn2.scalar.return_value = False  # Second caller can't get lock

        async with advisory_lock_nowait(mock_conn1, "shared_lock"):
            with pytest.raises(HTTPException) as exc_info:
                async with advisory_lock_nowait(mock_conn2, "shared_lock"):
                    pass

            assert exc_info.value.status_code == 409
