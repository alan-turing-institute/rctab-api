import datetime
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Tuple
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from jose.jws import sign

from rctab.crud.auth import (
    token_admin_verified,
    token_user_verified,
    token_verified,
    user_authenticated,
    user_authenticated_no_error,
)
from rctab.settings import Settings
from tests.test_routes import constants


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


# pylint: disable=W0621
@pytest.fixture
def auth_app(
    get_oauth_settings_override: Callable, get_token_verified_override: Callable
) -> FastAPI:

    # pylint: disable=import-outside-toplevel
    from rctab import app

    # Override all authentication for tests
    app.dependency_overrides = {}
    app.dependency_overrides[user_authenticated] = get_oauth_settings_override()
    app.dependency_overrides[user_authenticated_no_error] = (
        get_oauth_settings_override()
    )
    app.dependency_overrides[token_verified] = get_token_verified_override()
    app.dependency_overrides[token_user_verified] = get_token_verified_override()
    app.dependency_overrides[token_admin_verified] = get_token_verified_override()

    return app


def get_public_key_and_token(app_name: str) -> Tuple[str, str]:
    """Sign a JWT with private key and mock get_settings with public key field"""
    token_claims: Dict[str, Any] = {"sub": app_name}
    access_token_expires = datetime.timedelta(minutes=10)

    expire = datetime.datetime.now(datetime.UTC) + access_token_expires
    token_claims.update({"exp": expire})

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key()
    public_key_str = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("utf-8")

    token = jwt.encode(token_claims, private_key, algorithm="RS256")  # type: ignore
    return public_key_str, token


# pylint: disable=redefined-outer-name
@pytest.fixture
def app_with_signed_billing_token(
    tmp_path: Path,
    mocker: Any,
    get_oauth_settings_override: Callable,
    get_token_verified_override: Callable,
) -> Tuple[FastAPI, str]:
    """Sign a JWT with private key and mock get_settings with public key field"""
    private_key = tmp_path / "key"
    public_key = tmp_path / "key.pub"

    # Create a public and private_key
    _ = subprocess.check_output(
        ["ssh-keygen", "-t", "rsa", "-f", private_key, "-N", ""],
        universal_newlines=True,
    )

    assert private_key.exists()
    assert public_key.exists()

    private_key_text = private_key.read_text()
    private_key_bytes = serialization.load_ssh_private_key(  # type: ignore
        private_key_text.encode(), password=b""
    )

    # Create jwt
    token_claims: Dict[str, Any] = {"sub": "usage-app"}
    access_token_expires = datetime.timedelta(minutes=10)

    expire = datetime.datetime.now(datetime.UTC) + access_token_expires
    token_claims.update({"exp": expire})

    token = jwt.encode(token_claims, private_key_bytes, algorithm="RS256")  # type: ignore

    def _get_settings() -> Settings:
        return Settings(
            usage_func_public_key=str(public_key.read_text()), ignore_whitelist=True
        )

    mocker.patch(
        "rctab.routers.accounting.usage.get_settings", side_effect=_get_settings
    )
    # pylint: disable=import-outside-toplevel
    from rctab import app

    # Override all authentication for tests
    app.dependency_overrides = {}
    app.dependency_overrides[user_authenticated] = get_oauth_settings_override()
    app.dependency_overrides[token_verified] = get_token_verified_override()
    app.dependency_overrides[token_user_verified] = get_token_verified_override()
    app.dependency_overrides[token_admin_verified] = get_token_verified_override()

    return app, token


@pytest.fixture
def app_with_signed_status_and_controller_tokens(
    mocker: Any,
    get_oauth_settings_override: Callable,
    get_token_verified_override: Callable,
) -> Tuple[FastAPI, str, str]:

    status_public_key_str, status_token = get_public_key_and_token("status-app")
    controller_public_key_str, controller_token = get_public_key_and_token(
        "controller-app"
    )

    def _get_settings() -> Settings:
        return Settings(
            controller_func_public_key=controller_public_key_str,
            status_func_public_key=status_public_key_str,
            ignore_whitelist=True,
        )

    mocker.patch(
        "rctab.routers.accounting.status.get_settings", side_effect=_get_settings
    )
    mocker.patch(
        "rctab.routers.accounting.desired_states.get_settings",
        side_effect=_get_settings,
    )

    # pylint: disable=import-outside-toplevel
    from rctab import app

    # Override all authentication for tests
    app.dependency_overrides = {}
    app.dependency_overrides[user_authenticated] = get_oauth_settings_override()
    app.dependency_overrides[token_verified] = get_token_verified_override()
    app.dependency_overrides[token_user_verified] = get_token_verified_override()
    app.dependency_overrides[token_admin_verified] = get_token_verified_override()

    return app, status_token, controller_token


@pytest.fixture
def app_with_signed_status_token(
    mocker: Any,
    get_oauth_settings_override: Callable,
    get_token_verified_override: Callable,
) -> Tuple[FastAPI, str]:

    status_public_key_str, status_token = get_public_key_and_token("status-app")

    def _get_settings() -> Settings:
        return Settings(
            status_func_public_key=status_public_key_str, ignore_whitelist=True
        )

    mocker.patch(
        "rctab.routers.accounting.status.get_settings", side_effect=_get_settings
    )

    # pylint: disable=import-outside-toplevel
    from rctab import app

    # Override all authentication for tests
    app.dependency_overrides = {
        user_authenticated: get_oauth_settings_override(),
        token_verified: get_token_verified_override(),
        token_user_verified: get_token_verified_override(),
        token_admin_verified: get_token_verified_override(),
    }

    return app, status_token
