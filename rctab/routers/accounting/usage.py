"""Set and get usage data."""

import calendar
import datetime
import logging
from typing import Dict, List
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.inspection import inspect

from rctab.constants import ADMIN_OID
from rctab.crud import accounting_models
from rctab.crud.accounting_models import refresh_materialised_view, usage_view
from rctab.crud.auth import token_admin_verified
from rctab.crud.models import database, executemany
from rctab.crud.schema import AllCMUsage, AllUsage, CMUsage, Usage, UserRBAC
from rctab.crud.utils import insert_subscriptions_if_not_exists
from rctab.routers.accounting.desired_states import refresh_desired_states
from rctab.routers.accounting.routes import router
from rctab.routers.accounting.send_emails import UsageEmailContextManager
from rctab.settings import get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logger = logging.getLogger(__name__)


class TmpReturnStatus(BaseModel):
    """A wrapper for a status message."""

    status: str


async def authenticate_usage_app(token: str = Depends(oauth2_scheme)) -> Dict[str, str]:
    """Authenticates the usage function app."""
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

    public_key = get_settings().usage_func_public_key

    if not public_key:

        raise missing_key_exception

    try:
        payload = jwt.decode(
            token, public_key, algorithms=["RS256"], options={"require": ["exp", "sub"]}
        )
        username = payload.get("sub")

        if username != "usage-app":
            raise credentials_exception
    except HTTPException as e:
        logger.error(e)
        raise credentials_exception
    return payload


async def insert_usage(all_usage: AllUsage) -> None:
    """Inserts usage into the database.

    Args:
        all_usage: Usage data to insert.
    """
    usage_query = insert(accounting_models.usage)
    update_dict = {c.name: c for c in usage_query.excluded if not c.primary_key}
    on_duplicate_key_stmt = usage_query.on_conflict_do_update(
        index_elements=inspect(accounting_models.usage).primary_key,
        set_=update_dict,
    )

    logger.info("Inserting usage data")
    insert_start = datetime.datetime.now()

    await executemany(
        database,
        on_duplicate_key_stmt,
        values=[i.dict() for i in all_usage.usage_list],
    )
    logger.info("Inserting usage data took %s", datetime.datetime.now() - insert_start)
    refresh_start = datetime.datetime.now()
    await refresh_materialised_view(database, usage_view)
    logger.info(
        "Refreshing the usage view took %s",
        datetime.datetime.now() - refresh_start,
    )


@router.post("/monthly-usage", response_model=TmpReturnStatus)
async def post_monthly_usage(
    all_usage: AllUsage, _: Dict[str, str] = Depends(authenticate_usage_app)
) -> TmpReturnStatus:
    """Inserts monthly usage data into the database."""
    logger.info("Post monthly usage called")

    post_start = datetime.datetime.now()

    date_min = datetime.date.today() + datetime.timedelta(days=4000)
    date_max = datetime.date.today() - datetime.timedelta(days=4000)
    monthly_usage = True

    for usage in all_usage.usage_list:
        if usage.date < date_min:
            date_min = usage.date
        if usage.date > date_max:
            date_max = usage.date
        if usage.monthly_upload is None:
            monthly_usage = False

    logger.info(
        "Post monthly usage received data for %s - %s containing %d records",
        date_min,
        date_max,
        len(all_usage.usage_list),
    )

    if date_min.year != date_max.year or date_min.month != date_max.month:
        raise HTTPException(
            status_code=400,
            detail=f"Post monthly usage data should contain usage only for one month. Min, Max usage date: ({str(date_min)}), ({str(date_max)}).",
        )

    if not monthly_usage:
        raise HTTPException(
            status_code=400,
            detail="Post monthly usage data must have the monthly_upload column populated.",
        )

    month_start = datetime.date(date_min.year, date_min.month, 1)
    month_end = datetime.date(
        date_min.year,
        date_min.month,
        calendar.monthrange(date_min.year, date_min.month)[1],
    )

    logger.info(
        "Post monthly usage checks if data for %s - %s has already been posted",
        month_start,
        month_end,
    )

    # Check if monthly usage has already been posted for the month
    query = select([accounting_models.usage])
    query = query.where(accounting_models.usage.c.date >= month_start)
    query = query.where(accounting_models.usage.c.date <= month_end)
    query = query.where(accounting_models.usage.c.monthly_upload.isnot(None))

    query_result = await database.fetch_all(query)

    if query_result is not None and len(query_result) > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Post monthly usage data for {str(month_start)}-{str(month_end)} has already been posted.",
        )

    async with UsageEmailContextManager(database):

        async with database.transaction():

            logger.info(
                "Post monthly usage deleting existing usage data for %s - %s",
                month_start,
                month_end,
            )

            # delete al the usage for the month
            query_del = accounting_models.usage.delete().where(
                accounting_models.usage.c.date >= month_start
            )
            query_del = query_del.where(accounting_models.usage.c.date <= month_end)
            await database.execute(query_del)

            logger.info(
                "Post monthly usage inserting new subscriptions if they don't exist"
            )

            unique_subscriptions = list(
                {i.subscription_id for i in all_usage.usage_list}
            )

            await insert_subscriptions_if_not_exists(unique_subscriptions)

            logger.info("Post monthly usage inserting monthly usage data")

            await insert_usage(all_usage)

    logger.info("Post monthly usage refreshing desired states")

    await refresh_desired_states(UUID(ADMIN_OID), unique_subscriptions)

    logger.info("Post monthly usage data took %s", datetime.datetime.now() - post_start)

    return TmpReturnStatus(
        status=f"successfully uploaded {len(all_usage.usage_list)} rows"
    )


