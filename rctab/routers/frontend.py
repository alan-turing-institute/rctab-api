"""The user-facing web pages."""
import datetime
import logging
from pathlib import Path
from typing import Dict, Final, List, Optional
from uuid import UUID

import pandas as pd
import plotly.express as px
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapimsal import RequiresLoginException, UserIdentityToken
from jose import jwt
from pydantic import BaseModel, EmailStr, ValidationError
from starlette.templating import _TemplateResponse

from rctab.constants import __version__
from rctab.crud.auth import check_user_access, user_authenticated_no_error
from rctab.crud.schema import (
    AllocationListItem,
    ApprovalListItem,
    CostRecovery,
    FinanceListItem,
    RoleAssignment,
    SubscriptionDetails,
    Usage,
)
from rctab.routers.accounting.routes import (
    get_allocations,
    get_approvals,
    get_costrecovery,
    get_finance,
    get_subscription_details,
    get_subscriptions_with_disable,
    get_usage,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)

templates = Jinja2Templates(
    directory=str((Path(__file__).parent.parent / "templates").absolute())
)
router = APIRouter()

BETA_ACCESS = False


async def get_cost_breakdown(usage_object_list: list) -> pd.DataFrame:
    """Get a cost breakdown to build a plot from."""
    usage_dict = {}
    for usage_object in usage_object_list:
        for variable, value in usage_object:
            if variable not in usage_dict:
                usage_dict[variable] = [value]
            else:
                usage_dict[variable].append(value)
    df = pd.DataFrame.from_dict(usage_dict)
    with pd.option_context("mode.chained_assignment", None):
        df["period"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.strftime(
            "%b-%Y"
        )
    df2 = df[["period", "cost", "amortised_cost", "total_cost"]]
    df2summary = (
        df2.groupby(["period"])
        .agg({"total_cost": "sum", "amortised_cost": "sum", "cost": "sum"})
        .reset_index()
        .round(2)
    )
    df2summary["period"] = pd.to_datetime(df2summary["period"], format="%b-%Y")
    df2summary.sort_values(by="period", ascending=False, inplace=True)
    df2summary["period"] = df2summary["period"].dt.strftime("%b-%Y")
    return df2summary


class Email(BaseModel):
    """A wrapper for an email address."""

    address: EmailStr


def access_to_span(status: bool) -> str:
    """Return an HTML span indicating whether a user has a specific level of access.

    Args:
        status: Whether a user has a specific access type.

    Returns:
        An html span.
    """
    if status:
        return "<span class='hasAccess'>ADMIN: &#10003;</span>"
    return "<span class='noAccess'>ADMIN: &#10060;</span>"


async def check_user_on_subscription(subscription_id: UUID, username: str) -> bool:
    """Check whether a user has a role assignment on the subscription."""
    role_assignments = (await get_subscription_details(subscription_id))[0][
        "role_assignments"
    ]
    if role_assignments:
        for item in role_assignments:
            if RoleAssignment(**item).mail == username:
                return True

    return False


@router.get("/", include_in_schema=False)
async def home(
    request: Request, user: UserIdentityToken = Depends(user_authenticated_no_error)
) -> _TemplateResponse:
    """The home page."""
    settings = get_settings()
    if not user:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "version": __version__,
                "organisation": settings.organisation,
                "current_year": datetime.date.today().year,
            },
        )

    # Get the username from cached token
    token_claims = jwt.get_unverified_claims(user.token["access_token"])
    user_name = token_claims["name"]

    try:
        preferred_user_name: Optional[EmailStr] = Email(
            address=token_claims["unique_name"]
        ).address
    except ValidationError:
        logger.warning(
            "%s has an invalid email address: %s",
            user_name,
            {token_claims["unique_name"]},
        )
        raise HTTPException(status_code=403, detail="Invalid token unique_name")

    # Check the users access status
    access_status = await check_user_access(
        user.oid, username=preferred_user_name, raise_http_exception=False
    )

    # If we're in Beta release mode, only users with 'has_access' can access
    if BETA_ACCESS and (not access_status.has_access):
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "version": __version__,
                "current_year": datetime.date.today().year,
            },
        )

    # Get all subscription data
    # pylint: disable=unexpected-keyword-arg
    all_subscription_data = [
        SubscriptionDetails(**i)
        for i in await get_subscriptions_with_disable(raise_404=False)
    ]

    # What you see depends on if you are an admin (see everything) or not (see only subscriptions you are on)
    if access_status.is_admin:
        subscriptions_with_access = all_subscription_data
    elif not access_status.username:
        # If we don't know the username, the user shouldn't see any subscriptions
        subscriptions_with_access = []
    else:
        # Filter subscriptions the user has RBAC access to
        subscriptions_with_access = []
        for sub in all_subscription_data:
            rbac_assignments = sub.role_assignments
            if rbac_assignments:
                for entry in rbac_assignments:
                    if entry.mail == access_status.username:
                        subscriptions_with_access.append(sub)
                        break
    return templates.TemplateResponse(
        "signed_in_azure_info.html",
        {
            "request": request,
            "name": user_name,
            "version": __version__,
            "has_access": access_to_span(access_status.has_access),
            "is_admin": access_to_span(access_status.is_admin),
            "azure_sub_data": subscriptions_with_access,
            "organisation": settings.organisation,
            "current_year": datetime.date.today().year,
        },
    )


