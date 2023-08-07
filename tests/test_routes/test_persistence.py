from unittest.mock import AsyncMock

import pytest_mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rctab.crud.models import database
from rctab.crud.schema import SubscriptionDetails
from tests.test_routes import api_calls, constants


def test_post_persistent(auth_app: FastAPI, mocker: pytest_mock.MockerFixture) -> None:
    """Set subscription to always on"""

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)

        result = api_calls.set_persistence(
            client, constants.TEST_SUB_UUID, always_on=True
        )

        assert result.status_code == 200

        mock_send_email.assert_called_once_with(
            database,
            constants.TEST_SUB_UUID,
            "persistence_change.html",
            "Persistence change for your Azure subscription:",
            "subscription persistence",
            {"sub_id": constants.TEST_SUB_UUID, "always_on": True},
        )


def test_get_persistent(auth_app: FastAPI, mocker: pytest_mock.MockerFixture) -> None:
    """Check we're now persistent"""

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=None,
        approved_to=None,
        always_on=True,
        approved=0.0,
        allocated=0.0,
        cost=0.0,
        amortised_cost=0.0,
        total_cost=0.0,
        remaining=0.0,
        first_usage=None,
        latest_usage=None,
        desired_status_info=None,
        abolished=False,
    )

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)
        api_calls.assert_subscription_status(client, expected_details=expected_details)

        mock_send_email.assert_called_once_with(
            database,
            constants.TEST_SUB_UUID,
            "persistence_change.html",
            "Persistence change for your Azure subscription:",
            "subscription persistence",
            {"sub_id": constants.TEST_SUB_UUID, "always_on": True},
        )
