# pylint: disable=too-many-lines
import random
from datetime import date, datetime, timedelta, timezone
from typing import Generator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_mock
from asyncpg import Record
from databases import Database
from jinja2 import Environment, PackageLoader, StrictUndefined
from pytest_mock import MockerFixture
from sqlalchemy import insert, select
from sqlalchemy.sql import Select

from rctab.constants import (
    EMAIL_TYPE_SUB_APPROVAL,
    EMAIL_TYPE_SUB_WELCOME,
    EMAIL_TYPE_SUMMARY,
    EMAIL_TYPE_TIMEBASED,
    EMAIL_TYPE_USAGE_ALERT,
)
from rctab.crud import accounting_models
from rctab.crud.accounting_models import (
    allocations,
    approvals,
    emails,
    finance,
    refresh_materialised_view,
    subscription,
    subscription_details,
    usage,
    usage_view,
)
from rctab.crud.schema import AllUsage, RoleAssignment, SubscriptionState, Usage
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    UsageEmailContextManager,
    get_allocations_since,
    get_approvals_since,
    get_emails_sent_since,
    get_finance_entries_since,
    get_new_subscriptions_since,
    get_subscription_details_since,
    prepare_summary_email,
)
from rctab.routers.accounting.usage import post_usage
from tests.test_routes import constants
from tests.test_routes.constants import ADMIN_DICT
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import
from tests.test_routes.test_routes import create_subscription
from tests.utils import print_list_diff

USAGE_DICT = {
    "additional_properties": {},
    "name": str(UUID(int=random.randint(0, (2**32) - 1))),
    "type": "Usage type",
    "tags": None,
    "kind": "legacy",
    "billing_account_id": "01234567",
    "billing_account_name": "My billing account name",
    "billing_period_start_date": datetime(2021, 9, 1, 0, 0),
    "billing_period_end_date": datetime(2021, 9, 30, 0, 0),
    "billing_profile_id": "01234567",
    "billing_profile_name": "My institution",
    "account_owner_id": "account_owner@myinstitution",
    "account_name": "My account",
    "subscription_id": str(UUID(int=random.randint(0, (2**32) - 1))),
    "subscription_name": "My susbcription",
    "date": datetime(2021, 9, 1, 0, 0),
    "product": "Some Azure product",
    "part_number": "PART-NUM-1",
    "meter_id": str(UUID(int=random.randint(0, (2**32) - 1))),
    "meter_details": None,
    "quantity": 0.1,
    "effective_price": 0.0,
    "cost": 0.0,  # This is the important entry
    "total_cost": 0.0,
    "unit_price": 2.0,
    "billing_currency": "GBP",
    "resource_location": "Resource location",
    "consumed_service": "A service",
    "resource_id": "some-resource-id",
    "resource_name": "Resource name",
    "service_info1": None,
    "service_info2": None,
    "additional_info": None,
    "invoice_section": "Invoice section",
    "cost_center": None,
    "resource_group": None,
    "reservation_id": None,
    "reservation_name": None,
    "product_order_id": None,
    "product_order_name": None,
    "offer_id": "OFFER-ID",
    "is_azure_credit_eligible": True,
    "term": None,
    "publisher_name": None,
    "publisher_type": "Azure",
    "plan_name": None,
    "charge_type": "Usage",
    "frequency": "UsageBased",
}


@pytest.fixture()
def jinja2_environment() -> Generator[Environment, None, None]:
    yield Environment(
        loader=PackageLoader("rctab", "templates/emails"), undefined=StrictUndefined
    )