@router.get("/details/{subscription_id}", include_in_schema=False)
async def subscription_details(
    subscription_id: UUID,
    request: Request,
    user: UserIdentityToken = Depends(user_authenticated_no_error),
) -> _TemplateResponse:
    """The subscription details page."""
    if not user:
        return templates.TemplateResponse("index.html", {"request": request})

    # Get the username from cached token
    user_name = jwt.get_unverified_claims(user.token["access_token"])["name"]

    # Check the users access status
    access_status = await check_user_access(
        user.oid, raise_http_exception=False
    )  # pylint: disable=unexpected-keyword-arg

    # Only users with 'has_access' can access for now (BETA testing).
    # Remove this to let all users with institutional credentials have access
    if BETA_ACCESS and (not access_status.has_access):
        raise RequiresLoginException

    # Check the user has access to this specific subscription (either admin or on RBAC)
    if not access_status.is_admin and (
        not access_status.username
        or (
            not await check_user_on_subscription(
                subscription_id, access_status.username
            )
        )
    ):
        raise RequiresLoginException

    all_approvals = [
        ApprovalListItem(**i)
        for i in await get_approvals(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]

    all_allocations = [
        AllocationListItem(**i)
        for i in await get_allocations(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]
    # pylint: disable=line-too-long

    all_finance = [
        FinanceListItem(**i)
        for i in await get_finance(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]
    # pylint: disable=line-too-long

    all_costrecovery = [
        CostRecovery(**i)
        for i in await get_costrecovery(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]

    subscription_details_info = (await get_subscriptions_with_disable(subscription_id))[
        0
    ]
    role_assignments = subscription_details_info["role_assignments"]

    all_rbac_assignments = (
        [RoleAssignment(**i) for i in role_assignments] if role_assignments else []
    )

    role_order: Final = (
        "Owner",
        "User Access Administrator",
        "Management Group Contributor",
        "Contributor",
        "Billing Reader",
        "Reader",
    )

    # Take one pass through the assignments to make a dict...
    assignments_dict: Dict[str, List[RoleAssignment]] = {}
    for assignment in all_rbac_assignments:
        if assignment.role_name not in assignments_dict:
            assignments_dict[assignment.role_name] = []
        if "-function" not in assignment.display_name:
            assignments_dict[assignment.role_name].append(assignment)

    # ...then sort the assignments by role
    sorted_all_rbac_assignments = []
    for role in role_order:
        sorted_all_rbac_assignments.extend(assignments_dict.get(role, []))

    # pylint: disable=line-too-long
    views = {
        "by_resource_past_6m": "H4sIAAAAAAAAA41SXU%2FbQBD8L%2Ffs0BJCFHhLCI2QqB3Fpi8VijbnjTlxvnPvA9WN%2FN%2B7aycttA%2FweLszc7OzexAyOodGtuJarBZrkYgSAm7AVEiVe%2FBh%2BtWa8OSp8yOiI9xBhLbh7ry2LqhfWN5YHwYm5BgYUTkwUYNTgYV7Bd0SBKrKYQVBWdML2QC6Z9PDQM2qR7F9NHKAiTzWokv%2Bgh%2Fy5T94rvxPIY5nh6YS198PolQOT33wEk3JneSks1BaU6H3KrrHhGawsTmRjyMvVY3Gs8Yf3ga9jU5iwYjukY0SaO%2BGbmoNsnn5BC6wsQDymRPTsWYRkDLWlFTAkrp70B6p2qgXG%2Fw7H%2BfoXpTElF9d8hGL91YO0X8MvuIABnmKw0vbE3zceelUw0L%2B08X%2BHGY4no4QcDyaXF5cja4uxzD6DNPz2QTleDIDUn5u1JtxFrGskNeseOybLC%2B26fzb3WpeZJuzxcNydVtss3Vxl6X5WZqlt4REAzvNKQUXkZ4%2FA20Qy7UjW7Rk9K9v4n3B7lUGXyxdBvRn9%2BYXHrtUvtHQpoNwPVzydte6Y0gssZ2K7jdkaa%2FgSgMAAA%3D%3D",  # noqa: E501
        "by_resource_past_30d": "H4sIAAAAAAAAA41SXU%2FjQAz8L%2FucctAWVHhrG65CQknVpLycEDIbN6xIdnP7gS5X5b%2BfndCDwgM8rj0zOx57L2SwFrVsxZVYLdYiEgV43IAukSq34PzkNIbWUeN3QEuwvfBtw815baxXf7FYGucHImToGVFa0KECqzzrxqCqlgBQlhZL8MroXsZ4qHouPTTUrPkqtQtaDjCRhVp00Rt4m8Uf8Fz5TCGOY3%2B6FFe%2F9qJQFg99cBJ1wZ3ooLN1UGJMk4vuPiL7JjQH5uu0sapROxb4T9qgM8FKzBnR3bNLAu3s0E2MRnYun8B6duVBPnNYVahZBKQMNYXksaDuDiqHVG3Ui%2FHui48ztC9KYsKvLvqOxVsjh9y%2FB19xAIM8xeGk6QkuPDppVcNC7sdkdwYzHF%2BMEHA8mp5PLkeX52MYncLF2WyKcjydASk%2FN%2BponEUoSuQdKx57mWb5QzK%2Fu1nN83RzstjGq%2Bv8IV3nN2mSnSRpck1I1PBYcUreBqTnH0%2Frw2JtyRZtGN37g%2FhasHuXwU9DZwH9zR39wmMXyjUVtMkg3B8xn5sT3T%2Bo9DY9NgMAAA%3D%3D",  # noqa: E501
        "by_resource_this_month": "H4sIAAAAAAAAA41Sy07DQAz8lz2nPEpBhVtLoEKCpGpSLgghs3HTFclu2AeiVPl37IZCgQMc156Z9Yy9FjJYi1quxJmYjKciEgV4nIEukSr5Urkbo%2F2S6s8BLaHWwq8a7o1qY716w%2BLcON%2FxIEPPiNKCDhVY5Vk2BlWtCABlabEEr4zeyBgP1YZLDw01a35ILYKWHUxkoRZt9AWeZ%2FEPPFd%2BU4jjeD5dirO7tSiUxW0fnERdcCfa6swdlBiTcdHeRzS%2BCc2W%2BeE2VjVqxwKfpBk6E6zEnBHtPU9JoIXtuonRyJPLJVjPcVkEDkHKUFM2HgsqehuQio16Md798V2G9kVJTPjVRv8Z7NrILu3%2FwSdsu5OnEJw0G4ILj05a1bCQ2z9aHMIQ%2Byc9BOz3BsdHp73T4z70DuDkcDhA2R8M2eVTo77ZGYeiRN6sYtfnaZY%2FJKPbq8koT2d743k8ucgf0ml%2BlSbZXpImF4REDY8Vh8QZ0fPV09KwmFoai%2FaKbvcM%2FhZsdzK4NHQMsLm0b7%2Bw7UK5poJV0gmPvrbFp%2BZE%2Bw4wtbHgMQMAAA%3D%3D",  # noqa: E501
        "by_resource_this_year": "H4sIAAAAAAAAA41SXW%2FbMAz8L3p2ujVNi7RvSdMFBTY7iN0BxVAUrMw4wmzJo6RiWeD%2FPtJu%2BrE9tI8i7068I%2FdKRyK0eqcu1HK%2BUokqIeAabIVcKbbG3yIQl39FJAbtVdi10po1joL5g%2BWl82GgQY5BEBWBjTWQCaL6zdmwrXcMgaoirCAYZ3shF6Du2fyw0Ijqk9gmWj3AVB4b1SUv4Jt88Q9eKv9TmONlQlupix97VRrCQx%2B8RltKJznozE1dc6GfVXV3CXtwsT2QnywvTIPWi8Yzb43eRdJYCKK7k0EZtKGhmzqLMrzeAgXJjBAkB61jwwEFLLkYKCIXW%2FPogn%2Fnuxzp0WhM5dUlHxnsq9ND4B%2BDL8X2IM8heO16go8PXpNpRch%2FOtkcwxTHZyMEHI8mpyfno%2FPTMYw%2Bw9nxdIJ6PJmKy5%2BteWNnHssKZblGXF9meXGfzr5fL2dFtj6a3yyWV8V9tiquszQ%2FSrP0ipFo4aGWkCQjfv4OvDcsV8Rj8WrRv76E9wW7Vxl8cXwP0B%2Fbm1%2FEdml8W8MuHYRnL9uSa%2FOq%2BwsySNt7NQMAAA%3D%3D",  # noqa: E501
    }
    # pylint: enable=line-too-long

    return templates.TemplateResponse(
        "signed_in_azure_info_details.html",
        {
            "request": request,
            "name": user_name,
            "version": __version__,
            "has_access": access_to_span(access_status.has_access),
            "is_admin": access_to_span(access_status.is_admin),
            "subscription_id": subscription_id,
            "subscription_details": subscription_details_info,
            "all_approvals": all_approvals,
            "all_allocations": all_allocations,
            "all_finance": all_finance,
            "all_costrecovery": all_costrecovery,
            "all_rbac_assignments": sorted_all_rbac_assignments,
            "views": views,
            "current_year": datetime.date.today().year,
        },
    )


@router.get("/process_usage/{subscription_id}")
async def subscription_details_1(
    request: Request,
    subscription_id: UUID,
    timeperiodstr: str,
    user: UserIdentityToken = Depends(user_authenticated_no_error),
) -> _TemplateResponse:
    """Get html for the usage tab of the details page."""
    if not user:
        return templates.TemplateResponse("index.html", {"request": request})

    # Get the username from cached token
    # user_name = jwt.get_unverified_claims(user.token["access_token"])["name"]

    # Check the users access status
    access_status = await check_user_access(
        user.oid, raise_http_exception=False
    )  # pylint: disable=unexpected-keyword-arg

    # Only users with 'has_access' can access for now (BETA testing). Remove this to let all users with institutional credentials have access
    if BETA_ACCESS and (not access_status.has_access):
        raise RequiresLoginException

    # Check the user has access to this specific subscription (either admin or on RBAC)
    if not access_status.is_admin and (
        not access_status.username
        or (
            not await check_user_on_subscription(
                subscription_id, access_status.username
            )
        )
    ):
        raise RequiresLoginException

    cost_breakdown = None
    fig = None
    usage_fig = None
    all_usage = []
    time_frame_start = None
    # Set period for usage and query
    try:
        timeperiod = datetime.datetime.strptime(timeperiodstr, "%Y-%m-%d")
    except ValueError:
        return templates.TemplateResponse(
            "azure_usage_info.html",
            {
                "request": request,
                "cost_breakdown": None,
            },
        )
    all_usage = [
        Usage(**i)
        for i in await get_usage(
            subscription_id, timeperiod, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]
    # pylint: disable=line-too-long
    if len(all_usage) > 0:
        cost_breakdown = await get_cost_breakdown(all_usage)
        assert isinstance(timeperiod, datetime.date)
        time_frame_start = datetime.datetime.strftime(
            timeperiod,  # type: ignore
            "%d-%m-%Y",
        )
        fig = px.bar(
            cost_breakdown,
            x="period",
            y=["cost", "amortised_cost"],
            labels={"period": "Date", "value": "Cost (£)"},
            width=600,
            height=500,
            template="plotly_white",
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        usage_fig = fig.to_html(full_html=False, include_plotlyjs="cdn").replace(
            "<div>", '<div class="usageFigure">'
        )
    return templates.TemplateResponse(
        "azure_usage_info.html",
        {
            "request": request,
            "cost_breakdown": cost_breakdown,
            "all_usage": all_usage,
            "time_frame_start": time_frame_start,
            "usage_fig": usage_fig,
        },
    )
