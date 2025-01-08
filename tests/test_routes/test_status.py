import datetime
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock
from uuid import UUID

import hypothesis
import pytest
import pytest_mock
from databases import Database
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from rctab_models.models import (
    AllSubscriptionStatus,
    Approval,
    RoleAssignment,
    SubscriptionState,
    SubscriptionStatus,
)
from sqlalchemy import select

from rctab.constants import ADMIN_OID
from rctab.crud.accounting_models import subscription_details
from rctab.routers.accounting import status
from rctab.routers.accounting.approvals import post_approval
from rctab.routers.accounting.routes import get_subscriptions_summary
from rctab.routers.accounting.status import post_status
from tests.test_routes import constants
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import


@settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.builds(SubscriptionStatus), min_size=2, max_size=20, unique=True))
def test_post_status(
    app_with_signed_status_token: Tuple[FastAPI, str],
    mocker: pytest_mock.MockerFixture,
    status_list: List[SubscriptionStatus],
) -> None:
    auth_app, token = app_with_signed_status_token

    with TestClient(auth_app) as client:
        all_status = AllSubscriptionStatus(status_list=status_list)

        mock_refresh = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.status.refresh_desired_states", mock_refresh
        )

        mock_send_email = AsyncMock()
        mocker.patch(
            "rctab.routers.accounting.send_emails.send_generic_email", mock_send_email
        )

        resp = client.post(
            "accounting/all-status",
            content=all_status.model_dump_json().encode("utf-8"),
            headers={"authorization": "Bearer " + token},
        )
        assert resp.status_code == 200

        # Posting the status data should have the side effect of
        # refreshing the desired states
        mock_refresh.assert_called_once_with(
            UUID(ADMIN_OID), [x.subscription_id for x in all_status.status_list]
        )

        # Check that we can POST the same status again without issue (idempotency).
        resp = client.post(
            "accounting/all-status",
            content=all_status.model_dump_json(),
            headers={"authorization": "Bearer " + token},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_post_status_sends_welcome(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: pytest_mock.MockerFixture,
) -> None:
    # pylint: disable=unexpected-keyword-arg, too-many-statements

    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    # These values should be the same as the defaults
    mock_get_settings.return_value.notifiable_roles = ["Contributor"]
    mock_get_settings.return_value.roles_filter = ["Contributor"]
    mock_get_settings.return_value.ticker = "t1"
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    mock_send_email = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )
    mock_send_email.return_value = 200

    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.status.refresh_desired_states", mock_refresh)

    new_detail = SubscriptionStatus(
        subscription_id=constants.TEST_SUB_UUID,
        display_name="old-name",
        state=SubscriptionState("Enabled"),
        # We need some assignments so there's
        # someone to send a welcome email to
        role_assignments=(
            RoleAssignment(
                role_definition_id="role99",
                role_name="Contributor",
                principal_id="principal1010",
                display_name="MyUser",
                mail="myuser@example.com",
                scope=f"/subscription_id/{constants.TEST_SUB_UUID}",
            ),
        ),
    )

    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )

    template_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"
    # The first status object should send a welcome email...
    assert mock_send_email.call_count == 1
    mock_send_email.assert_called_once_with(
        "You have a new subscription on the Azure platform: " + "old-name",
        "welcome.html",
        template_data,
        ["myuser@example.com"],
    )

    # ...and re-POSTing it shouldn't send one...
    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )
    assert mock_send_email.call_count == 1


@pytest.mark.asyncio
async def test_post_status_sends_status_change_name(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: pytest_mock.MockerFixture,
) -> None:
    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    # These values should be the same as the defaults
    mock_get_settings.return_value.notifiable_roles = ["Contributor"]
    mock_get_settings.return_value.roles_filter = ["Contributor"]
    mock_get_settings.return_value.ticker = "t1"
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    mock_send_email = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )
    mock_send_email.return_value = 200

    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.status.refresh_desired_states", mock_refresh)

    first_assignment = RoleAssignment(
        role_definition_id="role99",
        role_name="Contributor",
        principal_id="principal1010",
        display_name="MyUser",
        mail="myuser@example.com",
        scope=f"/subscription_id/{constants.TEST_SUB_UUID}",
    )

    new_detail = SubscriptionStatus(
        subscription_id=constants.TEST_SUB_UUID,
        display_name="old-name",
        state=SubscriptionState("Enabled"),
        # We need some assignments so there's
        # someone to send a welcome email to
        role_assignments=(first_assignment,),
    )
    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )

    status_change_detail = SubscriptionStatus(
        subscription_id=constants.TEST_SUB_UUID,
        display_name="new-name",
        state=SubscriptionState("Enabled"),
        role_assignments=(first_assignment,),
    )

    await post_status(
        AllSubscriptionStatus(status_list=[status_change_detail]),
        {"fake": "authentication"},
    )

    template_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["old_status"] = new_detail
    template_data["new_status"] = status_change_detail
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"

    # ...subsequent ones should send status update emails...
    assert mock_send_email.call_count == 2
    mock_send_email.assert_called_with(
        "There has been a status change for your Azure subscription: " + "new-name",
        "status_change.html",
        template_data,
        ["myuser@example.com"],
    )


