"""Calculate and disseminate the desired states of subscriptions."""
import datetime
import logging
from typing import Dict, List, Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import Enum, and_, case, cast, func, literal_column, not_, or_, select

from rctab.constants import ADJUSTMENT_DELTA, ADMIN_OID, EXPIRY_ADJUSTMENT_MSG
from rctab.crud.accounting_models import allocations as allocations_table
from rctab.crud.accounting_models import approvals as approvals_table
from rctab.crud.accounting_models import status as status_table
from rctab.crud.models import database
from rctab.crud.schema import (
    DEFAULT_CURRENCY,
    BillingStatus,
    DesiredState,
    SubscriptionState,
)
from rctab.routers.accounting import send_emails
from rctab.routers.accounting.routes import get_subscriptions_summary, router
from rctab.settings import get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logger = logging.getLogger(__name__)


class TmpReturnStatus(BaseModel):
    """A wrapper for a status message."""

    status: str


async def authenticate_app(token: str = Depends(oauth2_scheme)) -> Dict[str, str]:
    """Authenticate the controller app."""
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

    public_key = get_settings().controller_func_public_key

    if not public_key:
        raise missing_key_exception

    try:
        payload = jwt.decode(
            token, public_key, algorithms=["RS256"], options={"require": ["exp", "sub"]}
        )
        username = payload.get("sub")

        if username != "controller-app":
            raise credentials_exception
    except HTTPException as e:
        logger.error(e)
        raise credentials_exception
    return payload


@router.get("/desired-states", response_model=List[DesiredState])
async def get_desired_states(
    _: Dict[str, str] = Depends(authenticate_app)
) -> List[DesiredState]:
    """Get the desired states of subscriptions that need to be enabled/disabled."""
    # pylint: disable=singleton-comparison,unexpected-keyword-arg

    # Refresh the desired states before we return them
    await refresh_desired_states(UUID(ADMIN_OID))

    # Handle: desired_status == NULL and status == NULL
    summaries = get_subscriptions_summary(execute=False).alias()

    to_be_changed = select(
        [
            summaries.c.subscription_id,
            case(
                [
                    # If the desired status is False, we want to disable it
                    (
                        summaries.c.desired_status == False,
                        SubscriptionState("Disabled"),
                    ),
                    # If the desired status is True, we want to enable it
                    (summaries.c.desired_status == True, SubscriptionState("Enabled")),
                ]
            ).label("desired_state"),
        ]
    ).where(
        or_(
            and_(
                summaries.c.desired_status == False,
                or_(
                    summaries.c.status == SubscriptionState("Enabled"),
                    summaries.c.status == SubscriptionState("PastDue"),
                ),
            ),
            and_(
                summaries.c.desired_status == True,
                or_(
                    summaries.c.status == SubscriptionState("Disabled"),
                    summaries.c.status == SubscriptionState("Warned"),
                    summaries.c.status == SubscriptionState("Expired"),
                ),
            ),
        )
    )

    rows = await database.fetch_all(to_be_changed)

    desired_state_list = [
        DesiredState(
            subscription_id=row["subscription_id"],
            desired_state=row["desired_state"],
        )
        for row in rows
    ]

    if not get_settings().ignore_whitelist:
        whitelist = get_settings().whitelist
        desired_state_list = [
            x for x in desired_state_list if x.subscription_id in whitelist
        ]

    return desired_state_list


