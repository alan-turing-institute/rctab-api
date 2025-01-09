# import random
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, Generator
from uuid import UUID

import pytest
from databases import Database
from jinja2 import Environment, PackageLoader, StrictUndefined
from rctab_models.models import (
    Allocation,
    Approval,
    BillingStatus,
    Finance,
    RoleAssignment,
    SubscriptionState,
    SubscriptionStatus,
)

from rctab.constants import EMAIL_TYPE_SUB_WELCOME, EMAIL_TYPE_USAGE_ALERT
from rctab.crud import accounting_models
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.routes import get_subscriptions_summary
from tests.test_routes.constants import ADMIN_DICT, ADMIN_UUID
from tests.test_routes.test_routes import (  # pylint: disable=unused-import
    create_subscription,
    test_db,
)

# pylint: disable=redefined-outer-name
# pylint: disable=unexpected-keyword-arg


@pytest.fixture()
async def subscription_summary(
    test_db: Database,
) -> AsyncGenerator[Dict[str, Any], None]:
    subscription_id = await create_subscription(
        db=test_db,  # type: ignore
        current_state=SubscriptionState("Enabled"),
        allocated_amount=300,
        approved=(400, date.today()),
        spent=(148, 0),
    )

    sub_summary = await test_db.fetch_one(
        get_subscriptions_summary(sub_id=subscription_id, execute=False)
    )
    yield dict(sub_summary)  # type: ignore


@pytest.fixture()
def jinja2_environment() -> Generator[Environment, None, None]:
    yield Environment(
        loader=PackageLoader("rctab", "templates/emails"), undefined=StrictUndefined
    )


@pytest.mark.asyncio
async def test_welcome_emails_render(
    subscription_summary: Dict[str, Any],
    jinja2_environment: Environment,
) -> None:
    template_data = {
        "summary": subscription_summary,
        "rctab_url": None,
    }

    template_name = "welcome.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_welcome_emails_render_with_url(
    subscription_summary: Dict[str, Any],
    jinja2_environment: Environment,
) -> None:
    template_data = {"summary": subscription_summary, "rctab_url": "https://test"}

    template_name = "welcome.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    with open(
        "rctab/templates/emails/" + "rendered_with_url_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_status_emails_render(
    test_db: Database,
    subscription_summary: Dict[str, Any],
    jinja2_environment: Environment,
) -> None:
    """Render made up examples of status change and role assignment change emails."""
    subscription_id = subscription_summary["subscription_id"]

    old_role_assignments = (
        RoleAssignment(
            role_definition_id="123",
            role_name="Sous chef",
            principal_id="456",
            display_name="Max Mustermann",
            mail="max.mustermann@domain.com",
            scope="some/scope/string",
        ),
        RoleAssignment(
            role_definition_id="667",
            role_name="Animal trainer",
            principal_id="777",
            display_name="Tammy Lion",
            mail="tl@tl.com",
            scope="some/scope/string",
        ),
        RoleAssignment(
            role_definition_id="669",
            role_name="Acrobat",
            principal_id="778",
            display_name="Jack Donut",
            mail="jd@jd.com",
            scope="some/scope/string",
        ),
    )

    new_role_assignments = (
        RoleAssignment(
            role_definition_id="666",
            role_name="Circus director",
            principal_id="776",
            display_name="Tommy Thompson",
            mail="tt@tt.com",
            scope="some/scope/string",
        ),
        RoleAssignment(
            role_definition_id="667",
            role_name="Animal trainer",
            principal_id="777",
            display_name="Tammy Lion",
            mail="tl@tl.com",
            scope="some/scope/string",
        ),
        RoleAssignment(
            role_definition_id="668",
            role_name="Clown",
            principal_id="778",
            display_name="Jack Donut",
            mail="jd@jd.com",
            scope="some/scope/string",
        ),
    )

    old_status = SubscriptionStatus(
        subscription_id=subscription_id,
        display_name="old display name",
        state=SubscriptionState("Disabled"),
        role_assignments=old_role_assignments,
    )

    new_status = SubscriptionStatus(
        subscription_id=subscription_id,
        display_name=subscription_summary["name"],
        state=SubscriptionState("Enabled"),
        role_assignments=new_role_assignments,
    )

    status_kwargs = send_emails.prepare_subscription_status_email(
        test_db, new_status, old_status
    )

    status_template_data = status_kwargs["template_data"]
    status_template_data["summary"] = subscription_summary
    status_template_data["rctab_url"] = None
    status_template_name = "status_change.html"
    status_template = jinja2_environment.get_template(status_template_name)
    status_html = status_template.render(**status_template_data)
    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + status_template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(status_html)

    roles_kwargs = send_emails.prepare_roles_email(test_db, new_status, old_status)
    roles_template_data = roles_kwargs["template_data"]
    roles_template_data["summary"] = subscription_summary
    roles_template_data["rctab_url"] = None
    roles_template_name = "role_assignment_change.html"
    roles_template = jinja2_environment.get_template(roles_template_name)
    roles_html = roles_template.render(**roles_template_data)
    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + roles_template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(roles_html)


