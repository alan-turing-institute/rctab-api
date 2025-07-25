import datetime
from typing import Optional, Tuple
from uuid import UUID, uuid4

from devtools import debug
from fastapi.testclient import TestClient
from httpx import Response
from rctab_models.models import (
    AllSubscriptionStatus,
    AllUsage,
    RoleAssignment,
    SubscriptionDetails,
    SubscriptionState,
    SubscriptionStatus,
    Usage,
)

from rctab.routers.accounting.routes import PREFIX

# pylint: disable=too-many-arguments


def assert_subscription_status(
    client: TestClient, expected_details: SubscriptionDetails
) -> None:
    """Assert that the subscription details are as expected."""
    result = client.get(
        PREFIX + "/subscription",
        params={"sub_id": str(expected_details.subscription_id)},
    )

    assert result.status_code == 200
    result_json = result.json()
    assert len(result_json) == 1
    res_details = SubscriptionDetails(**result_json[0])

    if expected_details != res_details:
        debug(res_details)
        debug(expected_details)

    assert expected_details == res_details, "{} != {}".format(
        expected_details, res_details
    )


def create_subscription(client: TestClient, subscription_id: UUID) -> Response:
    """Create a subscription record."""
    return client.post(
        PREFIX + "/subscription",
        json={"sub_id": str(subscription_id)},
    )


def create_subscription_detail(
    client: TestClient,
    token: str,
    subscription_id: UUID,
    state: SubscriptionState,
    role_assignments: Optional[Tuple[RoleAssignment, ...]] = (),
    display_name: str = "sub display name",
) -> Response:
    """Create a subscription detail record."""
    return client.post(
        "accounting/all-status",
        content=AllSubscriptionStatus(
            status_list=[
                SubscriptionStatus(
                    subscription_id=subscription_id,
                    display_name=display_name,
                    state=state,
                    role_assignments=role_assignments,
                )
            ]
        ).model_dump_json(),
        headers={"authorization": "Bearer " + token},
    )


def set_persistence(
    client: TestClient, subscription_id: UUID, always_on: bool
) -> Response:
    """Set the persistence of a subscription."""
    return client.post(
        PREFIX + "/persistent",
        json={"sub_id": str(subscription_id), "always_on": always_on},
    )


def create_approval(
    client: TestClient,
    subscription_id: UUID,
    ticket: str,
    amount: float,
    date_from: datetime.date,
    date_to: datetime.date,
    allocate: bool,
    currency: str = "GBP",
    force: bool = False,
) -> Response:
    """Create an approval for a subscription."""
    return client.post(
        PREFIX + "/approve",
        json={
            "sub_id": str(subscription_id),
            "ticket": ticket,
            "amount": amount,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "allocate": allocate,
            "currency": currency,
            "force": force,
        },
    )


def create_allocation(
    client: TestClient,
    subscription_id: UUID,
    ticket: str,
    amount: float,
) -> Response:
    """Create an allocation for a subscription."""
    return client.post(
        PREFIX + "/topup",
        json={"sub_id": str(subscription_id), "ticket": ticket, "amount": amount},
    )


def create_usage(
    client: TestClient,
    token: str,
    subscription_id: UUID,
    cost: float = 0.0,
    amortised_cost: float = 0.0,
    date: datetime.date = datetime.date.today(),
) -> Response:
    """Create a usage record for a subscription."""
    usage = Usage(
        id=str(uuid4()),
        name="test",
        type="",
        billing_account_id="666",
        billing_account_name="TestAccount",
        billing_period_start_date=date - datetime.timedelta(days=30),
        billing_period_end_date=date,
        billing_profile_id="",
        billing_profile_name="",
        account_owner_id="",
        account_name="",
        subscription_id=subscription_id,
        subscription_name="",
        date=date,
        product="",
        part_number="",
        meter_id="",
        quantity=1.0,
        effective_price=1.0,
        cost=cost,
        amortised_cost=amortised_cost,
        total_cost=cost + amortised_cost,
        unit_price=1.0,
        billing_currency="",
        resource_location="",
        consumed_service="",
        resource_id="",
        resource_name="",
        invoice_section="",
        offer_id="",
        is_azure_credit_eligible=True,
        publisher_type="",
        charge_type="",
        frequency="",
        monthly_upload=None,
    )

    post_data = AllUsage(usage_list=[usage], start_date=date, end_date=date)

    return client.post(
        "usage/all-usage",
        content=post_data.model_dump_json(),
        headers={"authorization": "Bearer " + token},
    )
