"""Database utilities and helper functions."""

from typing import List
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from rctab.constants import ADMIN_NAME, ADMIN_OID
from rctab.crud import accounting_models, models
from rctab.db import AsyncConnection


async def insert_subscriptions_if_not_exists(
    subscriptions: List[UUID], conn: AsyncConnection
) -> None:
    """Insert subscriptions if they don't already exist."""
    rbac_query = insert(models.user_rbac).on_conflict_do_nothing()
    await conn.execute(
        rbac_query,
        {
            "oid": ADMIN_OID,
            "username": ADMIN_NAME,
            "has_access": True,
            "is_admin": False,
        },
    )

    values = [
        dict(subscription_id=i, admin=ADMIN_OID, abolished=False) for i in subscriptions
    ]

    subscription_query = (
        insert(accounting_models.subscription).values(values).on_conflict_do_nothing()
    )

    await conn.execute(subscription_query)
