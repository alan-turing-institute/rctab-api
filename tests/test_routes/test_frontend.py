import random
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from pytest_mock import MockerFixture
from rctab_models.models import RoleAssignment, SubscriptionState, UserRBAC
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud.accounting_models import subscription, subscription_details
from rctab.db import ENGINE
from rctab.routers.frontend import check_user_on_subscription, home
from rctab.routers.frontend import subscription_details as subscription_details_page
from tests.test_routes import constants
from tests.test_routes.test_routes import test_db  # pylint: disable=unused-import

# pylint: disable=redefined-outer-name


@pytest.mark.asyncio
async def test_no_email_raises(mocker: MockerFixture) -> None:
    """We want to be explicit if this ever happens because we think it shouldn't."""

    mock_request = mocker.Mock()

    mock_user = mocker.Mock()
    # We expect the token to always have a valid email as the unique_name
    mock_user.token = {
        "access_token": jwt.encode({"unique_name": None, "name": "My Name"}, "my key")
    }
    async with ENGINE.connect() as conn:

        with pytest.raises(HTTPException):
            await home(mock_request, mock_user, conn=conn)


@pytest.mark.asyncio
async def test_no_username_no_subscriptions(
    mocker: MockerFixture, test_db: AsyncConnection
) -> None:
    """Check that users without usernames can't see any subscriptions."""

    subscription_id = UUID(int=random.randint(0, (2**32) - 1))

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
            role_assignments=[
                RoleAssignment(
                    role_definition_id="123",
                    role_name="Sous chef",
                    principal_id="456",
                    display_name="Max Mustermann",
                    # Note the missing email address, which does sometimes happen
                    mail=None,
                    scope="some/scope/string",
                ).model_dump()
            ],
        ),
    )

    mock_request = mocker.Mock()

    mock_user = mocker.Mock()
    mock_user.token = {
        "access_token": jwt.encode(
            {"unique_name": "me@my.org", "name": "My Name"}, "my key"
        )
    }
    mock_user.oid = str(UUID(int=434))

    mock_templates = mocker.patch("rctab.routers.frontend.templates")

    mock_check_access = AsyncMock()
    mock_check_access.return_value = UserRBAC(
        oid=UUID(int=111), has_access=True, is_admin=False
    )
    mocker.patch("rctab.routers.frontend.check_user_access", mock_check_access)

    await home(mock_request, mock_user)

    # Check that no subscriptions are passed to the template
    assert (
        mock_templates.TemplateResponse.call_args.kwargs["context"]["azure_sub_data"]
        == []
    )


@pytest.mark.asyncio
async def test_check_user_on_subscription(
    test_db: AsyncConnection,  # pylint: disable=redefined-outer-name
) -> None:
    subscription_id = UUID(int=1)

    await test_db.execute(
        subscription.insert().values(),
        dict(
            admin=str(constants.ADMIN_UUID),
            subscription_id=str(subscription_id),
        ),
    )

    # Since there is no subscription_detail row,
    # there won't be any role assignments
    user_on_subscription = await check_user_on_subscription(
        subscription_id, username=""
    )

    assert user_on_subscription is False


@pytest.mark.asyncio
async def test_render_home_page(
    mocker: MockerFixture, test_db: AsyncConnection
) -> None:
    """Check that we can pick up on undefined variable template issues."""

    # Use StrictUndefined while testing
    mocker.patch(
        "rctab.routers.frontend.templates",
        Jinja2Templates(
            env=Environment(
                loader=PackageLoader("rctab"),
                autoescape=select_autoescape(),
                undefined=StrictUndefined,
            )
        ),
    )
    subscription_id = UUID(int=random.randint(0, (2**32) - 1))

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
            role_assignments=[
                RoleAssignment(
                    role_definition_id="123",
                    role_name="Sous chef",
                    principal_id="456",
                    display_name="Max Mustermann",
                    # Note the missing email address, which does sometimes happen
                    mail=None,
                    scope="some/scope/string",
                ).model_dump()
            ],
        ),
    )

    mock_request = mocker.Mock()

    mock_user = mocker.Mock()
    mock_user.token = {
        "access_token": jwt.encode(
            {"unique_name": "me@my.org", "name": "My Name"}, "my key"
        )
    }
    mock_user.oid = str(UUID(int=434))

    mock_check_access = AsyncMock()
    mock_check_access.return_value = UserRBAC(
        oid=UUID(int=111), has_access=True, is_admin=False
    )
    mocker.patch("rctab.routers.frontend.check_user_access", mock_check_access)

    await home(mock_request, mock_user)


@pytest.mark.asyncio
async def test_render_details_page(
    mocker: MockerFixture, test_db: AsyncConnection
) -> None:
    """Check that we can pick up on undefined variable template issues."""
    # Use StrictUndefined while testing
    mocker.patch(
        "rctab.routers.frontend.templates",
        Jinja2Templates(
            env=Environment(
                loader=PackageLoader("rctab"),
                autoescape=select_autoescape(),
                undefined=StrictUndefined,
            )
        ),
    )
    subscription_id = UUID(int=random.randint(0, (2**32) - 1))

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
            role_assignments=[
                RoleAssignment(
                    role_definition_id="123",
                    role_name="Sous chef",
                    principal_id="456",
                    display_name="Max Mustermann",
                    # Note the missing email address, which does sometimes happen
                    mail=None,
                    scope="some/scope/string",
                ).model_dump()
            ],
        ),
    )

    mock_request = mocker.Mock()

    mock_user = mocker.Mock()
    mock_user.token = {
        "access_token": jwt.encode(
            {"unique_name": "me@my.org", "name": "My Name"}, "my key"
        )
    }
    mock_user.oid = str(UUID(int=434))

    mock_check_access = AsyncMock()
    mock_check_access.return_value = UserRBAC(
        oid=UUID(int=111), has_access=True, is_admin=True
    )
    mocker.patch("rctab.routers.frontend.check_user_access", mock_check_access)

    await subscription_details_page(subscription_id, mock_request, mock_user)
