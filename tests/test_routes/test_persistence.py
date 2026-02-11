from unittest.mock import ANY, AsyncMock

import pytest
import pytest_mock
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rctab_models.models import SubscriptionDetails

from rctab.routers.accounting.routes import PREFIX
from tests.test_routes import constants

# pylint: disable=redefined-outer-name


@pytest.mark.asyncio
async def test_post_persistent(
    auth_app_with_tx: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    """Set subscription to always on."""
    mock_send_email = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200

        result = await client.post(
            PREFIX + "/persistent",
            json={"sub_id": str(constants.TEST_SUB_UUID), "always_on": True},
        )

    assert result.status_code == 200
    mock_send_email.assert_called_once_with(
        ANY,
        constants.TEST_SUB_UUID,
        "persistence_change.html",
        "Persistence change for your Azure subscription:",
        "subscription persistence",
        {"sub_id": constants.TEST_SUB_UUID, "always_on": True},
    )


@pytest.mark.asyncio
async def test_get_persistent(
    auth_app_with_tx: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    """Check we're now persistent."""
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

    mock_send_email = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200

        result = await client.post(
            PREFIX + "/persistent",
            json={"sub_id": str(constants.TEST_SUB_UUID), "always_on": True},
        )
        assert result.status_code == 200

        result = await client.get(
            PREFIX + "/subscription",
            params={"sub_id": str(constants.TEST_SUB_UUID)},
        )

    assert result.status_code == 200
    result_json = result.json()
    assert len(result_json) == 1
    assert expected_details == SubscriptionDetails(**result_json[0])
    mock_send_email.assert_called_once_with(
        ANY,
        constants.TEST_SUB_UUID,
        "persistence_change.html",
        "Persistence change for your Azure subscription:",
        "subscription persistence",
        {"sub_id": constants.TEST_SUB_UUID, "always_on": True},
    )


@pytest.mark.asyncio
async def test_post_persistent_email_failure_does_not_rollback(
    auth_app_with_tx: FastAPI, mocker: pytest_mock.MockerFixture
) -> None:
    """Persistence update should survive notification failures."""
    mock_send_email = AsyncMock(side_effect=RuntimeError("email send failed"))
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
    )

    async with AsyncClient(
        transport=ASGITransport(app=auth_app_with_tx), base_url="http://test"
    ) as client:
        result = await client.post(
            PREFIX + "/subscription",
            json={"sub_id": str(constants.TEST_SUB_UUID)},
        )
        assert result.status_code == 200

        result = await client.post(
            PREFIX + "/persistent",
            json={"sub_id": str(constants.TEST_SUB_UUID), "always_on": True},
        )
        assert result.status_code == 200

        result = await client.get(
            PREFIX + "/subscription",
            params={"sub_id": str(constants.TEST_SUB_UUID)},
        )

    assert result.status_code == 200
    assert result.json()[0]["always_on"] is True
