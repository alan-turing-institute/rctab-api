"""Integration tests for advisory locks in route handlers."""

import datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from databases import Database
from fastapi import HTTPException
from rctab_models.models import AllUsage, Usage, UserRBAC

from rctab.crud.accounting_models import refresh_materialised_view, usage_view
from rctab.routers.accounting.cost_recovery import (
    CostRecoveryMonth,
    calc_cost_recovery_app,
    post_calc_cost_recovery_cli,
)
from rctab.routers.accounting.usage import post_monthly_usage, post_usage
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)


class TestUsageRouteLocks:
    """Test that usage routes properly use advisory locks."""

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.usage.advisory_lock")
    async def test_post_usage_uses_advisory_lock(
        self, mock_advisory_lock, test_db: Database
    ):
        """Test that post_usage route uses advisory lock correctly."""
        # Setup
        sub_id = await create_subscription(test_db)
        usage_data = AllUsage(
            usage_list=[
                Usage(
                    id=str(UUID(int=1)),
                    subscription_id=sub_id,
                    date="2021-01-01",
                    name="test-resource",
                    type="test-type",
                    billing_account_id="test-account",
                    billing_account_name="Test Account",
                    billing_profile_id="test-profile",
                    billing_profile_name="Test Profile",
                    account_owner_id="test-owner",
                    account_name="Test Account Name",
                    subscription_name="Test Subscription",
                    product="Test Product",
                    part_number="TEST-123",
                    meter_id="test-meter",
                    quantity=1.0,
                    effective_price=10.0,
                    cost=10.0,
                    unit_price=10.0,
                    billing_currency="USD",
                    resource_location="East US",
                    consumed_service="Test Service",
                    resource_id="test-resource-id",
                    resource_name="test-resource",
                    service_info1="",
                    service_info2="",
                    additional_info="",
                    invoice_section="",
                    cost_center="",
                    resource_group="test-rg",
                    monthly_upload=None,
                )
            ],
            start_date="2021-01-01",
            end_date="2021-01-01",
        )

        # Mock the context manager
        mock_context = AsyncMock()
        mock_advisory_lock.return_value.__aenter__.return_value = mock_context
        mock_advisory_lock.return_value.__aexit__.return_value = None

        # Mock other dependencies
        with patch("rctab.routers.accounting.usage.UsageEmailContextManager"), patch(
            "rctab.routers.accounting.usage.delete_usage"
        ), patch(
            "rctab.routers.accounting.usage.insert_subscriptions_if_not_exists"
        ), patch(
            "rctab.routers.accounting.usage.insert_usage"
        ), patch(
            "rctab.routers.accounting.usage.refresh_desired_states"
        ):

            # Execute
            await post_usage(usage_data, {"mock": "auth"})

            # Verify advisory lock was called with correct parameters
            mock_advisory_lock.assert_called_once()
            call_args = mock_advisory_lock.call_args
            assert call_args[0][1] == "usage_upload_2021-01-01_2021-01-01"

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.usage.advisory_lock")
    async def test_post_monthly_usage_uses_advisory_lock(
        self, mock_advisory_lock, test_db: Database
    ):
        """Test that post_monthly_usage route uses advisory lock correctly."""
        # Setup
        sub_id = await create_subscription(test_db)
        usage_data = AllUsage(
            usage_list=[
                Usage(
                    id=str(UUID(int=1)),
                    subscription_id=sub_id,
                    date="2021-02-01",
                    name="test-resource",
                    type="test-type",
                    billing_account_id="test-account",
                    billing_account_name="Test Account",
                    billing_profile_id="test-profile",
                    billing_profile_name="Test Profile",
                    account_owner_id="test-owner",
                    account_name="Test Account Name",
                    subscription_name="Test Subscription",
                    product="Test Product",
                    part_number="TEST-123",
                    meter_id="test-meter",
                    quantity=1.0,
                    effective_price=10.0,
                    cost=10.0,
                    unit_price=10.0,
                    billing_currency="USD",
                    resource_location="East US",
                    consumed_service="Test Service",
                    resource_id="test-resource-id",
                    resource_name="test-resource",
                    service_info1="",
                    service_info2="",
                    additional_info="",
                    invoice_section="",
                    cost_center="",
                    resource_group="test-rg",
                    monthly_upload=True,  # Required for monthly upload
                )
            ],
            start_date="2021-02-01",
            end_date="2021-02-28",
        )

        # Mock the context manager
        mock_context = AsyncMock()
        mock_advisory_lock.return_value.__aenter__.return_value = mock_context
        mock_advisory_lock.return_value.__aexit__.return_value = None

        # Mock other dependencies
        with patch(
            "rctab.routers.accounting.usage.insert_subscriptions_if_not_exists"
        ), patch("rctab.routers.accounting.usage.insert_usage"):

            # Execute
            await post_monthly_usage(usage_data, {"mock": "auth"})

            # Verify advisory lock was called with correct date range
            mock_advisory_lock.assert_called_once()
            call_args = mock_advisory_lock.call_args
            assert call_args[0][1] == "usage_upload_2021-02-01_2021-02-01"

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.usage.advisory_lock")
    async def test_lock_failure_returns_proper_error(
        self, mock_advisory_lock, test_db: Database
    ):
        """Test that lock acquisition failure returns proper HTTP error."""
        # Setup lock to fail
        mock_advisory_lock.side_effect = HTTPException(
            status_code=409, detail="Lock busy"
        )

        usage_data = AllUsage(
            usage_list=[],
            start_date="2021-01-01",
            end_date="2021-01-01",
        )

        # Verify the exception is propagated
        with pytest.raises(HTTPException) as exc_info:
            await post_usage(usage_data, {"mock": "auth"})

        assert exc_info.value.status_code == 409
        assert "Lock busy" in exc_info.value.detail


