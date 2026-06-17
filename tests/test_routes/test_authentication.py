"""One test per protected route verifying that unauthenticated requests are rejected."""

import pytest
from httpx import ASGITransport, AsyncClient

from rctab import app


@pytest.fixture(autouse=True)
def no_auth_overrides() -> None:
    """Ensure dependency overrides are clear so real auth is enforced."""
    app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_topup_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/topup")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_allocations_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/allocations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_approvals_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/approvals")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_approve_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/approve")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_cli_cost_recovery_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/cli-cost-recovery")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_cli_cost_recovery_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/cli-cost-recovery")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_finance_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/finance")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_finances_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/finances")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_put_finance_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/accounting/finances/1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_finance_by_id_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/finances/1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_finance_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/accounting/finances/1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_persistent_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/persistent")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_subscription_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/subscription")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_subscription_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/subscription")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_subscription_id_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/subscription-id")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_all_usage_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/all-usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_all_cm_usage_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/all-cm-usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_all_status_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/all-status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_app_cost_recovery_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/app-cost-recovery")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_all_usage_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/all-usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_monthly_usage_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/monthly-usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_all_cm_usage_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/accounting/all-cm-usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_desired_states_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/accounting/desired-states")
    assert response.status_code == 401
