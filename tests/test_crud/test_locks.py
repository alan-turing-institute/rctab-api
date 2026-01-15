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

    def test_consistent_lock_ids(self):
        """Test that same strings produce same lock IDs."""
        lock_name = "test_lock"
        id1 = _string_to_lock_id(lock_name)
        id2 = _string_to_lock_id(lock_name)
        assert id1 == id2

    def test_different_strings_different_ids(self):
        """Test that different strings produce different lock IDs."""
        id1 = _string_to_lock_id("lock1")
        id2 = _string_to_lock_id("lock2")
        assert id1 != id2

    def test_lock_id_in_valid_range(self):
        """Test that lock IDs are valid 64-bit signed integers."""
        lock_id = _string_to_lock_id("test")
        # PostgreSQL bigint range: -9223372036854775808 to 9223372036854775807
        assert -9223372036854775808 <= lock_id <= 9223372036854775807


class TestAdvisoryLock:
    """Test advisory_lock context manager."""

    @pytest.mark.asyncio
    async def test_successful_lock_acquisition(self):
        """Test successful lock acquisition and release."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = True  # Lock acquired successfully
        mock_db.execute.return_value = None

        async with advisory_lock(mock_db, "test_lock"):
            pass

        # Verify lock acquisition and release calls
        assert mock_db.fetch_val.call_count == 1
        assert mock_db.execute.call_count == 1

        # Check the SQL calls
        fetch_call = mock_db.fetch_val.call_args
        assert "pg_try_advisory_lock" in fetch_call[0][0]

        execute_call = mock_db.execute.call_args
        assert "pg_advisory_unlock" in execute_call[0][0]

    @pytest.mark.asyncio
    async def test_lock_acquisition_with_retry(self):
        """Test lock acquisition when first attempt fails."""
        mock_db = AsyncMock()
        # First call fails, second succeeds
        mock_db.fetch_val.side_effect = [False, True]
        mock_db.execute.return_value = None

        async with advisory_lock(mock_db, "test_lock"):
            pass

        # Should try twice (try_lock then blocking lock)
        assert mock_db.fetch_val.call_count == 2
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_lock_always_released_on_exception(self):
        """Test that locks are released even when exceptions occur."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = True
        mock_db.execute.return_value = None

        with pytest.raises(ValueError):
            async with advisory_lock(mock_db, "test_lock"):
                raise ValueError("Test exception")

        # Lock should still be released
        assert mock_db.execute.call_count == 1
        execute_call = mock_db.execute.call_args
        assert "pg_advisory_unlock" in execute_call[0][0]

    @pytest.mark.asyncio
    async def test_database_error_handling(self):
        """Test handling of database errors during lock acquisition."""
        mock_db = AsyncMock()
        mock_db.fetch_val.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            async with advisory_lock(mock_db, "test_lock"):
                pass

        assert exc_info.value.status_code == 503
        assert "Could not acquire lock" in exc_info.value.detail


class TestAdvisoryLockNoWait:
    """Test advisory_lock_nowait context manager."""

    @pytest.mark.asyncio
    async def test_successful_immediate_lock(self):
        """Test successful immediate lock acquisition."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = True
        mock_db.execute.return_value = None

        async with advisory_lock_nowait(mock_db, "test_lock"):
            pass

        assert mock_db.fetch_val.call_count == 1
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_failed_immediate_lock(self):
        """Test failure when lock cannot be acquired immediately."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = False  # Lock not available

        with pytest.raises(HTTPException) as exc_info:
            async with advisory_lock_nowait(mock_db, "test_lock"):
                pass

        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.detail

        # Should not call unlock if lock was not acquired
        assert mock_db.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self):
        """Test that acquired locks are released on exceptions."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = True
        mock_db.execute.return_value = None

        with pytest.raises(ValueError):
            async with advisory_lock_nowait(mock_db, "test_lock"):
                raise ValueError("Test exception")

        # Lock should be released
        assert mock_db.execute.call_count == 1


class TestLockNames:
    """Test lock name generation utilities."""

    def test_predefined_constants(self):
        """Test that predefined lock name constants exist."""
        assert hasattr(LockNames, "USAGE_UPLOAD")
        assert hasattr(LockNames, "COST_RECOVERY")
        assert hasattr(LockNames, "MATERIALIZED_VIEW_REFRESH")
        assert isinstance(LockNames.USAGE_UPLOAD, str)

    def test_usage_upload_by_date_range(self):
        """Test date range lock name generation."""
        lock_name = LockNames.usage_upload_by_date_range("2021-01-01", "2021-01-31")
        assert "2021-01-01" in lock_name
        assert "2021-01-31" in lock_name
        assert "usage_upload" in lock_name

    def test_cost_recovery_by_month(self):
        """Test monthly cost recovery lock name generation."""
        lock_name = LockNames.cost_recovery_by_month(2021, 3)
        assert "2021" in lock_name
        assert "03" in lock_name  # Should be zero-padded
        assert "cost_recovery" in lock_name

    def test_different_months_different_locks(self):
        """Test that different months generate different lock names."""
        lock1 = LockNames.cost_recovery_by_month(2021, 1)
        lock2 = LockNames.cost_recovery_by_month(2021, 2)
        assert lock1 != lock2

    def test_different_date_ranges_different_locks(self):
        """Test that different date ranges generate different lock names."""
        lock1 = LockNames.usage_upload_by_date_range("2021-01-01", "2021-01-31")
        lock2 = LockNames.usage_upload_by_date_range("2021-02-01", "2021-02-28")
        assert lock1 != lock2


class TestLockIntegration:
    """Integration tests for lock behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_lock_attempts(self):
        """Test behavior when multiple processes try to acquire same lock."""
        # This test would ideally use multiple async tasks
        # but for unit testing, we simulate the scenario
        mock_db1 = AsyncMock()
        mock_db1.fetch_val.return_value = True
        mock_db1.execute.return_value = None

        mock_db2 = AsyncMock()
        mock_db2.fetch_val.return_value = False  # Second process can't get lock

        # First process gets lock
        async with advisory_lock_nowait(mock_db1, "shared_lock"):
            # Second process should fail
            with pytest.raises(HTTPException) as exc_info:
                async with advisory_lock_nowait(mock_db2, "shared_lock"):
                    pass

            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_lock_name_uniqueness_matters(self):
        """Test that different lock names don't interfere."""
        mock_db = AsyncMock()
        mock_db.fetch_val.return_value = True
        mock_db.execute.return_value = None

        # These should not interfere with each other
        async with advisory_lock_nowait(mock_db, "lock1"):
            async with advisory_lock_nowait(mock_db, "lock2"):
                pass

        # Should have acquired and released two different locks
        assert mock_db.fetch_val.call_count == 2
        assert mock_db.execute.call_count == 2