@pytest.mark.asyncio
async def test_usage_emails(
    mocker: pytest_mock.MockerFixture,
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Test that we send the right emails to the right Azure users."""

    thirty_percent = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(20.0, 0),
    )

    ninety_percent = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(80.0, 0),
    )

    ninety_five_percent = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(85.0, 0),
    )

    ninety_percent_usage = USAGE_DICT.copy()
    ninety_percent_usage["subscription_id"] = ninety_percent  # type: ignore
    ninety_percent_usage["cost"] = 10  # This should push us up to the 90% threshold
    ninety_percent_usage["total_cost"] = 10
    ninety_percent_usage["id"] = "a"

    thirty_percent_usage = USAGE_DICT.copy()
    thirty_percent_usage["subscription_id"] = thirty_percent  # type: ignore
    thirty_percent_usage["cost"] = 10  # This only gets us to 80%
    thirty_percent_usage["total_cost"] = 10
    thirty_percent_usage["id"] = "b"

    ninety_five_percent_usage = USAGE_DICT.copy()
    ninety_five_percent_usage["subscription_id"] = ninety_five_percent  # type: ignore
    ninety_five_percent_usage["cost"] = 10  # This takes us to 95%%
    ninety_five_percent_usage["total_cost"] = 10
    ninety_five_percent_usage["id"] = "c"

    post_data = AllUsage(
        usage_list=[
            Usage(**ninety_percent_usage),
            Usage(**thirty_percent_usage),
            Usage(**ninety_five_percent_usage),
        ]
    )

    mock_send = AsyncMock()
    mocker.patch("rctab.routers.accounting.send_emails.send_generic_email", mock_send)

    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.usage.refresh_desired_states", mock_refresh)

    resp = await post_usage(post_data, {"": ""})

    assert resp.status == "successfully uploaded 3 rows"

    # Posting the usage data should have the side effect of sending emails
    try:
        expected = [
            mocker.call(
                test_db,
                ninety_percent,
                "usage_alert.html",
                "90.0% of allocated budget used by your Azure subscription:",
                EMAIL_TYPE_USAGE_ALERT,
                {"percentage_used": 90.0, "extra_info": str(90.0)},
            ),
            mocker.call(
                test_db,
                ninety_five_percent,
                "usage_alert.html",
                "95.0% of allocated budget used by your Azure subscription:",
                EMAIL_TYPE_USAGE_ALERT,
                {"percentage_used": 95.0, "extra_info": str(95.0)},
            ),
        ]
        mock_send.assert_has_calls(expected)
    except AssertionError as e:
        print_list_diff(expected, mock_send.call_args_list)
        raise e


def test_send_with_sendgrid(mocker: MockerFixture) -> None:
    """Test the send_with_sendgrid function."""

    mail = mocker.patch("rctab.routers.accounting.send_emails.Mail")
    client_class = mocker.patch(
        "rctab.routers.accounting.send_emails.SendGridAPIClient"
    )
    get_settings = mocker.patch("rctab.routers.accounting.send_emails.get_settings")
    get_settings.return_value.sendgrid_api_key = "sendgridkey123"
    get_settings.return_value.sendgrid_sender_email = "myemail@myorg"
    get_settings.return_value.testing = False  # Bypass the safety feature

    mock_sg_client = mocker.Mock()
    mock_sg_client.send.return_value = mocker.Mock(status_code=11)
    client_class.return_value = mock_sg_client

    status_code = send_emails.send_with_sendgrid(
        "my-subject",
        "blank.html",
        {},
        ["rse1@myorg", "rse2@myorg"],
    )
    mail.assert_called_once_with(
        from_email="myemail@myorg",
        to_emails=["rse1@myorg", "rse2@myorg"],
        html_content="<!-- This is used for unit tests -->",
        subject="my-subject",
    )
    mock_sg_client.send.assert_called_once_with(mail.return_value)
    assert status_code == 11


def test_no_sendgrid_api_key(mocker: MockerFixture) -> None:
    """We shouldn't try to send emails if we're missing an API key or sender email."""

    mocker.patch("rctab.routers.accounting.send_emails.Mail")
    client_class = mocker.patch(
        "rctab.routers.accounting.send_emails.SendGridAPIClient"
    )
    get_settings = mocker.patch("rctab.routers.accounting.send_emails.get_settings")
    get_settings.return_value.testing = False  # Bypass the safety feature

    mock_sg_client = mocker.Mock()
    mock_sg_client.send.return_value = mocker.Mock(status_code=11)
    client_class.return_value = mock_sg_client

    get_settings.return_value.sendgrid_api_key = None
    get_settings.return_value.sendgrid_sender_email = "me@myco.com"

    with pytest.raises(MissingEmailParamsError):
        send_emails.send_with_sendgrid(
            "my-subject",
            "blank.html",
            {},
            ["rse1@myorg", "rse2@myorg"],
        )

    get_settings.return_value.sendgrid_api_key = "sendgrid_key_1234"
    get_settings.return_value.sendgrid_sender_email = None

    with pytest.raises(MissingEmailParamsError):
        send_emails.send_with_sendgrid(
            "my-subject",
            "blank.html",
            {},
            ["rse1@myorg", "rse2@myorg"],
        )


@pytest.mark.asyncio
async def test_get_sub_email_recipients(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: MockerFixture,
) -> None:
    subscription_id = UUID(int=random.randint(0, (2**32) - 1))

    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(subscription_id),
        ),
    )

    # In case it is called before the status function app has run
    rbac_list = await send_emails.get_sub_email_recipients(test_db, subscription_id)
    assert rbac_list == []

    billing_reader = RoleAssignment(
        mail="johndoe@myorg",
        scope=f"/subscriptions/{subscription_id}",
        role_name="Billing Reader",
        display_name="John Doe",
        principal_id="1",
        role_definition_id="some_role_def_id",
    ).dict()
    contributor_a = RoleAssignment(
        mail="janedoe@myorg",
        scope=f"/subscriptions/{subscription_id}",
        role_name="Contributor",
        display_name="Jane Doe",
        principal_id="2",
        role_definition_id="some_other_role_def_id",
    ).dict()
    group_contributor = RoleAssignment(
        mail=None,
        scope=f"/subscriptions/{subscription_id}",
        role_name="Contributor",
        display_name="The_Does",
        principal_id="3",
        role_definition_id="some_other_role_def_id",
    ).dict()
    reader = RoleAssignment(
        mail="jimdoe@myorg",
        scope=f"/subscriptions/{subscription_id}",
        role_name="Reader",
        display_name="Jim Doe",
        principal_id="4",
        role_definition_id="some_other_role_def_id",
    ).dict()
    contributor_b = RoleAssignment(
        mail="joedoe@myorg",
        scope="/",
        role_name="Contributor",
        display_name="Joe Doe",
        principal_id="5",
        role_definition_id="some_other_role_def_id",
    ).dict()

    mock_get_settings = mocker.Mock()
    mock_get_settings.return_value.notifiable_roles = ["Reader", "Contributor"]
    mocker.patch("rctab.routers.accounting.send_emails.get_settings", mock_get_settings)

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=str(subscription_id),
            state=SubscriptionState("Enabled"),
            display_name="a subscription",
            role_assignments=[
                billing_reader,
                contributor_a,
                group_contributor,
                reader,
                contributor_b,
            ],
        ),
    )
    rbac_list = await send_emails.get_sub_email_recipients(test_db, subscription_id)
    assert rbac_list == ["janedoe@myorg", "jimdoe@myorg"]


@pytest.mark.asyncio
async def test_send_generic_emails(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    approved_to = date.today() + timedelta(days=10)
    subscription_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, approved_to),
        spent=(0.0, 0.0),
    )

    mock_sendgrid = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )

    mock_get_recipients = AsyncMock()
    mock_get_recipients.return_value = ["user1@myorg"]
    mocker.patch(
        "rctab.routers.accounting.send_emails.get_sub_email_recipients",
        mock_get_recipients,
    )

    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    mock_get_settings.return_value.stack = "teststack"
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    await send_emails.send_generic_email(
        test_db,
        subscription_id,
        "new_approval.html",
        "New approval for your Azure subscription:",
        EMAIL_TYPE_SUB_APPROVAL,
        {"approval_amount": 1010},
    )
    mock_sendgrid.assert_called_once_with(
        "New approval for your Azure subscription: a subscription",
        "new_approval.html",
        {
            "approval_amount": 1010,
            "summary": {
                "subscription_id": subscription_id,
                "abolished": False,
                "name": "a subscription",
                "role_assignments": [
                    {
                        "display_name": "SomePrincipal Display " "Name",
                        "mail": None,
                        "principal_id": "some-principal-id",
                        "role_definition_id": "some-role-def-id",
                        "role_name": "Billing Reader",
                        "scope": None,
                    },
                ],
                "status": "Enabled",
                "approved_from": date.today() - timedelta(days=365),
                "approved_to": approved_to,
                "approved": 100.0,
                "allocated": 100.0,
                "cost": 0.0,
                "amortised_cost": 0.0,
                "total_cost": 0.0,
                "first_usage": date.today(),
                "latest_usage": date.today(),
                "always_on": False,
                "desired_status": None,
                "desired_status_info": None,
            },
            "rctab_url": "https://rctab-t1-teststack.azurewebsites.net/",
        },
        mock_get_recipients.return_value,
    )

    email_query = select([accounting_models.emails]).where(
        accounting_models.emails.c.type == EMAIL_TYPE_SUB_APPROVAL
    )
    email_results = await test_db.fetch_all(email_query)
    email_list = [tuple(x) for x in email_results]
    assert len(email_list) == 1


@pytest.mark.asyncio
async def test_send_generic_emails_no_name(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Test that we can handle subscriptions without names."""

    approved_to = date.today() + timedelta(days=10)
    subscription_id = await create_subscription(
        test_db,
        always_on=False,
        current_state=None,  # no state = no name
        allocated_amount=100.0,
        approved=(100.0, approved_to),
        spent=(0.0, 0.0),
    )

    mock_sendgrid = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )

    mock_get_recipients = AsyncMock()
    mock_get_recipients.return_value = ["user1@myorg"]
    mocker.patch(
        "rctab.routers.accounting.send_emails.get_sub_email_recipients",
        mock_get_recipients,
    )

    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    await send_emails.send_generic_email(
        test_db,
        subscription_id,
        "new_approval.html",
        "New approval for your Azure subscription:",
        EMAIL_TYPE_SUB_APPROVAL,
        {},
    )

    mock_sendgrid.assert_called_once_with(
        f"New approval for your Azure subscription: {subscription_id}",
        "new_approval.html",
        {
            "summary": {
                "subscription_id": subscription_id,
                "abolished": False,
                "name": None,
                "role_assignments": None,
                "status": None,
                "approved_from": date.today() - timedelta(days=365),
                "approved_to": approved_to,
                "approved": 100.0,
                "allocated": 100.0,
                "cost": 0.0,
                "amortised_cost": 0.0,
                "total_cost": 0.0,
                "first_usage": date.today(),
                "latest_usage": date.today(),
                "always_on": False,
                "desired_status": None,
                "desired_status_info": None,
            },
            "rctab_url": "https://rctab-t1-teststack.azurewebsites.net/",
        },
        mock_get_recipients.return_value,
    )


