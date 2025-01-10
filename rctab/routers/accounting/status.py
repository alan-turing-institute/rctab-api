"""Receive data from the status function app."""

from typing import Dict
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.logger import logger
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from rctab_models.models import AllSubscriptionStatus, SubscriptionStatus
from sqlalchemy import and_, desc, insert, select

from rctab.constants import ADMIN_OID, EMAIL_TYPE_SUB_WELCOME
from rctab.crud.accounting_models import emails, subscription_details
from rctab.crud.models import database
from rctab.crud.utils import insert_subscriptions_if_not_exists
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import router
from rctab.settings import get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class TmpReturnStatus(BaseModel):
    """A wrapper for a status message."""

    status: str


async def authenticate_status_app(
    token: str = Depends(oauth2_scheme),
) -> Dict[str, str]:
    """Authenticate the status function app."""
    headers = {"WWW-Authenticate": "Bearer"}

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers=headers,
    )
    missing_key_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials - endpoint doesn't have public key",
        headers=headers,
    )

    public_key = get_settings().status_func_public_key

    if not public_key:
        raise missing_key_exception

    try:
        payload = jwt.decode(
            token, public_key, algorithms=["RS256"], options={"require": ["exp", "sub"]}
        )
        username = payload.get("sub")

        if username != "status-app":
            raise credentials_exception
    except Exception as e:
        logger.error(e)
        raise credentials_exception
    return payload


@router.post("/all-status", response_model=TmpReturnStatus)
async def post_status(
    all_status: AllSubscriptionStatus,
    _: Dict[str, str] = Depends(authenticate_status_app),
) -> TmpReturnStatus:
    """Inserts subscription status data into the database."""
    async with database.transaction():
        unique_subscriptions = [i.subscription_id for i in all_status.status_list]

        await insert_subscriptions_if_not_exists(unique_subscriptions)

        for new_status in all_status.status_list:
            temp = new_status.model_dump_json().encode("utf-8")
            if b"\\u0000" in temp:
                logger.warning(
                    "Subscription Status contained unexpected unicode NULL codepoint: %s",
                    new_status,
                )
                new_status = SubscriptionStatus.model_validate_json(
                    temp.replace(b"\\u0000", b"NUL").decode("utf-8")
                )

            # We want the most recent status for this subscription.
            status_select = (
                subscription_details.select()
                .where(
                    subscription_details.c.subscription_id == new_status.subscription_id
                )
                .order_by(desc(subscription_details.c.id))
            )
            status_row = await database.fetch_one(status_select)
            old_status = SubscriptionStatus(**dict(status_row)) if status_row else None

            previous_welcome_email = await database.fetch_one(
                select([emails]).where(
                    and_(
                        emails.c.subscription_id == new_status.subscription_id,
                        emails.c.type == EMAIL_TYPE_SUB_WELCOME,
                    )
                )
            )

            # If there is no prior status or the status has changed at all, we want to insert a new row.
            if old_status != new_status:
                status_insert = insert(subscription_details)
                await database.execute(
                    query=status_insert, values=new_status.model_dump()
                )

                if previous_welcome_email:
                    # We want to ignore some roles when deciding whether to
                    # send a status change email.
                    filtered_new_status = SubscriptionStatus(**new_status.model_dump())
                    filtered_new_status.role_assignments = tuple(
                        x
                        for x in filtered_new_status.role_assignments
                        if x.role_name in get_settings().roles_filter
                    )

                    if old_status:
                        filtered_old_status = SubscriptionStatus(
                            **old_status.model_dump()
                        )
                        filtered_old_status.role_assignments = tuple(
                            x
                            for x in filtered_old_status.role_assignments
                            if x.role_name in get_settings().roles_filter
                        )
                    else:
                        filtered_old_status = None

                    if filtered_old_status != filtered_new_status:
                        await send_emails.send_status_change_emails(
                            database, new_status, old_status
                        )

            if not previous_welcome_email:
                welcome_kwargs = send_emails.prepare_welcome_email(database, new_status)
                await send_emails.send_generic_email(**welcome_kwargs)

    # Send expiry emails if needed.
    await send_emails.check_for_subs_nearing_expiry(database)

    # Send overbudget emails if needed.
    await send_emails.check_for_overbudget_subs(database)

    # Not strictly necessary, since the status data shouldn't have changed them,
    # but refresh the desired states anyway
    await refresh_desired_states(UUID(ADMIN_OID), unique_subscriptions)

    return TmpReturnStatus(status="success")