@pytest.mark.asyncio
async def test_allocation_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    jinja2_environment = Environment(
        loader=PackageLoader("rctab", "templates/emails"), undefined=StrictUndefined
    )

    subscription_id = subscription_summary["subscription_id"]

    template_data = Allocation(
        sub_id=subscription_id, ticket="C2022-999", amount=300
    ).model_dump()
    template_data["summary"] = subscription_summary
    template_data["rctab_url"] = None

    template_name = "new_allocation.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_approval_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    subscription_id = subscription_summary["subscription_id"]

    template_name = "new_approval.html"
    template_data = Approval(
        sub_id=subscription_id,
        amount=9000.01,
        ticket="Ticket C1",
        date_from=date.today(),
        date_to=date.today() + timedelta(days=20),
    ).model_dump()
    template_data["summary"] = dict(subscription_summary)  # type: ignore
    template_data["rctab_url"] = None
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_disabled_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    template_data = {
        "reason": BillingStatus("OVER_BUDGET_AND_EXPIRED").value,
        "summary": dict(subscription_summary),  # type: ignore
        "rctab_url": None,
    }

    template_name = "will_be_disabled.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_enabled_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    template_data = {"summary": subscription_summary, "rctab_url": None}  # type: ignore

    template_name = "will_be_enabled.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_expiry_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    template_data = {"days": 7, "summary": dict(subscription_summary), "rctab_url": None}  # type: ignore

    template_name = "expiry_looming.html"
    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_persistence_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    template_data = {
        "old_persistence": False,
        "new_persistence": True,
        "summary": dict(subscription_summary),
        "rctab_url": None,
    }

    template_name = "persistence_change.html"

    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_usage_emails_render(
    subscription_summary: Dict[str, Any], jinja2_environment: Environment
) -> None:
    template_data = {
        "percentage_used": 81,
        "summary": dict(subscription_summary),
        "rctab_url": None,
    }

    template_name = "usage_alert.html"

    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    # There must be a better way to do this...
    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


def test_render_finance_email(jinja2_environment: Environment) -> None:
    template_data = Finance(
        subscription_id=UUID(int=random.randint(0, (2**32) - 1)),
        ticket="test_ticket",
        amount=0.0,
        date_from=date(2022, 8, 1),
        date_to=date(2022, 8, 31),
        finance_code="test_finance",
        priority=1,
    ).model_dump()

    template_name = "new_finance.html"

    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


def test_abolishment_emails_render(jinja2_environment: Environment) -> None:
    template_data = {
        "abolishments": [
            {
                "subscription_id": UUID(int=100),
                "name": "my subscription",
                "allocation": 10,
                "approval": 10,
            },
        ]
    }

    template_name = "abolishment.html"

    template = jinja2_environment.get_template(template_name)

    html = template.render(**template_data)

    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)