@pytest.mark.asyncio
async def test_send_generic_emails_no_recipients(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    subscription_id = UUID(int=55)

    mock_sendgrid = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )

    mock_get_recipients = AsyncMock()
    mock_get_recipients.return_value = []
    mocker.patch(
        "rctab.routers.accounting.send_emails.get_sub_email_recipients",
        mock_get_recipients,
    )

    # Add the subscription to the database, but add no role assignments.
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(subscription_id),
        ),
    )
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=str(subscription_id),
            state=SubscriptionState("Enabled"),
            display_name="a subscription",
            role_assignments=[],
        ),
    )

    # This call should do nothing because the subscription is not on the whitelist.
    await send_emails.send_generic_email(
        test_db,
        subscription_id,
        "new_approval.html",
        "has a new approval",
        EMAIL_TYPE_SUB_APPROVAL,
        {"approval_amount": 1010},
    )
    mock_sendgrid.assert_not_called()

    # Disable the email whitelist, and try again. This time there should be a fallback
    # email to admin email.
    get_settings = mocker.patch("rctab.routers.accounting.send_emails.get_settings")
    get_settings.return_value.ignore_whitelist = True
    get_settings.return_value.admin_email_recipients = ["admin@mail"]
    get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    await send_emails.send_generic_email(
        test_db,
        subscription_id,
        "new_approval.html",
        "New approval for your Azure subscription:",
        EMAIL_TYPE_SUB_APPROVAL,
        {"approval_amount": 1010},
    )
    mock_sendgrid.assert_called_once_with(
        (
            "RCTab undeliverable: "
            "New approval for your Azure subscription: "
            "a subscription"
        ),
        "new_approval.html",
        {
            "approval_amount": 1010,
            "summary": {
                "subscription_id": subscription_id,
                "abolished": False,
                "name": "a subscription",
                "role_assignments": [],
                "status": "Enabled",
                "approved_from": None,
                "approved_to": None,
                "approved": 0.0,
                "allocated": 0.0,
                "cost": 0.0,
                "amortised_cost": 0.0,
                "total_cost": 0.0,
                "first_usage": None,
                "latest_usage": None,
                "always_on": None,
                "desired_status": None,
                "desired_status_info": None,
            },
            "rctab_url": "https://rctab-t1-teststack.azurewebsites.net/",
        },
        ["admin@mail"],
    )


