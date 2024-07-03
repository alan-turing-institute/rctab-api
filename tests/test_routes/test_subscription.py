from typing import Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rctab.crud.schema import BillingStatus, SubscriptionDetails, SubscriptionState
from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import api_calls, constants


def test_get_subscription(auth_app: FastAPI) -> None:
    """Getting a subscription that doesn't exist."""

    with TestClient(auth_app) as client:
        result = client.request(
            "GET",
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )

    assert result.status_code == 404


def test_post_subscription(auth_app: FastAPI) -> None:
    """Register a subscription"""

    with TestClient(auth_app) as client:
        result = api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        assert result.status_code == 200


def test_post_subscription_twice(auth_app: FastAPI) -> None:
    """Can't register it if it already exists"""

    with TestClient(auth_app) as client:

        result = api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        assert result.status_code == 200

        result = api_calls.create_subscription(client, constants.TEST_SUB_UUID)
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