async def refresh_desired_states(
    admin_oid: UUID,
    subscription_ids: Optional[List[UUID]] = None,
) -> None:
    """Inserts new status rows for if the desired status has changed."""
    # pylint: disable=singleton-comparison
    # pylint: disable=unexpected-keyword-arg
    # pylint: disable=too-many-locals

    sub_query = get_subscriptions_summary(execute=False).alias()

    if subscription_ids:
        summaries = (
            select([sub_query])
            .where(
                sub_query.c.subscription_id.in_(
                    [str(sub_id) for sub_id in subscription_ids]
                )
            )
            .alias()
        )
    else:
        summaries = sub_query

    # Subscriptions without an approved_to date or whose approved_to
    # date is in the past, that currently have a desired_status of True
    over_time = (
        select([summaries]).where(
            and_(
                or_(
                    summaries.c.approved_to == None,
                    summaries.c.approved_to <= datetime.date.today(),
                ),
                or_(
                    summaries.c.always_on == False,
                    summaries.c.always_on == None,
                ),
            )
        )
    ).alias()

    # Adjusting approvals and allocations for expired subscriptions
    for row in await database.fetch_all(over_time):
        if row["allocated"] - row["total_cost"] >= ADJUSTMENT_DELTA:
            insert_neg_allocation = allocations_table.insert().values(
                subscription_id=row["subscription_id"],
                admin=admin_oid,
                ticket=EXPIRY_ADJUSTMENT_MSG,
                amount=row["total_cost"] - row["allocated"],
                currency=DEFAULT_CURRENCY,
            )
            await database.execute(insert_neg_allocation)

        if row["approved"] - row["total_cost"] >= ADJUSTMENT_DELTA:
            insert_neg_approval = approvals_table.insert().values(
                subscription_id=row["subscription_id"],
                admin=admin_oid,
                ticket=EXPIRY_ADJUSTMENT_MSG,
                amount=row["total_cost"] - row["approved"],
                currency=DEFAULT_CURRENCY,
                date_from=row["approved_from"],
                date_to=row["approved_to"],
            )
            await database.execute(insert_neg_approval)

    # Subscriptions with more usage than allocated budget
    # that currently have a desired_status of True
    over_budget = (
        select([summaries])
        .where(
            and_(
                # To gracelessly sidestep rounding errors, allow a tolerance
                summaries.c.allocated + ADJUSTMENT_DELTA < summaries.c.total_cost,
                or_(
                    summaries.c.always_on == False,
                    summaries.c.always_on == None,
                ),
            )
        )
        .alias()
    )

    over_time_or_over_budget = (
        select(
            [
                literal_column("1").label("reason_enum"),
                over_time.c.subscription_id,
                literal_column("uuid('" + str(admin_oid) + "')").label("admin_oid"),
                literal_column("False").label("active"),
                over_time.c.desired_status,
                over_time.c.desired_status_info,
            ]
        )
        .union(
            select(
                [
                    literal_column("2").label("reason_enum"),
                    over_budget.c.subscription_id,
                    literal_column("uuid('" + str(admin_oid) + "')").label("admin_oid"),
                    literal_column("False").label("active"),
                    over_budget.c.desired_status,
                    over_budget.c.desired_status_info,
                ]
            )
        )
        .alias()
    )

    over_time_or_over_budget_reason = (
        select(
            [
                over_time_or_over_budget.c.subscription_id,
                over_time_or_over_budget.c.admin_oid,
                over_time_or_over_budget.c.active,
                case(
                    [
                        (
                            func.sum(over_time_or_over_budget.c.reason_enum) == 1,
                            cast(BillingStatus.EXPIRED, Enum(BillingStatus)),
                        ),
                        (
                            func.sum(over_time_or_over_budget.c.reason_enum) == 2,
                            cast(BillingStatus.OVER_BUDGET, Enum(BillingStatus)),
                        ),
                        (
                            func.sum(over_time_or_over_budget.c.reason_enum) == 3,
                            cast(
                                BillingStatus.OVER_BUDGET_AND_EXPIRED,
                                Enum(BillingStatus),
                            ),
                        ),
                    ],
                ).label("reason"),
                over_time_or_over_budget.c.desired_status_info.label("old_reason"),
                over_time_or_over_budget.c.desired_status.label("old_desired_status"),
            ]
        )
        .group_by(
            over_time_or_over_budget.c.subscription_id,
            over_time_or_over_budget.c.admin_oid,
            over_time_or_over_budget.c.active,
            over_time_or_over_budget.c.desired_status_info,
            over_time_or_over_budget.c.desired_status,
        )
        .alias()
    )

    # Only insert a row if the most recent row is incorrect i.e. is missing or has the wrong
    # desired status or has the wrong reason or a missing reason
    over_time_or_over_budget_desired_on = (
        select(
            [
                over_time_or_over_budget_reason.c.subscription_id,
                over_time_or_over_budget_reason.c.admin_oid,
                over_time_or_over_budget_reason.c.active,
                over_time_or_over_budget_reason.c.reason,
                over_time_or_over_budget_reason.c.old_reason,
            ]
        )
        .where(
            or_(
                over_time_or_over_budget_reason.c.old_desired_status == None,
                over_time_or_over_budget_reason.c.old_desired_status == True,
                over_time_or_over_budget_reason.c.old_reason == None,
                over_time_or_over_budget_reason.c.reason
                != over_time_or_over_budget_reason.c.old_reason,
            ),
        )
        .alias()
    )

    # Insert rows for subscriptions that should be disabled but
    # aren't currently.
    insert_false_statement = status_table.insert().from_select(
        [
            status_table.c.subscription_id,
            status_table.c.admin,
            status_table.c.active,
            status_table.c.reason,
        ],
        select(
            [
                over_time_or_over_budget_desired_on.c.subscription_id,
                over_time_or_over_budget_desired_on.c.admin_oid,
                over_time_or_over_budget_desired_on.c.active,
                over_time_or_over_budget_desired_on.c.reason,
            ]
        ),
    )

    # Execute query before the insert, as it won't return anything afterwards
    to_be_inserted = await database.fetch_all(over_time_or_over_budget_desired_on)
    subscriptions_and_reasons = [
        (row["subscription_id"], row["reason"].value, row["old_reason"])
        for row in to_be_inserted
    ]

    for subscription_id, reason, old_reason in subscriptions_and_reasons:
        # Sending emails when the reason changes is unnecessary
        if not old_reason:
            await send_emails.send_generic_email(
                database,
                subscription_id,
                "will_be_disabled.html",
                "We will turn off your Azure subscription:",
                "subscription disabled",
                {"reason": reason},
            )

    await database.execute(insert_false_statement)

    # Insert rows for subscriptions that should be enabled
    # but aren't currently. These are all of our subscriptions
    # that are disabled but aren't over time or budget.
    should_be_enabled_but_are_not = select(
        [
            summaries.c.subscription_id,
            literal_column("uuid('" + str(admin_oid) + "')"),
            literal_column("True"),
            literal_column("NULL"),
        ]
    ).where(
        and_(
            not_(
                summaries.c.subscription_id.in_(
                    select([over_time_or_over_budget.c.subscription_id])
                )
            ),
            or_(
                summaries.c.desired_status == False,
                summaries.c.desired_status == None,
            ),
        ),
    )

    insert_true_statement = status_table.insert().from_select(
        [
            status_table.c.subscription_id,
            status_table.c.admin,
            status_table.c.active,
            status_table.c.reason,
        ],
        should_be_enabled_but_are_not,
    )

    # Execute query before the insert, as it won't return anything afterwards
    to_be_inserted = await database.fetch_all(should_be_enabled_but_are_not)
    subscriptions = [row["subscription_id"] for row in to_be_inserted]

    for subscription_id in subscriptions:
        await send_emails.send_generic_email(
            database,
            subscription_id,
            "will_be_enabled.html",
            "We will turn on your Azure subscription:",
            "subscription enabled",
            {},
        )

    await database.execute(insert_true_statement)
