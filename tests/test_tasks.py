import logging
from uuid import UUID

import pytest

from rctab.settings import Settings, get_settings

# pylint: disable=unexpected-keyword-arg
# pylint: disable=use-implicit-booleaness-not-comparison


def test_settings() -> None:
    """Check testing is set to true. If not the tests will write to database"""
    assert get_settings().testing, "Set the TESTING env var to True"


def test_minimal_settings() -> None:
    """Check that we can make a new settings with the minimal required values."""
    settings = Settings(  # type: ignore
        db_user="my_db_user",
        db_password="my_db_password",
        db_host="my_db_host",
        # To stop any local .env files influencing the test
        _env_file=None,
    )

    # Check the defaults
    assert settings.db_port == 5432
    assert settings.db_name == ""
    assert settings.ssl_required is False
    assert settings.testing is True  # Tricky one to test
    assert settings.log_level == logging.getLevelName(logging.WARNING)
    assert settings.ignore_whitelist is False
    assert settings.whitelist == []
    assert settings.notifiable_roles == ["Contributor"]
    assert settings.roles_filter == ["Contributor"]
    assert settings.admin_email_recipients == []


def test_settings_raises() -> None:
    """Check that we raise an error if a PostgreSQL DSN is provided."""
    with pytest.raises(ValueError):
        Settings(  # type: ignore
            db_user="my_db_user",
            db_password="my_db_password",
            db_host="my_db_host",
            postgres_dsn="postgresql://user:password@0.0.0.0:6000/mypostgresdb",
            # To stop any local .env files influencing the test
            _env_file=None,
        )


def test_maximal_settings() -> None:
    """Check that we can make a new Settings with all known values."""
    settings = Settings(  # type: ignore
        db_user="my_db_user",
        db_password="my_db_password",
        db_host="my_db_host",
        db_port=5432,
        db_name="my_db_name",
        ssl_required=False,
        testing=False,
        sendgrid_api_key="sendgrid_key1234",
        sendgrid_sender_email="myemail@myorg.com",
        notifiable_roles=["Contributor", "Billing Reader"],
        roles_filter=["Owner", "Contributor"],
        log_level=logging.getLevelName(logging.INFO),
        ignore_whitelist=False,
        whitelist=[UUID(int=786)],
        usage_func_public_key="3456",
        status_func_public_key="2345",
        controller_func_public_key="1234",
        admin_email_recipients=["myemail@myorg.com"],
        # To stop any local .env files influencing the test
        _env_file=None,
    )

    assert (
        settings.postgres_dsn
        == "postgresql://my_db_user:my_db_password@my_db_host:5432/my_db_name"
    )
