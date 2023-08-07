from typing import Any, List, Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy import insert

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import SubscriptionDetails, UserRBAC
from rctab.routers.accounting.routes import (
    SubscriptionItem,
    get_subscriptions_with_disable,
    router,
)


async def create_subscription(subscription: SubscriptionItem, user: UserRBAC) -> None:
    """
    Creates a new subscription.
    """

    async with database.transaction():
        await database.execute(
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
) -> SubscriptionDetails:
    """
    Returns a flag whether a subscription with the specified uuid is registered.
    """

    retval = await get_subscriptions_with_disable(sub_id)
    return retval


@router.post("/subscription")
async def post_subscription(
    subscription: SubscriptionItem, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """
    Creates a new subscription.
    """

    await create_subscription(subscription, user)

    return {
        "status": "success",
        "detail": f"Added subscription {subscription.sub_id} to RCTab",
    }
