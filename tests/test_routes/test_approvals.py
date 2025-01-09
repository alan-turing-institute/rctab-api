import datetime
import json
from unittest.mock import AsyncMock

from devtools import debug
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from rctab_models.models import Approval, SubscriptionDetails

from rctab.constants import EMAIL_TYPE_SUB_APPROVAL
from rctab.crud.models import database
from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import api_calls, constants
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import


def test_approve_date_from_in_past(auth_app: FastAPI, mocker: MockerFixture) -> None:
    """Approve with date_from in the past."""

    date_from = datetime.date.today() - datetime.timedelta(days=31)
    date_to = datetime.date.today() + datetime.timedelta(days=30)

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        assert result.status_code == 400

        assert (
            result.json()["detail"]
            == f"Date from ({date_from.isoformat()}) cannot be more than 30 days in the past. "
            "This check ensures that you are not approving a subscription that has already been cancelled "
            "for more than 30 days."
        )


def test_approve_date_from_in_past_forced(
    auth_app: FastAPI, mocker: MockerFixture
) -> None:
    """Approve with date_from in the past."""

    date_from = datetime.date.today() - datetime.timedelta(days=31)
    date_to = datetime.date.today() + datetime.timedelta(days=30)

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
            force=True,
        )

        assert result.status_code == 200


def test_approve_date_to_in_past(auth_app: FastAPI, mocker: MockerFixture) -> None:
    """Approve with date_to in the past."""

    date_from = datetime.date.today()
    date_to = datetime.date.today() - datetime.timedelta(days=1)

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        assert result.status_code == 400
        assert (
            result.json()["detail"]
            == f"Date to ({date_to.isoformat()}) cannot be in the past"
        )


def test_approve_date_to_before_date_from(
    auth_app: FastAPI, mocker: MockerFixture
) -> None:
    """Approve with date_to before date_from."""

    date_from = datetime.date.today() + datetime.timedelta(days=10)
    date_to = datetime.date.today() + datetime.timedelta(days=9)

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        assert result.status_code == 400
        debug(result.json())
        assert (
            result.json()["detail"]
            == f"Date from ({date_from.isoformat()}) cannot be greater than date to ({date_to.isoformat()})"
        )


def test_successful_approval(auth_app: FastAPI, mocker: MockerFixture) -> None:
    """Successful approval."""

    date_from = datetime.date.today()
    date_to = datetime.date.today() + datetime.timedelta(days=30)

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=datetime.date.today().isoformat(),
        approved_to=(datetime.date.today() + datetime.timedelta(days=30)).isoformat(),
        always_on=True,
        approved=100.0,
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

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        assert result.status_code == 200

        api_calls.assert_subscription_status(client, expected_details=expected_details)

        # We will receive calls for the persistence, the approval
        # and the change of desired state
        mock_send_email.assert_any_call(
            database,
            constants.TEST_SUB_UUID,
            "new_approval.html",
            "New approval for your Azure subscription:",
            EMAIL_TYPE_SUB_APPROVAL,
            Approval(
                allocate=False,
                amount=100.0,
                currency="GBP",
                date_from=date_from,
                date_to=date_to,
                sub_id=constants.TEST_SUB_UUID,
                ticket="T001-12",
            ).model_dump(),
        )


def test_approval_wrong_currency(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from = datetime.date.today()
    date_to = datetime.date.today() + datetime.timedelta(days=30)

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=True)

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-13",
            amount=100.0,
            currency="USD",
            date_from=date_from,
            date_to=date_to,
            allocate=False,
        )

        assert result.status_code == 400
        assert (
            result.json()["detail"]
            == "Other type of currency than GBP is not implemented yet."
        )


def test_multi_approvals(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from_1 = datetime.date.today()
    date_to_1 = datetime.date.today() + datetime.timedelta(days=30)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=40)

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=date_from_1,
        approved_to=date_to_2,
        always_on=True,
        approved=200.0,
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

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        assert result.status_code == 200

        api_calls.assert_subscription_status(client, expected_details=expected_details)


def test_approvals_overlap(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from_1 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_1 = datetime.date.today() + datetime.timedelta(days=40)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=42)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=50)

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
            ticket="T001-13",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        assert (
            result.json()["detail"]
            == f"Date from ({date_from_2.isoformat()}) should be equal or less than ({date_to_1.isoformat()})"
        )

        debug(result.json())


def test_approvals_overlap2(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from_1 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_1 = datetime.date.today() + datetime.timedelta(days=40)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=1)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=39)

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
            ticket="T001-13",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        assert (
            result.json()["detail"]
            == f"Date to ({date_to_2.isoformat()}) should be equal or greater than ({date_to_1.isoformat()})"
        )

        debug(result.json())


