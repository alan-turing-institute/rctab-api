"""Routes that determine whether a subscription is permanently on."""

from typing import Any
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import insert

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database
from rctab.crud.schema import UserRBAC
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.routes import router


class NewPersistenceStatus(BaseModel):
    """New persistence status for a subscription."""

    sub_id: UUID
    always_on: bool


@router.post("/persistent", status_code=200)
async def post_persistency_status(
    persistence: NewPersistenceStatus, user: UserRBAC = Depends(token_admin_verified)
) -> Any:
    """Return the latest value of always_on setting."""
    await database.execute(
        insert(accounting_models.persistence),
        {
            "admin": user.oid,
            "subscription_id": persistence.sub_id,
            "always_on": persistence.always_on,
        },
    )

    await send_emails.send_generic_email(
        database,
        persistence.sub_id,
        "persistence_change.html",
        "Persistence change for your Azure subscription:",
        "subscription persistence",
        persistence.dict(),
    )

    return {
        "status": "success",
        "detail": f'Subscription {persistence.sub_id} is now {"persistent" if persistence.always_on else "not persistent"}',
    }
