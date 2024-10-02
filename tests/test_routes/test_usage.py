import datetime
import json
from pathlib import Path
from typing import Iterable, List, Tuple, Union
from unittest.mock import AsyncMock
from uuid import UUID

import numpy as np
import pytest
import pytest_mock
import requests
from databases import Database
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from rctab_models.models import (
    AllCMUsage,
    AllUsage,
    BillingStatus,
    CMUsage,
    SubscriptionDetails,
    Usage,
)

from rctab.constants import ADMIN_OID, EMAIL_TYPE_USAGE_ALERT
from rctab.crud.accounting_models import usage_view
from rctab.crud.models import database
from rctab.routers.accounting.usage import get_usage, post_monthly_usage, post_usage
from tests.test_routes import api_calls, constants
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)
from tests.utils import print_list_diff

date_from = datetime.date.today()
date_to = datetime.date.today() + datetime.timedelta(days=30)
TICKET = "T001-12"


def test_post_usage(
    app_with_signed_billing_token: Tuple[FastAPI, str],
    mocker: pytest_mock.MockerFixture,
) -> None:
    auth_app, token = app_with_signed_billing_token
    example_usage_file = Path("tests/data/example.json")

    example_usage_data: Iterable[dict] = json.loads(
        example_usage_file.read_text(encoding="utf-8")
    )
    dates = {item["date"] for item in example_usage_data}

    post_data = AllUsage(
        usage_list=example_usage_data, start_date=min(dates), end_date=max(dates)
    )

    with TestClient(auth_app) as client:
        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.usage.refresh_desired_states", mock_refresh
        )

        resp = client.post(
            "usage/all-usage",
            content=post_data.model_dump_json().encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )

        assert resp.status_code == 200

        # Posting the usage data should have the side effect of
        # refreshing the desired states
        mock_refresh.assert_called_once_with(
            UUID(ADMIN_OID), list({x.subscription_id for x in post_data.usage_list})
        )

        get_resp = client.get(
            "usage/all-usage",
            headers={"authorization": "Bearer " + token},
        )

        assert get_resp.status_code == 200

        resp_data = get_resp.json()
        assert np.isclose(
            sum(i["total_cost"] for i in resp_data),
            sum(i.total_cost for i in post_data.usage_list),
        )


def test_post_usage2(
    mocker: pytest_mock.MockerFixture,
) -> None:
    del mocker


def test_write_usage(
    app_with_signed_billing_token: Tuple[FastAPI, str], mocker: MockerFixture
) -> None:
    auth_app, token = app_with_signed_billing_token
    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        approved_from=date_from,
        approved_to=date_to,
        always_on=False,
        approved=500.0,
        allocated=130.0,
        cost=75.34,
        amortised_cost=0.0,
        total_cost=75.34,
        first_usage=datetime.date.today(),
        latest_usage=datetime.date.today(),
        remaining=130.0 - 75.34,
        desired_status_info=None,
        abolished=False,
    )

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=False)

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

        assert (
            api_calls.create_usage(
                client, token, constants.TEST_SUB_UUID, cost=50.0
            ).status_code
            == 200
        )

        assert (
            api_calls.create_usage(
                client, token, constants.TEST_SUB_UUID, cost=20.0
            ).status_code
            == 200
        )

        assert (
            api_calls.create_usage(
                client, token, constants.TEST_SUB_UUID, cost=5.34
            ).status_code
            == 200
        )

        api_calls.assert_subscription_status(client, expected_details)


def test_greater_budget(
    app_with_signed_billing_token: Tuple[FastAPI, str], mocker: MockerFixture
) -> None:
    auth_app, token = app_with_signed_billing_token
    expected_details = SubscriptionDetails(
        subscription_id=constants.TEST_SUB_UUID,
        approved_from=date_from,
        approved_to=date_to,
        always_on=False,
        approved=500.0,
        allocated=130.0,
        cost=150.0,
        amortised_cost=0.0,
        total_cost=150.0,
        remaining=130.0 - 150.0,
        first_usage=datetime.date.today(),
        latest_usage=datetime.date.today(),
        desired_status_info=BillingStatus.OVER_BUDGET,
        abolished=False,
    )

    with TestClient(auth_app) as client:
        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        api_calls.create_subscription(client, constants.TEST_SUB_UUID)
        api_calls.set_persistence(client, constants.TEST_SUB_UUID, always_on=False)

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

        assert (
            api_calls.create_usage(
                client, token, constants.TEST_SUB_UUID, cost=100.0
            ).status_code
            == 200
        )

        assert (
            api_calls.create_usage(
                client, token, constants.TEST_SUB_UUID, cost=50.0
            ).status_code
            == 200
        )

        api_calls.assert_subscription_status(client, expected_details)