@pytest.mark.asyncio
async def test_post_status_sends_status_change_roles(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: pytest_mock.MockerFixture,
) -> None:
    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    # These values should be the same as the defaults
    mock_get_settings.return_value.notifiable_roles = ["Contributor"]
    mock_get_settings.return_value.roles_filter = ["Contributor"]
    mock_get_settings.return_value.ticker = "t1"
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )

    mock_send_email = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )
    mock_send_email.return_value = 200

    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.status.refresh_desired_states", mock_refresh)

    first_assignment = RoleAssignment(
        role_definition_id="role99",
        role_name="Contributor",
        principal_id="principal1010",
        display_name="MyUser",
        mail="myuser@example.com",
        scope=f"/subscription_id/{constants.TEST_SUB_UUID}",
    )

    new_detail = SubscriptionStatus(
        subscription_id=constants.TEST_SUB_UUID,
        display_name="name",
        state=SubscriptionState("Enabled"),
        # We need some assignments so there's
        # someone to send a welcome email to
        role_assignments=(first_assignment,),
    )
    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )

    second_assignment = RoleAssignment(
        role_definition_id="role666",
        role_name="Contributor",
        principal_id="principal777",
        display_name="Leif Erikson",
        mail="leif@poee.org",
        scope=f"a/scope/string/{constants.TEST_SUB_UUID}",
    )
    # add a new role assignment
    await post_status(
        AllSubscriptionStatus(
            status_list=[
                SubscriptionStatus(
                    subscription_id=constants.TEST_SUB_UUID,
                    display_name="name",
                    state=SubscriptionState("Enabled"),
                    role_assignments=(first_assignment, second_assignment),
                )
            ]
        ),
        {"fake": "authentication"},
    )
    template_data: Dict[str, Any] = {}
    template_data = {
        "removed_from_rbac": [],
        "added_to_rbac": [
            {
                x: getattr(second_assignment, x)
                for x in ("role_name", "display_name", "mail")
            }
        ],
    }
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"
    assert mock_send_email.call_count == 2
    mock_send_email.assert_called_with(
        "The user roles have changed for your Azure subscription: " + "name",
        "role_assignment_change.html",
        template_data,
        ["myuser@example.com", "leif@poee.org"],
    )
    # remove one of the role assignements
    await post_status(
        AllSubscriptionStatus(
            status_list=[
                SubscriptionStatus(
                    subscription_id=constants.TEST_SUB_UUID,
                    display_name="name",
                    state=SubscriptionState("Enabled"),
                    role_assignments=(second_assignment,),
                )
            ]
        ),
        {"fake": "authentication"},
    )

    template_data = {
        "removed_from_rbac": [
            {
                x: getattr(first_assignment, x)
                for x in ("role_name", "display_name", "mail")
            }
        ],
        "added_to_rbac": [],
    }

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"

    assert mock_send_email.call_count == 3
    mock_send_email.assert_called_with(
        "The user roles have changed for your Azure subscription: " + "name",
        "role_assignment_change.html",
        template_data,
        ["leif@poee.org"],
    )