@pytest.mark.asyncio
async def test_send_summary_email_render(test_db: Database) -> None:
    since_this_datetime = datetime.now(timezone.utc) - timedelta(days=1)
    # make a few subscriptions
    test_sub_1 = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Enabled"),
        allocated_amount=500.0,
        approved=(1000.0, date.today() + timedelta(days=10)),
    )
    test_sub_2 = await create_subscription(
        test_db,
        always_on=False,
        current_state=SubscriptionState("Disabled"),
        allocated_amount=50000.0,
        approved=(50000.0, date.today() + timedelta(days=10)),
    )
    # create new subscription with no subscription details since datetime
    # but approval for that time period
    test_sub_3 = UUID(int=random.randint(0, (2**32) - 1))
    test_sub_3 = UUID(int=random.randint(0, (2**32) - 1))
    test_sub_3 = UUID(int=random.randint(0, (2**32) - 1))
    await test_db.execute(
        accounting_models.subscription.insert().values(),
        dict(
            admin=str(ADMIN_UUID),
            subscription_id=str(test_sub_3),
            time_created=datetime.now(timezone.utc),
        ),
    )
    await test_db.execute(
        accounting_models.approvals.insert().values(),
        dict(
            subscription_id=str(test_sub_3),
            admin=str(ADMIN_UUID),
            currency="GBP",
            amount=76.85,
            date_from=datetime.now(timezone.utc) - timedelta(days=3),
            date_to=datetime.now(timezone.utc) + timedelta(days=30),
            time_created=datetime.now(timezone.utc) - timedelta(seconds=3),
        ),
    )

    # add role and status changes
    contributor = RoleAssignment(
        role_definition_id="some-role-def-id",
        role_name="Billing Reader",
        principal_id="some-principal-id",
        display_name="SomePrincipal Display Name",
    ).model_dump()

    await test_db.execute(
        accounting_models.subscription_details.insert().values(),
        dict(
            subscription_id=str(test_sub_3),
            state=SubscriptionState("Enabled"),
            display_name="a subscription",
            role_assignments=[
                contributor,
            ],
            time_created=datetime.now(timezone.utc) - timedelta(days=7),
        ),
    )

    await test_db.execute(
        accounting_models.subscription_details.insert().values(),
        dict(
            subscription_id=str(test_sub_1),
            state=SubscriptionState("Disabled"),
            display_name="test subscription 1",
            role_assignments=[
                contributor,
            ],
        ),
    )
    # notifications
    await test_db.execute(
        accounting_models.emails.insert().values(
            {
                "subscription_id": test_sub_2,
                "status": 200,
                "type": EMAIL_TYPE_SUB_WELCOME,
                "recipients": "me@my.org",
                "time_created": datetime.now(timezone.utc),
            }
        )
    )
    await test_db.execute(
        accounting_models.emails.insert().values(
            {
                "subscription_id": test_sub_2,
                "status": 200,
                "type": EMAIL_TYPE_USAGE_ALERT,
                "recipients": "me@my.org",
                "time_created": datetime.now(timezone.utc),
                "extra_info": str(95),
            }
        )
    )
    # finance entries
    await test_db.execute(
        accounting_models.finance.insert().values(),
        dict(
            subscription_id=test_sub_1,
            ticket="test_ticket",
            amount=1050.0,
            date_from=date.today(),
            date_to=date.today(),
            priority=100,
            finance_code="test_finance_code",
            time_created=datetime.now(timezone.utc) - timedelta(minutes=60),
            **ADMIN_DICT,
        ),
    )
    await test_db.execute(
        accounting_models.finance.insert().values(),
        dict(
            subscription_id=test_sub_1,
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
        accounting_models.finance.insert().values(),
        dict(
            subscription_id=test_sub_2,
            ticket="test_ticket",
            amount=250.0,
            date_from=date.today(),
            date_to=date.today(),
            priority=100,
            finance_code="test_finance_code",
            time_created=datetime.now(timezone.utc) - timedelta(minutes=60),
            **ADMIN_DICT,
        ),
    )

    # prepare and render summary email
    template_data = await send_emails.prepare_summary_email(
        test_db, since_this_datetime
    )
    template_name = "daily_summary.html"

    html = send_emails.render_template(template_name, template_data)

    with open(
        "rctab/templates/emails/" + "rendered_" + template_name,
        mode="w",
        encoding="utf-8",
    ) as output_file:
        output_file.write(html)

    # Test that we catch rendering error for incomplete template_data
    del template_data["new_approvals_and_allocations"][0]["details"]
    recipients = ["test@mail"]
    subject = "Daily summary"

    # We use send_with_sendgrid to since that's where we handle render exception
    status = send_emails.send_with_sendgrid(
        subject,
        template_name,
        template_data,
        recipients,
    )
    assert status == -999