def test_negative_approval_overlap_min_max(
    auth_app: FastAPI, mocker: MockerFixture
) -> None:
    """Negative approvals must overlap the min and max dates of all approvals"""
    date_from_1 = datetime.date.today()
    date_to_1 = datetime.date.today() + datetime.timedelta(days=30)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=40)

    date_from_3 = datetime.date.today() + datetime.timedelta(days=1)
    date_to_3 = datetime.date.today() + datetime.timedelta(days=40)

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
            ticket="T001-12",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-15",
            amount=-50.0,
            date_from=date_from_3,
            date_to=date_to_3,
            allocate=False,
        )

        assert result.status_code == 400

        assert result.json()["detail"] == (
            f"Dates from and to ({date_from_3.isoformat()} - {date_to_3.isoformat()}) "
            f"must align with the min-max ({date_from_1.isoformat()} - {date_to_3.isoformat()}) "
            "approval period."
        )
        debug(result.json())


def test_negative_approval_too_large(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from_1 = datetime.date.today()
    date_to_1 = datetime.date.today() + datetime.timedelta(days=30)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=40)

    date_from_3 = datetime.date.today()
    date_to_3 = datetime.date.today() + datetime.timedelta(days=40)

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
            ticket="T001-12",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-15",
            amount=-500.0,
            date_from=date_from_3,
            date_to=date_to_3,
            allocate=False,
        )

        assert result.status_code == 400

        debug(result.json()["detail"])
        assert (
            result.json()["detail"]
            == "The amount of unused budget (200.0) is less than the negative allocation (500.0). Can only remove (200.0)."
        )
        debug(result.json())


def test_negative_approval_success(auth_app: FastAPI, mocker: MockerFixture) -> None:
    date_from_1 = datetime.date.today()
    date_to_1 = datetime.date.today() + datetime.timedelta(days=30)

    date_from_2 = datetime.date.today() + datetime.timedelta(days=2)
    date_to_2 = datetime.date.today() + datetime.timedelta(days=40)

    date_from_3 = datetime.date.today()
    date_to_3 = datetime.date.today() + datetime.timedelta(days=40)

    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        name=None,
        role_assignments=None,
        status=None,
        approved_from=date_from_3,
        approved_to=date_to_3,
        always_on=True,
        approved=150.0,
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

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=date_from_1,
            date_to=date_to_1,
            allocate=False,
        )

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-14",
            amount=100.0,
            date_from=date_from_2,
            date_to=date_to_2,
            allocate=False,
        )

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-15",
            amount=-50.0,
            date_from=date_from_3,
            date_to=date_to_3,
            allocate=False,
        )

        assert result.status_code == 200
        api_calls.assert_subscription_status(client, expected_details=expected_details)

        # Check we get three records back from approvals
        result = client.request(
            "GET", PREFIX + "/approvals", json={"sub_id": str(constants.TEST_SUB_UUID)}
        )  # type: ignore

        assert result.status_code == 200

        result_dict = json.loads(result.content.decode("utf-8"))

        assert len(result_dict) == 3


def test_post_approval_refreshes_desired_states(
    auth_app: FastAPI, mocker: MockerFixture
) -> None:
    with TestClient(auth_app) as client:
        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.approvals.refresh_desired_states", mock_refresh
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
            ticket="T001-12",
            amount=100.0,
            date_from=datetime.date.today(),
            date_to=datetime.date.today() + datetime.timedelta(days=1),
            allocate=False,
        ).raise_for_status()

        # Posting an approval should have the side effect of
        # refreshing the desired states
        mock_refresh.assert_called_once_with(
            constants.ADMIN_UUID, [constants.TEST_SUB_UUID]
        )


def test_negative_approval_deallocates(
    auth_app: FastAPI, mocker: MockerFixture
) -> None:
    """A negative approval should deallocate the budget."""
    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(
            client, constants.TEST_SUB_UUID
        ).raise_for_status()

        api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-12",
            amount=100.0,
            date_from=datetime.date.today(),
            date_to=datetime.date.today() + datetime.timedelta(days=1),
            allocate=True,
        ).raise_for_status()

        # Check total approval amount is 100.
        result = client.get(
            PREFIX + "/subscription",
            params={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200
        result_json = result.json()
        assert len(result_json) == 1
        details = SubscriptionDetails(**result_json[0])

        assert details.allocated == 100.0
        assert details.approved == 100.0

        result = api_calls.create_approval(
            client,
            constants.TEST_SUB_UUID,
            ticket="T001-13",
            amount=-100.0,
            date_from=datetime.date.today(),
            date_to=datetime.date.today() + datetime.timedelta(days=1),
            allocate=True,
        )

        assert result.status_code == 200, result.content.decode("utf-8")

        # Check total approval amount is 0.
        result = client.get(
            PREFIX + "/subscription",
            params={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200
        result_json = result.json()
        assert len(result_json) == 1
        details = SubscriptionDetails(**result_json[0])

        assert details.allocated == 0.0
        assert details.approved == 0.0