@pytest.mark.asyncio
async def test_post_status_sends_looming(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: pytest_mock.MockerFixture,
) -> None:
    # pylint: disable=unexpected-keyword-arg
    days_remaining = 10

    mock_get_settings = mocker.patch(
        "rctab.routers.accounting.send_emails.get_settings"
    )
    mock_get_settings.return_value.ignore_whitelist = True
    # These values should be the same as the defaults
    mock_get_settings.return_value.notifiable_roles = ["Contributor"]
    mock_get_settings.return_value.roles_filter = ["Contributor"]
    mock_get_settings.return_value.ticker = "t1"
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )
    mock_get_settings.return_value.expiry_email_freq = [1, 7, 30]

    mock_send_email = mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid"
    )
    mock_send_email.return_value = 200

    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.status.refresh_desired_states", mock_refresh)
    mocker.patch(
        "rctab.routers.accounting.approvals.refresh_desired_states", mock_refresh
    )

    # Post status to create the subscription
    new_detail = SubscriptionStatus(
        subscription_id=constants.TEST_SUB_UUID,
        display_name="name",
        state=SubscriptionState("Enabled"),
        # We need an assignment so there's
        # someone to send a welcome email to
        role_assignments=(
            RoleAssignment(
                role_definition_id="role99",
                role_name="Contributor",
                principal_id="principal1010",
                display_name="MyUser",
                mail="myuser@example.com",
                scope=f"/subscription_id/{constants.TEST_SUB_UUID}",
            ),
        ),
    )
    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )

    template_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"
    assert mock_send_email.call_count == 1
    welcome_call = mocker.call(
        "You have a new subscription on the Azure platform: " + "name",
        "welcome.html",
        template_data,
        ["myuser@example.com"],
    )

    # The first status call should have sent a welcome email
    mock_send_email.assert_has_calls([welcome_call])

    # So that we have an expiry date
    today = datetime.date.today()
    new_approval = Approval(
        sub_id=constants.TEST_SUB_UUID,
        ticket="N/A",
        amount=0,
        date_from=today,
        date_to=today + datetime.timedelta(days=days_remaining),
    )
    mock_user = mocker.MagicMock()
    mock_user.oid = ADMIN_OID
    await post_approval(new_approval, mock_user)

    assert mock_send_email.call_count == 2
    approval_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        approval_data["summary"] = dict(sub_summary)
    approval_data = {
        **new_approval.dict(),
        **approval_data,
        "rctab_url": "https://rctab-t1-teststack.azurewebsites.net/",
    }
    new_approval_call = mocker.call(
        "New approval for your Azure subscription: name",
        "new_approval.html",
        approval_data,
        ["myuser@example.com"],
    )

    # The approval call should have sent a new approval email
    mock_send_email.assert_has_calls([welcome_call, new_approval_call])

    # Post status again to catch the fact that there's now an expiry date
    await post_status(
        AllSubscriptionStatus(status_list=[new_detail]), {"fake": "authentication"}
    )

    expiry_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=new_detail.subscription_id, execute=False)
    )
    if sub_summary:
        expiry_data["summary"] = dict(sub_summary)
    expiry_data = {
        "days": days_remaining,
        "extra_info": str(days_remaining),
        **expiry_data,
        "rctab_url": "https://rctab-t1-teststack.azurewebsites.net/",
    }
    expiry_call = mocker.call(
        f"{days_remaining} days until the expiry of your Azure subscription: name",
        "expiry_looming.html",
        expiry_data,
        ["myuser@example.com"],
    )

    assert mock_send_email.call_count == 3
    mock_send_email.assert_has_calls([welcome_call, new_approval_call, expiry_call])


