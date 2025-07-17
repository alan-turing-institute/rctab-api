"""SQLAlchemy models for the default schema."""

import sqlalchemy
from sqlalchemy.dialects.postgresql import UUID

metadata = sqlalchemy.MetaData()

user_cache = sqlalchemy.Table(
    "user_cache",
    metadata,
    sqlalchemy.Column("oid", UUID(as_uuid=True), primary_key=True),
    sqlalchemy.Column("cache", sqlalchemy.Text, nullable=False),
)

user_rbac = sqlalchemy.Table(
    "user_rbac",
    metadata,
    sqlalchemy.Column("oid", UUID, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("has_access", sqlalchemy.Boolean, nullable=False),
    sqlalchemy.Column("is_admin", sqlalchemy.Boolean, nullable=False),
)
