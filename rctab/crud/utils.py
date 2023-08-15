"""Database utilities and helper functions."""
from typing import List
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from rctab.constants import ADMIN_NAME, ADMIN_OID
from rctab.crud import accounting_models, models
from rctab.crud.models import database, executemany


async def insert_subscriptions_if_not_exists(subscriptions: List[UUID]) -> None:
    """Insert subscriptions if they don't already exist."""
    async with database.transaction():
        # Add RCTab-API to RBAC
        rbac_query = insert(models.user_rbac).on_conflict_do_nothing()
        await database.execute(
            rbac_query,
            {
                "oid": ADMIN_OID,
                "username": ADMIN_NAME,
                "has_access": True,
                "is_admin": False,
            },
        )

        subscription_query = insert(
            accounting_models.subscription
        ).on_conflict_do_nothing()

        values = [
            dict(subscription_id=i, admin=ADMIN_OID, abolished=False)
            for i in subscriptions
        ]

        await executemany(database, subscription_query, values=values)