@pytest.mark.asyncio
async def test_post_status_filters_roles(
    test_db: Database,  # pylint: disable=redefined-outer-name
    mocker: pytest_mock.MockerFixture,
) -> None:
    # pylint: disable=unexpected-keyword-arg

    mock_send_email = mocker.Mock()
    mock_send_email.return_value = 200
    mocker.patch(
        "rctab.routers.accounting.send_emails.send_with_sendgrid", mock_send_email
    )

    mock_get_settings = mocker.Mock()
    mock_get_settings.return_value.roles_filter = ["IncludeRole"]
    mock_get_settings.return_value.notifiable_roles = ["IncludeRole"]
    mock_get_settings.return_value.ignore_whitelist = True
    mock_get_settings.return_value.website_hostname = (
        "https://rctab-t1-teststack.azurewebsites.net/"
    )
    mocker.patch("rctab.routers.accounting.status.get_settings", mock_get_settings)
    mocker.patch("rctab.routers.accounting.send_emails.get_settings", mock_get_settings)

    # We don't want to worry about which emails this function will send out
    mock_refresh = AsyncMock()
    mocker.patch("rctab.routers.accounting.status.refresh_desired_states", mock_refresh)

    sub_id = UUID(int=373758)
    old_status = SubscriptionStatus(
        subscription_id=sub_id,
        display_name="display_name",
        state=SubscriptionState("Enabled"),
        role_assignments=(
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="IncludeRole",
                principal_id="my-principal-id-1",
                display_name="MyPrincipal 1 Display Name",
                mail="principal1@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="ExcludeRole",
                principal_id="my-principal-id-2",
                display_name="MyPrincipal 2 Display Name",
                mail="principal2@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
        ),
    )
    await status.post_status(
        AllSubscriptionStatus(status_list=[SubscriptionStatus(**old_status.dict())]),
        {"fake": "authentication"},
    )

    template_data: Dict[str, Any] = {}
    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=old_status.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"
    assert mock_send_email.call_count == 1
    welcome_call = mocker.call(
        "You have a new subscription on the Azure platform: " + "display_name",
        "welcome.html",
        template_data,
        ["principal1@example.com"],
    )
    mock_send_email.assert_has_calls([welcome_call])

    # Shouldn't trigger an email but should be inserted
    newer_status = SubscriptionStatus(
        subscription_id=sub_id,
        display_name="display_name",
        state=SubscriptionState("Enabled"),
        role_assignments=(
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="IncludeRole",
                principal_id="my-principal-id-1",
                display_name="MyPrincipal 1 Display Name",
                mail="principal1@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="ExcludeRole",
                principal_id="my-principal-id-2",
                display_name="MyPrincipal 2 Display Name",
                mail="principle2@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
            # An extra role assignment has been added
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="ExcludeRole",
                principal_id="my-principal-id-3",
                display_name="MyPrincipal 3 Display Name",
                mail="principle3@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
        ),
    )

    await status.post_status(
        AllSubscriptionStatus(status_list=[SubscriptionStatus(**newer_status.dict())]),
        {"fake": "authentication"},
    )
    # No new emails expected
    mock_send_email.assert_has_calls([welcome_call])

    results = await test_db.fetch_all(select([subscription_details]))
    actual = [SubscriptionStatus(**dict(result)) for result in results]

    expected = [old_status, newer_status]
    assert expected == actual

    # Should trigger an email and be inserted
    newest_status = SubscriptionStatus(
        subscription_id=sub_id,
        display_name="display_name",
        state=SubscriptionState("Enabled"),
        role_assignments=(
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="IncludeRole",
                principal_id="my-principal-id-1",
                display_name="MyPrincipal 1 Display Name",
                mail="principle1@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
            # An extra role assignment has been added
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="IncludeRole",
                principal_id="my-principal-id-4",
                display_name="MyPrincipal 4 Display Name",
                mail="principle4@example.com",
                scope=f"/subscription_id/{sub_id}",
            ),
            RoleAssignment(
                role_definition_id="my-role-def-id-1",
                role_name="ExcludeRole",
                principal_id="my-principal-id-3",
                display_name="MyPrincipal 3 Display Name",
                scope=f"/subscription_id/{sub_id}",
            ),
        ),
    )

    await status.post_status(
        AllSubscriptionStatus(status_list=[SubscriptionStatus(**newest_status.dict())]),
        {"fake": "authentication"},
    )

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=newest_status.subscription_id, execute=False)
    )
    if sub_summary:
        template_data["summary"] = dict(sub_summary)
    template_data["removed_from_rbac"] = [
        {
            "role_name": "IncludeRole",
            "display_name": "MyPrincipal 1 Display Name",
            "mail": "principal1@example.com",
        },
        {
            "role_name": "ExcludeRole",
            "display_name": "MyPrincipal 2 Display Name",
            "mail": "principle2@example.com",
        },
        {
            "role_name": "ExcludeRole",
            "display_name": "MyPrincipal 3 Display Name",
            "mail": "principle3@example.com",
        },
    ]
    template_data["added_to_rbac"] = [
        {
            "role_name": "IncludeRole",
            "display_name": "MyPrincipal 1 Display Name",
            "mail": "principle1@example.com",
        },
        {
            "role_name": "IncludeRole",
            "display_name": "MyPrincipal 4 Display Name",
            "mail": "principle4@example.com",
        },
        {
            "role_name": "ExcludeRole",
            "display_name": "MyPrincipal 3 Display Name",
            "mail": None,
        },
    ]
    template_data["rctab_url"] = "https://rctab-t1-teststack.azurewebsites.net/"
    # New email expected
    mock_send_email.assert_called_with(
        "The user roles have changed for your Azure subscription: display_name",
        "role_assignment_change.html",
        template_data,
        ["principle1@example.com", "principle4@example.com"],
    )

    results = await test_db.fetch_all(
        select([subscription_details]).order_by(subscription_details.c.id)
    )
    actual = [SubscriptionStatus(**dict(result)) for result in results]

    expected = [old_status, newer_status, newest_status]
    assert expected == actual