class TestCostRecoveryLocks:
    """Test that cost recovery routes properly use advisory locks."""

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.cost_recovery.advisory_lock_nowait")
    @patch("rctab.routers.accounting.cost_recovery.calc_cost_recovery")
    async def test_cost_recovery_app_uses_lock(
        self, mock_calc_cost_recovery, mock_advisory_lock
    ):
        """Test that cost recovery app route uses advisory lock."""
        import datetime

        from rctab.routers.accounting.cost_recovery import CostRecoveryMonth

        recovery_period = CostRecoveryMonth(first_day=datetime.date(2021, 3, 1))

        # Mock the context manager
        mock_context = AsyncMock()
        mock_advisory_lock.return_value.__aenter__.return_value = mock_context
        mock_advisory_lock.return_value.__aexit__.return_value = None

        mock_calc_cost_recovery.return_value = []

        # Execute
        await calc_cost_recovery_app(recovery_period, {"mock": "auth"})

        # Verify advisory lock was called with correct month
        mock_advisory_lock.assert_called_once()
        call_args = mock_advisory_lock.call_args
        assert call_args[0][1] == "cost_recovery_2021_03"

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.cost_recovery.advisory_lock_nowait")
    @patch("rctab.routers.accounting.cost_recovery.calc_cost_recovery")
    async def test_cost_recovery_cli_uses_lock(
        self, mock_calc_cost_recovery, mock_advisory_lock
    ):
        """Test that cost recovery CLI route uses advisory lock."""

        recovery_period = CostRecoveryMonth(first_day=datetime.date(2021, 4, 1))
        mock_user = UserRBAC(
            oid=UUID(int=1), username="test", has_access=True, is_admin=True
        )

        # Mock the context manager
        mock_context = AsyncMock()
        mock_advisory_lock.return_value.__aenter__.return_value = mock_context
        mock_advisory_lock.return_value.__aexit__.return_value = None

        mock_calc_cost_recovery.return_value = []

        # Execute
        await post_calc_cost_recovery_cli(recovery_period, mock_user)

        # Verify advisory lock was called with correct month
        mock_advisory_lock.assert_called_once()
        call_args = mock_advisory_lock.call_args
        assert call_args[0][1] == "cost_recovery_2021_04"


class TestMaterializedViewLocks:
    """Test that materialized view refresh uses advisory locks."""

    @pytest.mark.asyncio
    @patch("rctab.crud.accounting_models.advisory_lock")
    async def test_materialized_view_refresh_uses_lock(
        self, mock_advisory_lock, test_db: Database
    ):
        """Test that materialized view refresh uses advisory lock."""
        # Mock the context manager
        mock_context = AsyncMock()
        mock_advisory_lock.return_value.__aenter__.return_value = mock_context
        mock_advisory_lock.return_value.__aexit__.return_value = None

        # Mock the database execute call
        with patch.object(test_db, "execute", new_callable=AsyncMock) as mock_execute:
            await refresh_materialised_view(test_db, usage_view)

            # Verify advisory lock was called
            mock_advisory_lock.assert_called_once()
            call_args = mock_advisory_lock.call_args
            expected_lock_name = "materialized_view_refresh_accounting_usage_view"
            assert call_args[0][1] == expected_lock_name

            # Verify SQL was executed
            mock_execute.assert_called_once()
            sql_call = mock_execute.call_args[0][0]
            assert "REFRESH MATERIALIZED VIEW" in sql_call


class TestLockErrorHandling:
    """Test error handling in lock-protected routes."""

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.usage.advisory_lock")
    async def test_usage_route_handles_lock_timeout(
        self, mock_advisory_lock,
        test_db: Database
    ):
        """Test that usage routes handle lock timeout gracefully."""
        # Simulate lock timeout
        mock_advisory_lock.side_effect = HTTPException(
            status_code=503,
            detail="Could not acquire lock for operation 'usage_upload_2021-01-01_2021-01-01'. Another process may be performing the same operation.",
        )

        usage_data = AllUsage(
            usage_list=[],
            start_date="2021-01-01",
            end_date="2021-01-01",
        )

        with pytest.raises(HTTPException) as exc_info:
            await post_usage(usage_data, {"mock": "auth"})

        assert exc_info.value.status_code == 503
        assert "Could not acquire lock" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("rctab.routers.accounting.cost_recovery.advisory_lock_nowait")
    async def test_cost_recovery_handles_concurrent_execution(self, mock_advisory_lock):
        """Test that cost recovery handles concurrent execution attempts."""

        # Simulate another process already running cost recovery
        mock_advisory_lock.side_effect = HTTPException(
            status_code=409,
            detail="Operation 'cost_recovery_2021_05' is already in progress. Please try again later.",
        )

        recovery_period = CostRecoveryMonth(first_day=datetime.date(2021, 5, 1))

        with pytest.raises(HTTPException) as exc_info:
            await calc_cost_recovery_app(recovery_period, {"mock": "auth"})

        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.detail
