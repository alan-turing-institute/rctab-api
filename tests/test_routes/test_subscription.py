import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import constants


@pytest.mark.asyncio
async def test_get_subscription(
    auth_app_with_tx: FastAPI,  # pylint: disable=redefined-outer-name
) -> None:
    """Getting a subscription that doesn't exist."""

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.request(
            "GET",
            PREFIX + "/subscription",
            params={"sub_id": str(constants.TEST_SUB_UUID)},
        )

    assert result.status_code == 404


@pytest.mark.asyncio
async def test_post_subscription(
    auth_app_with_tx: FastAPI,  # pylint: disable=redefined-outer-name
) -> None:
    """Register a subscription"""

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_post_subscription_twice(
    auth_app_with_tx: FastAPI,  # pylint: disable=redefined-outer-name
) -> None:
    """Can't register it if it already exists"""

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200

        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 409


# def test_get_subscription_summary(
#     app_with_signed_status_and_controller_tokens: Tuple[FastAPI, str, str],
# ) -> None:
#     """Get subscription information"""
#     auth_app, status_token, _ = app_with_signed_status_and_controller_tokens
#
#     expected_details = SubscriptionDetails(
#         subscription_id=constants.TEST_SUB_UUID,
#         name="sub display name",
#         role_assignments=(),
#         status=SubscriptionState.ENABLED,
#         approved_from=None,
#         approved_to=None,
#         always_on=None,
#         approved=0.0,
#         allocated=0.0,
#         cost=0.0,
#         amortised_cost=0.0,
#         total_cost=0.0,
#         remaining=0.0,
#         first_usage=None,
#         latest_usage=None,
#         desired_status_info=BillingStatus.EXPIRED,
#         abolished=False,
#     )
#
#     with TestClient(auth_app) as client:
#
#         result = api_calls.create_subscription_detail(
#             client,
#             status_token,
#             constants.TEST_SUB_UUID,
#             SubscriptionState.ENABLED,
#             role_assignments=(),
#             display_name="sub display name",
#         )
#         assert result.status_code == 200
#
#         api_calls.assert_subscription_status(client, expected_details=expected_details)