def _post_costmanagement(
    client: Union[requests.Session, TestClient],
    token: str,
    data: List[CMUsage],
) -> requests.Response:
    all_usage = AllCMUsage(cm_usage_list=data)
    post_client = client.post(
        "/usage/all-cm-usage",
        headers={"authorization": "Bearer " + token},
        content=all_usage.model_dump_json().encode("utf-8"),
    )  # type: ignore
    return post_client  # type: ignore


def _get_costmanagement(
    client: Union[requests.Session, TestClient], token: str
) -> requests.Response:
    return client.get(
        "/usage/all-cm-usage", headers={"authorization": "Bearer " + token}
    )  # type: ignore


def test_write_read_costmanagement(
    app_with_signed_billing_token: Tuple[FastAPI, str]
) -> None:
    """POST some cost-management data, GET it back, and check that the response matches
    the input. Do it twice, because the first time inserts new subscriptions, whereas
    the second updates existing ones.
    """
    auth_app, token = app_with_signed_billing_token
    end_date = datetime.datetime.now().date()
    start_date = end_date - datetime.timedelta(days=364)
    sub_data_in = [
        CMUsage(
            subscription_id=constants.TEST_SUB_UUID,
            name="sub1",
            start_datetime=start_date,
            end_datetime=end_date,
            cost=12.0,
            billing_currency="GBP",
        ),
        CMUsage(
            subscription_id=constants.TEST_SUB_2_UUID,
            name="sub2",
            start_datetime=start_date,
            end_datetime=end_date,
            cost=144.0,
            billing_currency="GBP",
        ),
    ]
    with TestClient(auth_app) as client:
        for _ in range(2):
            response = _post_costmanagement(client, token, sub_data_in)
            assert response.status_code == 200
            response = _get_costmanagement(client, token)
            assert response.status_code == 200
            sub_data_out = response.json()
            sub_data_out = [CMUsage(**d) for d in sub_data_out]
            assert len(sub_data_in) == len(sub_data_out)
            assert sub_data_out == sub_data_in


def test_post_monthly_usage(
    app_with_signed_billing_token: Tuple[FastAPI, str],
    mocker: pytest_mock.MockerFixture,
) -> None:
    auth_app, token = app_with_signed_billing_token

    example_1_file = Path("tests/data/example-monthly-wrong.json")
    example_1_data = json.loads(example_1_file.read_text(encoding="utf-8"))
    dates_ex1 = {item["date"] for item in example_1_data}

    example_2_file = Path("tests/data/example-monthly-correct.json")
    example_2_data = json.loads(example_2_file.read_text(encoding="utf-8"))
    dates_ex2 = {item["date"] for item in example_2_data}

    post_example_1_data = AllUsage(
        usage_list=example_1_data, start_date=min(dates_ex1), end_date=max(dates_ex1)
    )
    post_example_2_data = AllUsage(
        usage_list=example_2_data, start_date=min(dates_ex2), end_date=max(dates_ex2)
    )

    with TestClient(auth_app) as client:
        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.usage.refresh_desired_states", mock_refresh
        )

        # Should error if there is no data.
        resp = client.post(
            "usage/monthly-usage",
            content=AllUsage(
                usage_list=[], start_date="2021-04-01", end_date="2021-04-30"
            )
            .model_dump_json()
            .encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )

        assert resp.status_code == 400
        assert "must have at least one record" in resp.text

        resp = client.post(
            "usage/monthly-usage",
            content=post_example_1_data.model_dump_json().encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )

        assert resp.status_code == 400
        assert "data must have the monthly_upload column" in resp.text

        resp = client.post(
            "usage/monthly-usage",
            content=post_example_2_data.model_dump_json().encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )

        assert resp.status_code == 200

        get_resp = client.get(
            "usage/all-usage",
            headers={"authorization": "Bearer " + token},
        )

        assert get_resp.status_code == 200

        resp_data = get_resp.json()
        assert np.isclose(
            sum(i["total_cost"] for i in resp_data),
            sum(i.total_cost for i in post_example_2_data.usage_list),
        )


