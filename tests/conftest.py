import asyncio
from typing import Any, AsyncGenerator, Callable, Dict, Generator
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from jose.jws import sign
from sqlalchemy.ext.asyncio.engine import AsyncConnection
from sqlalchemy.sql.expression import text

from rctab.crud.auth import (
    token_admin_verified,
    token_user_verified,
    token_verified,
    user_authenticated,
    user_authenticated_no_error,
)
from rctab.db import ENGINE, get_async_connection
from rctab.routers.accounting.desired_states import authenticate_app
from rctab.routers.accounting.status import authenticate_status_app
from rctab.routers.accounting.usage import authenticate_usage_app
from tests.test_routes import constants

# pylint: disable=W0621


@pytest.fixture(scope="function", autouse=True)
def clear_database_once() -> None:
    """Clear accounting tables once before the test session starts."""

    async def _clear() -> None:
        async with ENGINE.begin() as conn:
            await conn.execute(text("""
                    TRUNCATE TABLE
                        accounting.status,
                        accounting.usage,
                        accounting.costmanagement,
                        accounting.allocations,
                        accounting.approvals,
                        accounting.persistence,
                        accounting.emails,
                        accounting.cost_recovery,
                        accounting.finance,
                        accounting.finance_history,
                        accounting.subscription,
                        accounting.cost_recovery_log
                    RESTART IDENTITY CASCADE
                    """))

    asyncio.run(_clear())


@pytest_asyncio.fixture
async def auth_app_with_tx(auth_app: FastAPI) -> AsyncGenerator[FastAPI, None]:
    """Override DB dependency with one connection per test."""
    conn = await ENGINE.connect()

    async def _get_async_connection_override() -> AsyncGenerator[AsyncConnection, None]:
        yield conn

    auth_app.dependency_overrides[get_async_connection] = _get_async_connection_override
    try:
        yield auth_app
    finally:
        auth_app.dependency_overrides.pop(get_async_connection, None)
        await conn.close()


@pytest.fixture
def get_oauth_settings_override() -> Callable:
    """Fixture to replace user details"""

    def oauth_settings() -> Any:

        username = "test@domain.com"

        class MyUserClass(dict):
            """Dummy user class."""

            def __init__(self, token: dict[str, str], oid: UUID) -> None:
                super().__init__()
                self.token = token
                self.oid = oid

        class UserLogged:
            """Simple user detail for auth tests"""

            async def __call__(self, request: Request) -> Dict[str, str]:
                user_token = {
                    "access_token": sign(
                        {
                            "name": "dummy_username",
                            "unique_name": "dummy_username@dummyorg.com",
                        },
                        "secret",
                        algorithm="HS256",
                    )
                }
                user_oid = constants.USER_WITHOUT_ACCESS_UUID
                user = MyUserClass(user_token, user_oid)
                user["preferred_username"] = username
                return user

        return UserLogged()

    return oauth_settings


@pytest.fixture
def get_token_verified_override() -> Callable:
    def _token_verified() -> Any:
        class TokenVerifier:
            def __init__(
                self,
                oid: UUID,
                has_access: bool = True,
                is_admin: bool = True,
                auto_error: bool = True,
            ):
                self.auto_error = auto_error
                self.oid = oid
                self.has_access = has_access
                self.is_admin = is_admin

            async def __call__(self) -> Any:
                return TokenVerifier(oid=constants.ADMIN_UUID, auto_error=False)

        return TokenVerifier(oid=constants.ADMIN_UUID, auto_error=False)

    return _token_verified


@pytest.fixture
def auth_app(
    get_oauth_settings_override: Callable, get_token_verified_override: Callable
) -> Generator[FastAPI, None, None]:
    # pylint: disable=import-outside-toplevel
    from rctab import app

    async def bypass_app_token() -> Dict[str, str]:
        return {}

    # Override all authentication for tests
    app.dependency_overrides = {
        user_authenticated: get_oauth_settings_override(),
        user_authenticated_no_error: get_oauth_settings_override(),
        token_verified: get_token_verified_override(),
        token_user_verified: get_token_verified_override(),
        token_admin_verified: get_token_verified_override(),
        authenticate_status_app: bypass_app_token,
        authenticate_usage_app: bypass_app_token,
        authenticate_app: bypass_app_token,
    }
    yield app
    app.dependency_overrides = {}