@router.post("/all-usage", response_model=TmpReturnStatus)
async def post_usage(
    all_usage: AllUsage, _: Dict[str, str] = Depends(authenticate_usage_app)
) -> TmpReturnStatus:
    """Write some usage data to the database."""
    post_start = datetime.datetime.now()

    async with UsageEmailContextManager(database):

        async with database.transaction():
            unique_subscriptions = list(
                {i.subscription_id for i in all_usage.usage_list}
            )

            await insert_subscriptions_if_not_exists(unique_subscriptions)

            await insert_usage(all_usage)

    await refresh_desired_states(UUID(ADMIN_OID), unique_subscriptions)

    logger.info("POSTing usage took %s", datetime.datetime.now() - post_start)

    return TmpReturnStatus(
        status=f"successfully uploaded {len(all_usage.usage_list)} rows"
    )


@router.get("/all-usage", response_model=List[Usage])
async def get_usage(_: UserRBAC = Depends(token_admin_verified)) -> List[Usage]:
    """Get all usage data."""
    usage_query = select([accounting_models.usage])
    rows = [dict(x) for x in await database.fetch_all(usage_query)]
    result = [Usage(**x) for x in rows]

    return result


@router.post("/all-cm-usage", response_model=TmpReturnStatus)
async def post_cm_usage(
    all_cm_usage: AllCMUsage,
    _: Dict[str, str] = Depends(authenticate_usage_app),
) -> TmpReturnStatus:
    """Write cost-management data to the database."""
    async with database.transaction():
        unique_subscriptions = list(
            {i.subscription_id for i in all_cm_usage.cm_usage_list}
        )

        await insert_subscriptions_if_not_exists(unique_subscriptions)

        cm_query = insert(accounting_models.costmanagement)
        update_dict = {c.name: c for c in cm_query.excluded if not c.primary_key}
        on_duplicate_key_stmt = cm_query.on_conflict_do_update(
            index_elements=inspect(accounting_models.costmanagement).primary_key,
            set_=update_dict,
        )

        await executemany(
            database,
            on_duplicate_key_stmt,
            values=[i.dict() for i in all_cm_usage.cm_usage_list],
        )

    return TmpReturnStatus(
        status=f"successfully uploaded {len(all_cm_usage.cm_usage_list)} rows"
    )


@router.get("/all-cm-usage", response_model=List[CMUsage])
async def get_cm_usage(_: UserRBAC = Depends(token_admin_verified)) -> List[CMUsage]:
    """Get all cost-management data."""
    cm_query = select([accounting_models.costmanagement])
    rows = [dict(x) for x in await database.fetch_all(cm_query)]
    result = [CMUsage(**x) for x in rows]
    return result
