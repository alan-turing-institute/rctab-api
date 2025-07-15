"""Create and fetch subscriptions."""

from typing import Any, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException

# from psycopg2 import IntegrityError
from rctab_models.models import SubscriptionDetails, UserRBAC
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.db import AsyncConnection, get_async_connection
from rctab.routers.accounting.routes import (
    SubscriptionItem,
    get_subscriptions_with_disable,
    router,
)


async def create_subscription(
    conn: AsyncConnection, subscription: SubscriptionItem, user: UserRBAC
) -> None:
    """Add an Azure subscription to the database."""
    await conn.execute(
        insert(accounting_models.subscription),
        {
            "admin": user.oid,
            "subscription_id": subscription.sub_id,
            "abolished": False,
        },
    )


@router.get("/subscription", response_model=List[SubscriptionDetails])
async def get_subscription(
    sub_id: Optional[UUID] = None,
    _: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> List[SubscriptionDetails]:
    """Whether a subscription with the specified uuid is registered."""
    rows = [dict(x) for x in await get_subscriptions_with_disable(conn, sub_id)]
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Subscription {sub_id} not found",
        )
    result = [SubscriptionDetails(**x) for x in rows]

    return result


@router.post("/subscription")
async def post_subscription(
    subscription: SubscriptionItem,
    user: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> Any:
    """Create a new subscription."""
    try:
        await create_subscription(conn, subscription, user)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Subscription {subscription.sub_id} already exists",
        )

    return {
        "status": "success",
        "detail": f"Added subscription {subscription.sub_id} to RCTab",
    }
