import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_mock
from devtools import debug
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rctab.crud.models import database
from rctab.crud.schema import SubscriptionDetails
from tests.test_routes import api_calls, constants

date_from = datetime.date.today()
date_to = datetime.date.today() + datetime.timedelta(days=30)
TICKET = "T001-12"


def test_over_allocate(auth_app: FastAPI, mocker: pytest_mock.MockerFixture) -> None:
    """Try to over-allocate credit."""

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        result = api_calls.create_allocation(
            client, constants.TEST_SUB_UUID, TICKET, 200
        )

    assert result.status_code == 400
    result_json = result.json()
    debug(result_json)
    assert (
        result_json["detail"]
        == "Allocation (200.0) cannot be bigger than the unallocated budget (100.0)."
    )


def test_negative_allocation(
    auth_app: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        result = api_calls.create_allocation(
            client, constants.TEST_SUB_UUID, TICKET, -50
        )

    assert result.status_code == 400
    result_json = result.json()
    debug(result_json)
    assert (
        result_json["detail"]
        == "Negative allocation (50.0) cannot be bigger than the unused budget (0.0)."
    )


def test_unknown_desired_status(
    auth_app: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    """No allocations so desired status should be None"""

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=date_from,
        approved_to=date_to,
        always_on=True,
        approved=100.0,
        allocated=0.0,
        cost=0.0,
        amortised_cost=0.0,
        total_cost=0.0,
        remaining=0.0,
        # billing_status=BillingStatus.ACTIVE,
        first_usage=None,
        latest_usage=None,
        # desired_status=True,
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

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        api_calls.assert_subscription_status(client, expected_details)


@pytest.mark.parametrize("amount", [0.01, 50.0, 99.9999, 100.0])
def test_successful_allocations(
    auth_app: FastAPI, mocker: pytest_mock.MockerFixture, amount: float
) -> None:
    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=date_from,
        approved_to=date_to,
        always_on=True,
        approved=100.0,
        allocated=amount,
        cost=0.0,
        amortised_cost=0.0,
        total_cost=0.0,
        remaining=amount,
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

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        result = api_calls.create_allocation(
            client, constants.TEST_SUB_UUID, TICKET, amount
        )

        assert result.status_code == 200

        api_calls.assert_subscription_status(client, expected_details)

        mock_send_email.assert_called_with(
            database,
            constants.TEST_SUB_UUID,
            "new_allocation.html",
            "New allocation for your Azure subscription:",
            "subscription allocation",
            {
                "amount": amount,
                "currency": "GBP",
                "sub_id": constants.TEST_SUB_UUID,
                "ticket": TICKET,
            },
        )


def test_negative_too_large(
    auth_app: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        api_calls.create_allocation(client, constants.TEST_SUB_UUID, TICKET, 100)

        result = api_calls.create_allocation(
            client, constants.TEST_SUB_UUID, TICKET, -200
        )

        assert result.status_code == 400

        result_json = result.json()
        debug(result_json)
        assert (
            result_json["detail"]
            == "Negative allocation (200.0) cannot be bigger than the unused budget (100.0)."
        )


def test_9(auth_app: FastAPI, mocker: pytest_mock.MockerFixture) -> None:
    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        approved_from=date_from,
        approved_to=date_to,
        always_on=True,
        approved=500.0,
        allocated=130.0,
        cost=0.0,
        amortised_cost=0.0,
        total_cost=0.0,
        remaining=130.00,
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

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=500.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        api_calls.create_allocation(client, constants.TEST_SUB_UUID, TICKET, 100)

        api_calls.create_allocation(client, constants.TEST_SUB_UUID, TICKET, -20)

        api_calls.create_allocation(client, constants.TEST_SUB_UUID, TICKET, 50)

        api_calls.assert_subscription_status(client, expected_details)


def test_topup_refreshes_desired_states(
    auth_app: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    # pylint: disable=useless-super-delegation

    with TestClient(auth_app) as client:
        mock_refresh = AsyncMock()

        mocker.patch(
            "rctab.routers.accounting.allocations.refresh_desired_states", mock_refresh
        )

        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(
            client, constants.TEST_SUB_UUID
        ).raise_for_status()
        api_calls.set_persistence(
            client, constants.TEST_SUB_UUID, always_on=True
        ).raise_for_status()

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket=TICKET,
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        ).raise_for_status()

        api_calls.create_allocation(
            client, constants.TEST_SUB_UUID, TICKET, 100.0
        ).raise_for_status()

        # Topping up a subscription should have the side effect of
        # refreshing the desired states
        mock_refresh.assert_called_once_with(
            constants.ADMIN_UUID, [constants.TEST_SUB_UUID]
        )