@pytest.mark.asyncio
async def test_check_subs_nearing_expiry(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    one_day = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=1)),
        spent=(70.0, 0),
    )

    thirty_days = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=30)),
        spent=(70.0, 0),
    )

    # forty days
    await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=40)),
        spent=(70.0, 0),
    )

    mock_expiry_looming = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_expiry_looming_emails",
        mock_expiry_looming,
    )

    await send_emails.check_for_subs_nearing_expiry(test_db)

    mock_expiry_looming.assert_called_once_with(
        test_db,
        [
            (
                one_day,
                date.today() + timedelta(days=1),
                SubscriptionState.ENABLED.value,
            ),
            (
                thirty_days,
                date.today() + timedelta(days=30),
                SubscriptionState.ENABLED.value,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_check_for_overbudget_subs(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    sub_1 = await create_subscription(
        test_db,
        always_on=True,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(170.0, 0),
    )

    await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(90.0, 0),
    )

    await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.DISABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(100.0, 0),
    )

    await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState.DISABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(170.0, 0),
    )

    mock_overbudget = AsyncMock()
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_overbudget_emails", mock_overbudget
    )

    await send_emails.check_for_overbudget_subs(test_db)

    mock_overbudget.assert_called_once_with(
        test_db,
        [
            (sub_1, 170.0),
        ],
    )


