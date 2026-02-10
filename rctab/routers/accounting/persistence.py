"""Routes that determine whether a subscription is permanently on."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from rctab_models.models import UserRBAC
from sqlalchemy import insert
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from rctab.crud import accounting_models
from rctab.crud.auth import token_admin_verified
from rctab.db import get_async_connection
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.routes import router

logger = logging.getLogger(__name__)


class NewPersistenceStatus(BaseModel):
    """New persistence status for a subscription."""

    sub_id: UUID
    always_on: bool


@router.post("/persistent", status_code=200)
async def post_persistency_status(
    persistence: NewPersistenceStatus,
    user: UserRBAC = Depends(token_admin_verified),
    conn: AsyncConnection = Depends(get_async_connection),
) -> Any:
    """Return the latest value of always_on setting."""
    await conn.execute(
        insert(accounting_models.persistence),
        {
            "admin": user.oid,
            "subscription_id": persistence.sub_id,
            "always_on": persistence.always_on,
        },
    )

    # pylint: disable=broad-exception-caught
    try:
        # Preserve persistence changes even if notification handling fails.
        async with conn.begin_nested():
            await send_emails.send_generic_email(
                conn,
                persistence.sub_id,
                "persistence_change.html",
                "Persistence change for your Azure subscription:",
                "subscription persistence",
                persistence.model_dump(),
            )
    except Exception:  # pragma: no cover - integration behavior
        logger.exception(
            "Failed to send persistence-change notification for %s",
            persistence.sub_id,
        )
    # pylint: enable=broad-exception-caught

    return {
        "status": "success",
        "detail": f'Subscription {persistence.sub_id} is now {"persistent" if persistence.always_on else "not persistent"}',
    }
