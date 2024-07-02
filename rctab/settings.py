"""Global app configuration."""

from functools import lru_cache
from typing import Any, List, Optional
from uuid import UUID

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global app settings."""

    # Connection parameters for a PostgreSQL database to store
    # subscription data, user account info, sent emails, etc. See also
    # https://www.postgresql.org/docs/11/libpq-connect.html#LIBPQ-PARAMKEYWORDS
    db_host: str  # e.g. "mydb.postgres.database.azure.com" or "0.0.0.0"
    db_port: int = 5432
    db_user: str  # e.g. "postgres" or "rctab-user"
    db_password: str
    db_name: Optional[str] = None  # e.g. RCTab or empty for the user's default db
    ssl_required: bool = False  # Usually False for local and True for Azure DBs

    # Email settings
    sendgrid_api_key: Optional[str] = None  # An API key with which to send emails
    sendgrid_sender_email: Optional[str] = None  # The "from:" address for sent emails
    notifiable_roles: List[str] = ["Contributor"]  # Roles to email about a subscription
    roles_filter: List[str] = ["Contributor"]  # Send emails if one of these changes
    admin_email_recipients: List[str] = []  # Recipients of admin emails
    expiry_email_freq: List[int] = [1, 7, 30]  # Days before expiry to send emails

    # Org name, for emails and frontend
    organisation: Optional[str] = "My organisation"

    # Current server hostname, for emails (automatically set by Azure)
    website_hostname: Optional[str] = None

    # Gradual rollout settings
    ignore_whitelist: bool = False  # By default, only manage whitelist subscriptions
    whitelist: List[UUID] = []  # e.g. WHITELIST='["01-23-45-67-89"]'

    # See validate_log_level()
    log_level: str = "WARNING"

    # To copy log messages to a central app insights
    central_logging_connection_string: Optional[str] = None

    # Whether we are running unit tests
    testing: bool = False  # A True value rolls back all commits between tests

    # Public keys for function apps
    usage_func_public_key: Optional[str] = None
    status_func_public_key: Optional[str] = None
    controller_func_public_key: Optional[str] = None

    # postgres_dsn is calculated so do not provide it explicitly
    postgres_dsn: Optional[PostgresDsn] = None

    # Settings for the settings class itself.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Note that mode="before" means that we get (and return)
    # a dict and not a Settings object.
    @model_validator(mode="before")
    def validate_postgres_dsn(  # type: ignore
        self: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a DSN string from the host, db name, port, username and password."""
        # We want to build the Data Source Name ourselves so none should be provided
        if self.get("postgres_dsn") is not None:
            raise ValueError("postgres_dsn should not be provided")

        self["postgres_dsn"] = (
            f'postgresql://{self["db_user"]}:{self["db_password"]}@{self["db_host"]}:{self["db_port"]}/{self.get("db_name", "")}'
        )

        if self.get("ssl_required"):
            self["postgres_dsn"] += "?sslmode=require"

        return self

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, log_level: str) -> str:
        """Check that the log level has a valid value."""
        # See https://docs.python.org/3/library/logging.html#logging-levels
        allowed_levels = (
            "CRITICAL",
            "FATAL",
            "ERROR",
            "WARNING",
            "WARN",
            "INFO",
            "DEBUG",
            "NOTSET",
        )
        if log_level not in allowed_levels:
            raise ValueError(f"{log_level} not in {allowed_levels}")
        return log_level


@lru_cache()
def get_settings() -> Settings:
    """Cache Settings as they should not change after startup."""
    return Settings()
