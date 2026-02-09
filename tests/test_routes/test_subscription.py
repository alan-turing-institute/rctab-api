import pytest
from typing import Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient
from rctab_models.models import BillingStatus, SubscriptionDetails, SubscriptionState
from httpx import ASGITransport, AsyncClient

from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import api_calls, constants


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


def test_get_subscription_summary(
    app_with_signed_status_and_controller_tokens: Tuple[FastAPI, str, str],
) -> None:
    """Get subscription information"""
    auth_app, status_token, _ = app_with_signed_status_and_controller_tokens

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name="sub display name",
        role_assignments=(),
        status=SubscriptionState.ENABLED,
        approved_from=None,
        approved_to=None,
        always_on=None,
        approved=0.0,
        allocated=0.0,
        cost=0.0,
        amortised_cost=0.0,
        total_cost=0.0,
        remaining=0.0,
        first_usage=None,
        latest_usage=None,
        desired_status_info=BillingStatus.EXPIRED,
        abolished=False,
    )

    with TestClient(auth_app) as client:

        result = api_calls.create_subscription_detail(
            client,
            status_token,
            constants.TEST_SUB_UUID,
            SubscriptionState.ENABLED,
            role_assignments=(),
            display_name="sub display name",
        )
        assert result.status_code == 200

        api_calls.assert_subscription_status(client, expected_details=expected_details)


# here
def test_get_subscription_id(
    app_with_signed_status_and_controller_tokens: Tuple[FastAPI, str, str],
) -> None:
    """Returns a subscription id, given a subscription name."""
    (auth_app, status_token, _) = app_with_signed_status_and_controller_tokens

    with TestClient(auth_app) as client:
        # Check the scenario with no matches.
        result = client.get(
            PREFIX + "/subscription-id",
            params={"display_name": "-"},
        )
        result.raise_for_status()
        assert result.json() == []

        # Add a subscription and make sure we can get its ID.
        api_calls.create_subscription(
            client, constants.TEST_SUB_UUID
        ).raise_for_status()

        api_calls.create_subscription_detail(
            client=client,
            token=status_token,
            subscription_id=constants.TEST_SUB_UUID,
            state=SubscriptionState.ENABLED,
            display_name="MyDisplayName",
        ).raise_for_status()

        result = client.get(
            PREFIX + "/subscription-id",
            params={"display_name": "MyDisplayName"},
        )
        result.raise_for_status()
        assert [UUID(x) for x in result.json()] == [constants.TEST_SUB_UUID]

        # Check multiple matches.
        api_calls.create_subscription(
            client, constants.TEST_SUB_2_UUID
        ).raise_for_status()

        api_calls.create_subscription_detail(
            client=client,
            token=status_token,
            subscription_id=constants.TEST_SUB_2_UUID,
            state=SubscriptionState.ENABLED,
            display_name="MyDisplayName",
        ).raise_for_status()

        result = client.get(
            PREFIX + "/subscription-id",
            params={"display_name": "MyDisplayName"},
        )
        result.raise_for_status()
        assert [UUID(x) for x in result.json()] in [
            [constants.TEST_SUB_2_UUID, constants.TEST_SUB_UUID],
            [constants.TEST_SUB_UUID, constants.TEST_SUB_2_UUID],
        ]