@pytest.mark.asyncio
async def test_monthly_usage_2(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    sub1 = await create_subscription(test_db)
    sub2 = await create_subscription(test_db)

    await post_usage(
        AllUsage(
            usage_list=[
                Usage(
                    id=str(UUID(int=0)),
                    subscription_id=sub1,
                    date="2024-04-01",
                    total_cost=1.0,
                    invoice_section="-",
                ),
                Usage(
                    id=str(UUID(int=1)),
                    subscription_id=sub2,
                    date="2024-04-02",
                    total_cost=2.0,
                    invoice_section="-",
                ),
                Usage(
                    id=str(UUID(int=2)),
                    subscription_id=sub1,
                    date="2024-04-03",
                    total_cost=4.0,
                    invoice_section="-",
                ),
            ],
            start_date="2024-04-01",
            end_date="2024-04-03",
        ),
        {"mock": "authentication"},
    )

    await post_monthly_usage(
        AllUsage(
            usage_list=[
                Usage(
                    id=str(UUID(int=3)),
                    subscription_id=sub1,
                    date="2024-04-01",
                    total_cost=10.0,
                    invoice_section="-",
                    monthly_upload=datetime.date.today(),
                ),
                Usage(
                    id=str(UUID(int=4)),
                    subscription_id=sub1,
                    date="2024-04-02",
                    total_cost=0.5,
                    invoice_section="-",
                    monthly_upload=datetime.date.today(),
                ),
            ],
            start_date="2024-04-01",
            end_date="2024-04-02",
        ),
        {"mock": "authentication"},
    )
    all_usage = await get_usage()
    assert all_usage == [
        Usage(
            id=str(UUID(int=2)),
            subscription_id=sub1,
            date="2024-04-03",
            total_cost=4.0,
            invoice_section="-",
        ),
        Usage(
            id=str(UUID(int=3)),
            subscription_id=sub1,
            date="2024-04-01",
            total_cost=10.0,
            invoice_section="-",
            monthly_upload=datetime.date.today(),
        ),
        Usage(
            id=str(UUID(int=4)),
            subscription_id=sub1,
            date="2024-04-02",
            total_cost=0.5,
            invoice_section="-",
            monthly_upload=datetime.date.today(),
        ),
    ]


@pytest.mark.asyncio
async def test_post_usage_refreshes_view(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we refresh the view."""

    mock_refresh = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.usage.refresh_materialised_view", mock_refresh
    )

    await post_usage(
        AllUsage(usage_list=[], start_date="2021-04-01", end_date="2021-04-30"),
        {"mock": "authentication"},
    )

    mock_refresh.assert_called_once_with(test_db, usage_view)


def test_post_usage_emails(
    app_with_signed_billing_token: Tuple[FastAPI, str],
    mocker: pytest_mock.MockerFixture,
) -> None:
    """Check that we send the correct emails."""

    auth_app, token = app_with_signed_billing_token
    example_usage_file = Path("tests/data/example.json")
    example_usage_data = json.loads(example_usage_file.read_text(encoding="utf-8"))
    dates = {item["date"] for item in example_usage_data}
    post_data = AllUsage(
        usage_list=example_usage_data, start_date=min(dates), end_date=max(dates)
    )

    with TestClient(auth_app) as client:
        mock_send_emails = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_emails
        )

        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.usage.refresh_desired_states", mock_refresh
        )

        resp = client.post(
            "usage/all-usage",
            content=post_data.model_dump_json().encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )
        assert resp.status_code == 200

        unique_subs = list({x.subscription_id for x in post_data.usage_list})
        # These subs have no allocations at all so any usage should be over-budget
        try:
            expected = [
                mocker.call(
                    database,
                    subscription_id,
                    "usage_alert.html",
                    "95.0% of allocated budget used by your Azure subscription:",
                    EMAIL_TYPE_USAGE_ALERT,
                    {"percentage_used": 95.0, "extra_info": str(95.0)},
                )
                for subscription_id in unique_subs
            ]
            mock_send_emails.assert_has_calls(expected)
        except AssertionError as e:
            print_list_diff(expected, mock_send_emails.call_args_list)
            raise e

        mock_refresh.assert_called_once_with(UUID(ADMIN_OID), unique_subs)
