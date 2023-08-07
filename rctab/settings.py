"""Global App Configuration"""
from functools import lru_cache
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseSettings, PostgresDsn, validator


class Settings(BaseSettings):
    # Connection parameters for a PostgreSQL database to store
    # subscription data, user account info, sent emails, etc. See also
    # https://www.postgresql.org/docs/11/libpq-connect.html#LIBPQ-PARAMKEYWORDS
    db_host: str  # e.g. "mydb.postgres.database.azure.com" or "0.0.0.0"
    db_port: int = 5432
    db_user: str  # e.g. "postgres" or "rctab-user"
    db_password: str
    db_name: str = ""  # e.g. RCTab or empty for the user's default db
    ssl_required: bool = False  # Usually False for local and True for Azure DBs

    # Email settings
    sendgrid_api_key: Optional[str]  # An API key with which to send emails
    sendgrid_sender_email: Optional[str]  # The "from:" address for sent emails
    notifiable_roles: List[str] = ["Contributor"]  # Roles to email about a subscription
    roles_filter: List[str] = ["Contributor"]  # Send emails if one of these changes
    admin_email_recipients: List[str] = []  # Recipients of admin emails

    # Org name, for emails and frontend
    organisation: Optional[str] = "My organisation"

    # Current server hostname, for emails (automatically set by Azure)
    website_hostname: Optional[str]

    # Gradual rollout settings
    ignore_whitelist: bool = False  # By default, only manage whitelist subscriptions
    whitelist: List[UUID] = []  # e.g. WHITELIST='["01-23-45-67-89"]'

    # See validate_log_level()
    log_level: str = "WARNING"

    # To copy log messages to a central app insights
    central_logging_connection_string: Optional[str]

    # Whether we are running unit tests
    testing: bool = False  # A True value rolls back all commits between tests

    # Public keys for function apps
    usage_func_public_key: Optional[str]
    status_func_public_key: Optional[str]
    controller_func_public_key: Optional[str]

    # postgres_dsn is calculated so do not provide it explicitly
    postgres_dsn: Optional[PostgresDsn]

    @validator("postgres_dsn", pre=True)
    def validate_postgres_dsn(cls, _: Optional[PostgresDsn], values: Any) -> str:
        """Build a DSN string from the host, db name, port, username and password."""

        # We want to build the Data Source Name ourselves so none should be provided
        if _:
            raise ValueError("postgres_dsn should not be provided")

        user = values["db_user"]
        password = values["db_password"]
        host = values["db_host"]
        port = values["db_port"]
        db_name = values["db_name"]

        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

        if values["ssl_required"]:
            return dsn + "?sslmode=require"

        return dsn

    @validator("log_level")
    def validate_log_level(cls, log_level: str) -> str:
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cache Settings as they should not change after startup."""
    return Settings()