@pytest.mark.asyncio
async def test_get_most_recent_emails(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we can get the most recent email for a subscription."""

    async def fetch_one_or_fail(query: Select) -> Record:
        row = await test_db.fetch_one(query)
        if not row:
            raise RuntimeError("No row returned")
        return row

    seven_days = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=7)),
        spent=(70.0, 0),
    )
    the_sub = await fetch_one_or_fail(select([accounting_models.subscription]))
    sub_time = the_sub["time_created"]

    insert_statement = insert(accounting_models.emails)
    await test_db.execute(
        insert_statement.values(
            {
                "subscription_id": seven_days,
                "status": 200,
                "type": EMAIL_TYPE_TIMEBASED,
                "recipients": "me@my.org",
                "time_created": sub_time + timedelta(days=1),
            }
        )
    )
    await test_db.execute(
        insert_statement.values(
            {
                "subscription_id": seven_days,
                "status": 200,
                "type": EMAIL_TYPE_TIMEBASED,
                "recipients": "me@my.org",
                "time_created": sub_time + timedelta(days=2),
            }
        )
    )
    await test_db.execute(
        insert_statement.values(
            {
                "subscription_id": seven_days,
                "status": 200,
                "type": "budget-based",
                "recipients": "me@my.org",
            }
        )
    )

    email_query = send_emails.sub_time_based_emails()
    rows = await test_db.fetch_all(email_query)
    assert len(rows) == 1
    assert rows[0]["subscription_id"] == seven_days
    assert rows[0]["time_created"] == sub_time + timedelta(days=2)


@pytest.mark.asyncio
async def test_send_expiry_looming_emails(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    seven_days = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=7)),
        spent=(70.0, 0),
    )

    mock_send = mocker.patch("rctab.routers.accounting.send_emails.send_generic_email")

    await send_emails.send_expiry_looming_emails(
        test_db,
        [
            (
                seven_days,
                date.today() + timedelta(days=7),
                SubscriptionState.ENABLED,
            )
        ],
    )

    mock_send.assert_called_once_with(
        test_db,
        seven_days,
        "expiry_looming.html",
        "7 days until the expiry of your Azure subscription:",
        EMAIL_TYPE_TIMEBASED,
        {"days": (timedelta(days=7)).days, "extra_info": str((timedelta(days=7)).days)},
    )


@pytest.mark.asyncio
async def test_send_overbudget_emails(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    sub_1 = await create_subscription(
        test_db,
        always_on=True,
        current_state=SubscriptionState.ENABLED,
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=10)),
        spent=(170.0, 0),
    )

    mock_send = mocker.patch("rctab.routers.accounting.send_emails.send_with_sendgrid")
    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )

    mock_get_settings.return_value.ignore_whitelist = True
    mock_get_settings.return_value.admin_email_recipients = ["admin@mail"]

    async def send_over_budget() -> None:
        await send_emails.send_overbudget_emails(
            test_db,
            [
                (
                    sub_1,
                    170.0,
                )
            ],
        )

    await send_over_budget()

    assert len(mock_send.call_args_list) == 1
    assert (
        mock_send.call_args_list[0].args[0]
        == "RCTab undeliverable: 170.0% of allocated budget used by your Azure subscription: a subscription"
    )
    assert mock_send.call_args_list[0].args[1] == "usage_alert.html"
    assert mock_send.call_args_list[0].args[2]["percentage_used"] == 170.0
    assert mock_send.call_args_list[0].args[3] == ["admin@mail"]

    await send_over_budget()
    assert len(mock_send.call_args_list) == 1


@pytest.mark.asyncio
async def test_expiry_looming_doesnt_resend(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """Check that we take no action if not necessary."""

    seven_days = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=100.0,
        approved=(100.0, date.today() + timedelta(days=7)),
        spent=(70.0, 0),
    )

    insert_statement = insert(accounting_models.emails)
    await test_db.execute(
        insert_statement.values(
            {
                "subscription_id": seven_days,
                "status": 200,
                "type": EMAIL_TYPE_TIMEBASED,
                "recipients": "me@my.org",
            }
        )
    )

    mock_send = mocker.patch("rctab.routers.accounting.send_emails.send_with_sendgrid")

    await send_emails.send_expiry_looming_emails(
        test_db,
        [
            (
                seven_days,
                date.today() + timedelta(days=7),
                SubscriptionState.DISABLED,
            )
        ],
    )

    mock_send.assert_not_called()


def test_should_send_expiry_email(mocker: MockerFixture) -> None:
    # pylint: disable=using-constant-test
    # pylint: disable=invalid-name

    # If the expiry is a long way away, we don't want to send an email
    date_of_expiry = date.today() + timedelta(days=31)
    date_of_last_email = None
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is False
    )

    # If we have already sent an email during this period,
    # i.e. between 30 and 7 days before expiry,
    # we should not send an email
    date_of_expiry = date.today() + timedelta(days=30)
    date_of_last_email = date.today()
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is False
    )

    # If we haven't already sent an email, we should send one...
    date_of_expiry = date.today() + timedelta(days=30)
    date_of_last_email = None
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )

    # ...unless the subscription is disabled already for some other reason.
    date_of_expiry = date.today() + timedelta(days=30)
    date_of_last_email = None
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.DISABLED
        )
        is False
    )

    # After the 30-day email, we want a reminder at 7 days
    date_of_expiry = date.today() + timedelta(days=7)
    date_of_last_email = date.today() - timedelta(days=1)
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )

    # After the 7-day email, we also want a reminder at 1 day
    date_of_expiry = date.today() + timedelta(days=1)
    date_of_last_email = date.today() - timedelta(days=1)
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )

    # If the subscription has already expired, we should not send an email
    # because other emails will alert the owners...
    date_of_expiry = date.today() - timedelta(days=1)
    date_of_last_email = None
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.DISABLED
        )
        is False
    )

    # ...unless this is an "always on" subscription, in which case they should
    # be emailed daily because they ought to put in an approval request...
    date_of_expiry = date.today() - timedelta(days=1)
    date_of_last_email = date.today() - timedelta(days=1)
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )

    # ...which should also hold if there is no previous email...
    date_of_expiry = date.today() - timedelta(days=1)
    date_of_last_email = None
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )

    # ...but they should only receive one email per day...
    date_of_expiry = date.today() - timedelta(days=1)
    date_of_last_email = date.today()
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is False
    )

    # ...and none on the day of expiry
    date_of_expiry = date.today()
    date_of_last_email = date.today() - timedelta(days=1)
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is False
    )

    # If we have sent an email, but it is now out of date
    # e.g. as a result of a new approval,
    # we should send an email
    date_of_expiry = date.today() + timedelta(days=30)
    date_of_last_email = date.today() - timedelta(days=1)
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is True
    )
    # Try again but having changed the settings
    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.expiry_email_freq = []
    assert (
        send_emails.should_send_expiry_email(
            date_of_expiry, date_of_last_email, SubscriptionState.ENABLED
        )
        is False
    )

    if False:
        # Visualise!
        table = []
        for x in range(32):
            row = []
            for y in range(32):
                date_of_expiry = date.today() + timedelta(days=x)
                date_of_last_email = date.today() - timedelta(days=y)
                row.append(
                    send_emails.should_send_expiry_email(
                        date_of_expiry, date_of_last_email, SubscriptionState.DISABLED
                    )
                )
            table.append(row)

        print("\n")
        for row in table:
            string = ["True " if x else "False" for x in row]
            print(string)


@pytest.mark.asyncio
async def test_usage_email_context_manager(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    subscription_ids = []
    # These should be 20 below each threshold
    starting_usages = (30, 55, 70, 75)
    for starting_usage in starting_usages:
        subscription_ids.append(
            await create_subscription(
                test_db,
                always_on=False,
                current_state=SubscriptionState("Enabled"),
                allocated_amount=100.0,
                approved=(100.0, date.today() + timedelta(days=7)),
                spent=(starting_usage, 0),
            )
        )

    mock_send = AsyncMock()
    mocker.patch("rctab.routers.accounting.send_emails.send_generic_email", mock_send)

    async with UsageEmailContextManager(test_db):
        for subscription_id in subscription_ids:
            await test_db.execute(
                usage.insert().values(),
                dict(
                    subscription_id=str(subscription_id),
                    id=str(UUID(int=random.randint(0, 2**32 - 1))),
                    total_cost=21.0,  # To put us over the next highest threshold
                    invoice_section="",
                    date=date.today(),
                ),
            )
            await refresh_materialised_view(test_db, usage_view)

        expected = [
            mocker.call(
                test_db,
                subscription_id,
                "usage_alert.html",
                str(starting_usage + 20.0)
                + "% of allocated budget "
                + "used by your Azure subscription:",
                EMAIL_TYPE_USAGE_ALERT,
                {
                    "percentage_used": starting_usage + 20.0,
                    "extra_info": str(starting_usage + 20.0),
                },
            )
            for subscription_id, starting_usage in zip(
                subscription_ids, starting_usages
            )
        ]
    try:
        mock_send.assert_has_calls(expected)
    except AssertionError as e:
        print_list_diff(expected, mock_send.call_args_list)
        raise e


@pytest.mark.asyncio
async def test_catches_params_missing(
    test_db: Database, mocker: MockerFixture  # pylint: disable=redefined-outer-name
) -> None:
    """If the key email params are missing, we should log instead."""

    mock_logger = mocker.patch("rctab.routers.accounting.send_emails.logger")

    get_settings = mocker.patch("rctab.routers.accounting.send_emails.get_settings")
    get_settings.return_value.ignore_whitelist = True

    get_sub_email_recipients = mocker.patch(
        "rctab.routers.accounting.send_emails.get_sub_email_recipients"
    )
    get_sub_email_recipients.return_value = ["user1@mail.com", "user2@mail.com"]

    mock_send = mocker.patch("rctab.routers.accounting.send_emails.send_with_sendgrid")
    mock_send.side_effect = MissingEmailParamsError(
        subject="TestMissingEmail",
        recipients=["user1@mail.com", "user2@mail.com"],
        from_email="",
        message="test-message",
    )

    test_subscription_id = UUID(int=786)

    # add subscriptions to database
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(test_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )

    # add row to database
    await send_emails.send_generic_email(
        test_db,
        test_subscription_id,
        "test-template-name",
        "test-subject-prefix",
        "test-email-type",
        {},
    )

    # check the last row added is as expected
    last_row_query = select([accounting_models.failed_emails]).order_by(
        accounting_models.failed_emails.c.id.desc()
    )
    last_row_result = await test_db.fetch_one(last_row_query)
    assert last_row_result is not None
    last_row = {x: last_row_result[x] for x in last_row_result}

    # check log message for row added
    mock_logger.error.assert_called_with(
        "'%s' email failed to send to subscription '%s' due to missing "
        "api_key or send email address.\n"
        "It has been logged in the 'failed_emails' table with id=%s.\n"
        "Use 'get_failed_emails.py' to retrieve it to send manually.",
        "test-email-type",
        test_subscription_id,
        last_row["id"],
    )

    # check last row in database contains the MissingEmailParamsError params
    assert len(last_row) == 9
    assert last_row["subscription_id"] == test_subscription_id
    assert last_row["type"] == "test-email-type"
    assert last_row["subject"] == "TestMissingEmail"
    assert last_row["from_email"] == ""
    assert last_row["recipients"] == "user1@mail.com;user2@mail.com"
    assert last_row["time_updated"] is None
    assert last_row["message"] == "test-message"


@pytest.mark.asyncio
async def test_get_new_subscriptions_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    todays_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    yesterdays_subscription_id = UUID(int=random.randint(0, (2**32) - 1))

    new_subscriptions = await get_new_subscriptions_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert not new_subscriptions

    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(yesterdays_subscription_id),
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
        ),
    )

    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(todays_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )

    new_subscriptions = await get_new_subscriptions_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert new_subscriptions[0]["subscription_id"] == todays_subscription_id
    assert len(new_subscriptions) == 1


@pytest.mark.asyncio
async def test_get_status_changes_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(test_subscription_id),
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
        ),
    )

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            display_name="my test subscription",
            state="Enabled",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=5),
        ),
    )

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            display_name="my test subscription",
            state="Disabled",
        ),
    )

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            display_name="my test subscription",
            state="Enabled",
        ),
    )
    status_changes = await get_subscription_details_since(
        test_db, test_subscription_id, datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert status_changes and len(status_changes) == 2
    assert status_changes[0]["id"] <= status_changes[1]["id"]
    assert status_changes[0]["state"] == "Disabled"
    assert status_changes[1]["state"] == "Enabled"


@pytest.mark.asyncio
async def test_get_emails_sent_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    another_test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))

    # add subscriptions and details to db
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(test_subscription_id),
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
        ),
    )
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(another_test_subscription_id),
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
        ),
    )
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            display_name="my test subscription",
            state="Enabled",
        ),
    )
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=another_test_subscription_id,
            display_name="i love testing",
            state="Enabled",
        ),
    )
    # add entries to email table
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            status=200,  # sendgrid return code
            type=EMAIL_TYPE_SUB_WELCOME,
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=1),
        ),
    )

    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            status=200,  # sendgrid return code
            type=EMAIL_TYPE_SUMMARY,
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=1),
        ),
    )
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(another_test_subscription_id),
            status=200,  # sendgrid return code
            type=EMAIL_TYPE_USAGE_ALERT,
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=120),
            extra_info="75.0",
        ),
    )
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(another_test_subscription_id),
            status=200,  # sendgrid return code
            type=EMAIL_TYPE_SUB_APPROVAL,
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=500),
        ),
    )
    # no emails sent for queried time perios
    emails_sent = await get_emails_sent_since(test_db, datetime.now(timezone.utc))
    assert not emails_sent

    # we only have emails sent within last 10 seconds for one subscription id
    emails_sent = await get_emails_sent_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=10)
    )
    assert len(emails_sent) == 1
    assert emails_sent[0]["name"] == "my test subscription"
    assert emails_sent[0]["subscription_id"] == test_subscription_id
    assert len(emails_sent[0]["emails_sent"]) == 1

    # we have emails sent within last 200 seconds for two subscription ids
    emails_sent = await get_emails_sent_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=200)
    )
    emails_another_test_sub = list(
        filter(
            lambda l: l["subscription_id"] == another_test_subscription_id, emails_sent
        )
    )
    assert emails_another_test_sub[0]["emails_sent"][0]["extra_info"] == "75.0"

    # we have emails sent within last 600 seconds for two subscription ids
    emails_sent = await get_emails_sent_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=600)
    )
    assert len(emails_sent) == 2
    assert emails_sent[0]["subscription_id"] in [
        test_subscription_id,
        another_test_subscription_id,
    ]
    assert emails_sent[1]["subscription_id"] in [
        test_subscription_id,
        another_test_subscription_id,
    ]
    emails_test_sub = list(
        filter(lambda l: l["subscription_id"] == test_subscription_id, emails_sent)
    )
    assert len(emails_test_sub[0]["emails_sent"]) == 1
    emails_another_test_sub = list(
        filter(
            lambda l: l["subscription_id"] == another_test_subscription_id, emails_sent
        )
    )
    assert len(emails_another_test_sub[0]["emails_sent"]) == 2


@pytest.mark.asyncio
async def test_get_finance_entries_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    test_subscription_id = await create_subscription(
        test_db, current_state=SubscriptionState("Enabled")
    )
    another_test_subscription_id = await create_subscription(
        test_db, current_state=SubscriptionState("Enabled")
    )
    # insert entries to finance table
    await test_db.execute(
        finance.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            ticket="test_ticket",
            amount=-50.0,
            date_from=date.today(),
            date_to=date.today(),
            priority=100,
            finance_code="test_finance_code",
            time_created=datetime.now(timezone.utc) - timedelta(minutes=60),
            **ADMIN_DICT,
        ),
    )

    await test_db.execute(
        finance.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            ticket="test_ticket",
            amount=3000.0,
            date_from=date.today(),
            date_to=date.today(),
            priority=100,
            finance_code="test_finance_code",
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
            **ADMIN_DICT,
        ),
    )

    # no entries for time since
    entries = await get_finance_entries_since(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=10)
    )
    assert not entries

    # entries for one subscription
    entries = await get_finance_entries_since(
        test_db, datetime.now(timezone.utc) - timedelta(days=2)
    )
    assert len(entries) == 1
    assert len(entries[0]["finance_entry"]) == 2
    assert sum(x["amount"] for x in entries[0]["finance_entry"]) == 2950.0

    # add an entry for another subscription
    await test_db.execute(
        finance.insert().values(),
        dict(
            subscription_id=another_test_subscription_id,
            ticket="another_test_ticket",
            amount=900.0,
            date_from=date.today(),
            date_to=date.today(),
            priority=100,
            finance_code="another_test_finance_code",
            time_created=datetime.now(timezone.utc) - timedelta(days=1),
            **ADMIN_DICT,
        ),
    )

    entries = await get_finance_entries_since(
        test_db, datetime.now(timezone.utc) - timedelta(days=1.5)
    )
    assert len(entries) == 2
    assert entries[0]["subscription_id"] in [
        test_subscription_id,
        another_test_subscription_id,
    ]
    assert entries[1]["subscription_id"] in [
        test_subscription_id,
        another_test_subscription_id,
    ]


@pytest.mark.asyncio
async def test_prepare_summary_email(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    another_test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    yet_another_test_subscription_id = UUID(int=random.randint(0, (2**32) - 1))
    # add subscriptions to database
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(test_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(another_test_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )
    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(yet_another_test_subscription_id),
            time_created=datetime.now(timezone.utc),
        ),
    )
    # add details for created test subscriptions
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=test_subscription_id,
            display_name="my test subscription",
            state="Enabled",
        ),
    )

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=another_test_subscription_id,
            display_name="my other test subscription",
            state="Enabled",
        ),
    )
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=yet_another_test_subscription_id,
            display_name="my latest test subscription",
            state="Enabled",
        ),
    )

    summary_data = await prepare_summary_email(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=5)
    )

    assert len(summary_data["new_subscriptions"]) == 3  # number of new subscriptions
    assert sorted([x["name"] for x in summary_data["new_subscriptions"]]) == sorted(
        [
            "my test subscription",
            "my other test subscription",
            "my latest test subscription",
        ]
    )

    #  for testing status changes
    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=yet_another_test_subscription_id,
            display_name="my latest test subscription",
            state="Disabled",
        ),
    )

    summary_data = await prepare_summary_email(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=5)
    )

    assert len(summary_data["status_changes"]) == 1
    assert summary_data["status_changes"][0]["old_status"]["state"] == "Enabled"
    assert summary_data["status_changes"][0]["new_status"]["state"] == "Disabled"

    await test_db.execute(
        subscription_details.insert().values(),
        dict(
            subscription_id=another_test_subscription_id,
            display_name="my latest test subscription",
            state="Enabled",
        ),
    )

    summary_data = await prepare_summary_email(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    assert len(summary_data["status_changes"]) == 2
    changes_another_test = [
        x
        for x in summary_data["status_changes"]
        if x["new_status"].get("subscription_id") == another_test_subscription_id
    ]

    assert (
        changes_another_test[0]["old_status"]["display_name"]
        == "my other test subscription"
    )
    assert (
        changes_another_test[0]["new_status"]["display_name"]
        == "my latest test subscription"
    )

    # add some test data to approvals and allocations table
    await test_db.execute(
        approvals.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=100.0,
            date_from=datetime.now(timezone.utc) - timedelta(days=3),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc) - timedelta(seconds=3),
        ),
    )
    await test_db.execute(
        approvals.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=50.0,
            date_from=datetime.now(timezone.utc) - timedelta(days=3),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc),
        ),
    )

    await test_db.execute(
        allocations.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=80.0,
            time_created=datetime.now(timezone.utc),
        ),
    )

    summary_data = await prepare_summary_email(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    assert len(summary_data["new_approvals_and_allocations"][0]["approvals"]) == 2
    assert sum(summary_data["new_approvals_and_allocations"][0]["approvals"]) == 150
    assert (
        summary_data["new_approvals_and_allocations"][0]["details"]["name"]
        == "my test subscription"
    )
    assert sum(summary_data["new_approvals_and_allocations"][0]["allocations"]) == 80

    # add some test data to emails table
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            status=1,
            type=EMAIL_TYPE_SUMMARY,
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=1),
        ),
    )
    await test_db.execute(
        emails.insert().values(),
        dict(
            subscription_id=str(test_subscription_id),
            status=1,
            type="welcome",
            recipients="Some happy email recipient",
            time_created=datetime.now(timezone.utc) - timedelta(seconds=1),
        ),
    )

    summary_data = await prepare_summary_email(
        test_db, datetime.now(timezone.utc) - timedelta(seconds=5)
    )

    assert len(summary_data["notifications_sent"]) == 1
    assert summary_data["notifications_sent"][0]["emails_sent"][0]["type"] == "welcome"


@pytest.mark.asyncio
async def test_get_allocations_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    time_since_last_summary_email = datetime.now(timezone.utc) - timedelta(days=1)
    # make new subscription
    test_subscription = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
    )
    another_test_subscription = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
    )

    # insert allocation information predating last summary email
    await test_db.execute(
        allocations.insert().values(),
        dict(
            subscription_id=str(test_subscription),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=100.0,
            time_created=datetime.now(timezone.utc) - timedelta(days=3),
        ),
    )

    # no allocation data found
    allocations_data = await get_allocations_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert not allocations_data

    # insert allocation
    await test_db.execute(
        allocations.insert().values(),
        dict(
            subscription_id=str(test_subscription),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=200.0,
            time_created=datetime.now(timezone.utc) - timedelta(minutes=300),
        ),
    )
    # one allocation found
    allocations_data = await get_allocations_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(allocations_data) == 1
    assert sum(allocations_data) == 200

    # insert negative allocation
    await test_db.execute(
        allocations.insert().values(),
        dict(
            subscription_id=str(test_subscription),
            admin=str(constants.ADMIN_UUID),
            amount=-50.0,
            currency="GBP",
            time_created=datetime.now(timezone.utc) - timedelta(minutes=240),
        ),
    )
    allocations_data = await get_allocations_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(allocations_data) == 2
    assert sum(allocations_data) == 150

    # insert allocation for other subscription
    await test_db.execute(
        allocations.insert().values(),
        dict(
            subscription_id=str(another_test_subscription),
            admin=str(constants.ADMIN_UUID),
            amount=-50.0,
            currency="GBP",
            time_created=datetime.now(timezone.utc) - timedelta(minutes=240),
        ),
    )
    allocations_data = await get_allocations_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(allocations_data) == 2
    assert sum(allocations_data) == 150


@pytest.mark.asyncio
async def test_get_approvals_since(
    test_db: Database,  # pylint: disable=redefined-outer-name
) -> None:
    time_since_last_summary_email = datetime.now(timezone.utc) - timedelta(days=1)
    test_subscription = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
    )
    another_test_subscription = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
    )

    # insert approval information predating last summary email
    await test_db.execute(
        approvals.insert().values(),
        dict(
            subscription_id=str(test_subscription),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=100.0,
            date_from=datetime.now(timezone.utc) - timedelta(days=3),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc) - timedelta(days=3),
        ),
    )
    approvals_data = await get_approvals_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(approvals_data) == 0

    # add a more recent approval
    await test_db.execute(
        approvals.insert().values(),
        dict(
            subscription_id=str(test_subscription),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=200.0,
            date_from=datetime.now(timezone.utc) - timedelta(minutes=60),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc) - timedelta(minutes=60),
        ),
    )
    approvals_data = await get_approvals_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(approvals_data) == 1
    assert sum(approvals_data) == 200

    # and another approval BUT for a different subscription
    await test_db.execute(
        approvals.insert().values(),
        dict(
            subscription_id=str(another_test_subscription),
            admin=str(constants.ADMIN_UUID),
            currency="GBP",
            amount=500.0,
            date_from=datetime.now(timezone.utc) - timedelta(minutes=60),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc) - timedelta(minutes=60),
        ),
    )
    approvals_data = await get_approvals_since(
        test_db, test_subscription, time_since_last_summary_email
    )
    assert len(approvals_data) == 1
    assert sum(approvals_data) == 200
