"""The user-facing web pages."""
import datetime
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

import numpy as np
import pandas as pd
import plotly.express as px
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapimsal import RequiresLoginException, UserIdentityToken
from jose import jwt
from prophet import Prophet
from pydantic import BaseModel, EmailStr, ValidationError
from starlette.templating import _TemplateResponse
from statsmodels.tsa.arima.model import ARIMA

from rctab.constants import __version__
from rctab.crud.auth import check_user_access, user_authenticated_no_error
from rctab.crud.schema import (
    AllocationListItem,
    ApprovalListItem,
    ConsumedServiceData,
    CostRecovery,
    FinanceWithCostRecovery,
    RoleAssignment,
    SubscriptionDetails,
    Usage,
    UsageDailyTotal,
    UsageForecastData,
    UsageForecastSummary,
)
from rctab.routers.accounting.routes import (
    get_allocations,
    get_approvals,
    get_consumed_service_data,
    get_costrecovery,
    get_daily_usage_total,
    get_finance_costs_recovered,
    get_subscription_details,
    get_subscriptions_with_disable,
    get_usage,
    get_usage_forecast_data,
    get_usage_forecast_summary,
    get_usage_forecast_summary_all,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)

templates = Jinja2Templates(
    directory=str((Path(__file__).parent.parent / "templates").absolute())
)
router = APIRouter()

BETA_ACCESS = False


async def convert_to_pd_df(object_list: list) -> pd.DataFrame:
    """Extract the attributes from a list of objects and place in a pandas dataframe."""
    obj_dict = {}
    for usage_object in object_list:
        for variable, value in usage_object:
            if variable not in obj_dict:
                obj_dict[variable] = [value]
            else:
                obj_dict[variable].append(value)
    return pd.DataFrame.from_dict(obj_dict)


async def get_cost_breakdown(usage_object_list: list) -> pd.DataFrame:
    """Get a cost breakdown to build a plot from."""
    df = await convert_to_pd_df(usage_object_list)
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


async def get_usage_forecast(
    subscription_id: UUID, approvals_obj: list, financial_year_start: datetime.date
) -> list:
    """Plot usage and approvals."""
    usage_forecast_summary_obj = [
        UsageForecastSummary(**i)
        for i in await get_usage_forecast_summary(
            str(subscription_id), raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]
    usage_forecast_data_obj = [
        UsageForecastData(**i)
        for i in await get_usage_forecast_data(str(subscription_id))
    ]
    report_df = await convert_to_pd_df(usage_forecast_summary_obj)
    approvals_df = await convert_to_pd_df(approvals_obj)
    approvals_df = approvals_df[
        (approvals_df["date_to"] >= financial_year_start)
        & (
            approvals_df["date_from"]
            < financial_year_start + datetime.timedelta(days=365)
        )
    ]
    approvals_df["cumulative_approval_amount"] = approvals_df["amount"].cumsum()
    usage_forecast_df = await convert_to_pd_df(usage_forecast_data_obj)
    if report_df.empty:
        report_df = pd.DataFrame(
            columns=[
                "fy_spend_to_date",
                "fy_projected_spend",
                "fy_projected_dif",
                "approval_end_date_projected_spend",
                "datetime_data_updated",
            ],
            values=[0, 0, 0, 0, datetime.datetime.now()],
        )
        return report_df, "Forecast not available"

    # Make forecast plot
    forecast_plot_html = plot_subscription_usage_forecast(
        usage_forecast_df, approvals_df
    )
    return report_df, forecast_plot_html


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
    rbac_assignments = [
        RoleAssignment(**i)
        for i in (await get_subscription_details(subscription_id))[0][
            "role_assignments"
        ]
    ]

    for entry in rbac_assignments:
        if entry.mail == username:
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
            "index.html", {"request": request, "version": __version__}
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

    all_costrecovery = [
        CostRecovery(**i)
        for i in await get_costrecovery(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]

    all_finance_with_costs_recovered = [
        FinanceWithCostRecovery(**i)
        for i in await get_finance_costs_recovered(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]

    # Get report data
    today = datetime.date.today()
    if today.month < 4:
        financial_year_start = datetime.date(today.year - 1, 4, 1)
    else:
        financial_year_start = datetime.date(today.year, 4, 1)
    projection_data, html_forecast_fig = await get_usage_forecast(
        subscription_id, all_approvals, financial_year_start
    )

    # pylint: disable=line-too-long
    subscription_details_info = (await get_subscriptions_with_disable(subscription_id))[
        0
    ]

    # return 404 if subscription does not have rbac
    if subscription_details_info["role_assignments"] is None:
        return templates.TemplateResponse(
            "404.html",
            {
                "request": request,
                "version": __version__,
                "subscription_id": subscription_id,
            },
        )

    all_rbac_assignments = [
        RoleAssignment(**i)
        for i in (await get_subscription_details(subscription_id, raise_404=False))[0][
            "role_assignments"
        ]
    ]  # pylint: disable=unexpected-keyword-arg
    # pylint: disable=line-too-long
    role_order = [
        "Owner",
        "User Access Administrator",
        "Management Group Contributor",
        "Contributor",
        "Billing Reader",
        "Reader",
    ]
    sorted_all_rbac_assignments = [
        v
        for x in role_order
        for v in all_rbac_assignments
        if v.role_name == x and "-function" not in v.display_name
    ]

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
            "all_finance": all_finance_with_costs_recovered,
            "all_costrecovery": all_costrecovery,
            "all_rbac_assignments": sorted_all_rbac_assignments,
            "views": views,
            "total_recovered_costs": sum(
                item.total_recovered for item in all_finance_with_costs_recovered
            ),
            "usage_fig_forecast": html_forecast_fig,
            "projection_data": projection_data,
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
            "<div>", '<div class="usageFigure">', regex=True
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


@router.get("/azreport/{financial_year}")
async def azure_report(
    request: Request,
    financial_year: str,
    user: UserIdentityToken = Depends(user_authenticated_no_error),
) -> _TemplateResponse:
    """Get HTML of the reports data."""

    if not user:
        return templates.TemplateResponse("index.html", {"request": request})

    # Check the users access status
    access_status = await check_user_access(
        user.oid, raise_http_exception=False
    )  # pylint: disable=unexpected-keyword-arg

    if not access_status.is_admin:
        return templates.TemplateResponse("index.html", {"request": request})

    financial_year_start = datetime.date(int(f"20{financial_year[:2]}"), 4, 1)
    financial_year_end = datetime.date(int(f"20{financial_year[3:]}"), 4, 1)

    # check user is an admin to display the report
    if not user:
        return templates.TemplateResponse("index.html", {"request": request})

    # Check the users access status
    access_status = await check_user_access(
        user.oid, raise_http_exception=False
    )  # pylint: disable=unexpected-keyword-arg

    if not access_status.is_admin:
        return templates.TemplateResponse("index.html", {"request": request})

    daily_report_obj = [
        UsageForecastSummary(**i)
        for i in await get_usage_forecast_summary_all(
            raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]
    report_df = await convert_to_pd_df(daily_report_obj)
    report_df["core_project"] = np.where(
        (report_df["current_fy_finance"] == 0) & (report_df["costs_recovered_fy"] == 0),
        "Core",
        "Project",
    )
    report_df["fy_projected_over"] = np.where(
        report_df["fy_projected_dif"] > 0, report_df["fy_projected_dif"], 0
    )
    report_df["fy_projected_under"] = np.where(
        report_df["fy_projected_dif"] < 0, report_df["fy_projected_dif"].abs(), 0
    )
    report_df["awaiting_recovery"] = np.where(
        report_df["core_project"] == "Project",
        report_df["fy_spend_to_date"] - report_df["costs_recovered_fy"],
        0,
    )
    named_cols = {
        "fy_approved_amount": "Total approved spending",
        "current_fy_finance": "Current finance approved",
        "fy_spend_to_date": "Total current spending",
        "costs_recovered_fy": "Total costs recovered",
        "awaiting_recovery": "Total costs awaiting recovery",
        "fy_projected_spend": "Total projected spending",
        "fy_projected_over": "Total projected overspend",
        "fy_projected_under": "Total projected underspend",
        "fy_predicted_core_spending": "Predicted spending from core",
    }
    report_df.rename(columns=named_cols, inplace=True)
    report_pivot = report_df.pivot_table(
        columns=["core_project"],
        values=[nc for nc in named_cols.values()],
        aggfunc=np.sum,
    )
    report_pivot = report_pivot.reindex(named_cols.values())
    report_pivot["rowname"] = report_pivot.index

    financial_year = f"{financial_year_start.year}-{financial_year_end.year}"

    # subscription details aggregation
    all_subscription_data = [
        SubscriptionDetails(**i)
        for i in await get_subscriptions_with_disable(raise_404=False)
    ]

    all_subscription_df = await convert_to_pd_df(all_subscription_data)
    all_subscription_df = pd.merge(
        all_subscription_df,
        report_df[["subscription_id", "core_project"]],
        on="subscription_id",
        how="right",
    )
    all_subscription_df["status"] = all_subscription_df["status"].str.replace(
        "SubscriptionState.", "", regex=True
    )
    all_subscription_df["new_existing"] = np.where(
        (all_subscription_df["approved_from"] >= financial_year_start)
        & (all_subscription_df["approved_from"] < financial_year_end),
        "New",
        "Existing",
    )

    subscription_pivot = all_subscription_df.pivot_table(
        index=["core_project", "new_existing", "status", "abolished"],
        values=["subscription_id"],
        aggfunc=np.count_nonzero,
    )

    # Get service data
    core_subscriptions = (
        all_subscription_df[
            (all_subscription_df["core_project"] == "Core")
            & (all_subscription_df["latest_usage"] > financial_year_start)
        ]["subscription_id"]
        .unique()
        .tolist()
    )

    project_subscriptions = (
        all_subscription_df[
            (all_subscription_df["core_project"] == "Project")
            & (all_subscription_df["latest_usage"] > financial_year_start)
        ]["subscription_id"]
        .unique()
        .tolist()
    )
    core_consumed_service_data = [
        ConsumedServiceData(**i)
        for i in await get_consumed_service_data(
            core_subscriptions,
            financial_year_start,
            financial_year_end,
            raise_404=False,
        )
    ]
    project_consumed_service_data = [
        ConsumedServiceData(**i)
        for i in await get_consumed_service_data(
            project_subscriptions,
            financial_year_start,
            financial_year_end,
            raise_404=False,
        )
    ]
    ccsd_df = await convert_to_pd_df(core_consumed_service_data)
    pcsd_df = await convert_to_pd_df(project_consumed_service_data)
    ccsd_df["ConsumedService"] = ccsd_df["consumed_service"].str.upper()
    ccsd_df["ConsumedService"].fillna("Unknown", inplace=True)
    ccsd_df_grouped = (
        ccsd_df.groupby(["ConsumedService"]).sum(numeric_only=True).reset_index()
    )
    ccsd_df_grouped["ConsumedService"] = ccsd_df_grouped["ConsumedService"].str.replace(
        "MICROSOFT.", "", regex=True
    )
    ccsd_df_grouped["ConsumedService"] = ccsd_df_grouped["ConsumedService"].str.lower()

    pcsd_df["ConsumedService"] = pcsd_df["consumed_service"].str.upper()
    pcsd_df["ConsumedService"].fillna("Unknown", inplace=True)
    pcsd_dff_grouped = (
        pcsd_df.groupby(["ConsumedService"]).sum(numeric_only=True).reset_index()
    )
    pcsd_dff_grouped["ConsumedService"] = pcsd_dff_grouped[
        "ConsumedService"
    ].str.replace("MICROSOFT.", "", regex=True)
    pcsd_dff_grouped["ConsumedService"] = pcsd_dff_grouped[
        "ConsumedService"
    ].str.lower()

    # Create doughnut plots of consumed services for core and project
    hovertemp = "<b>%{label}</b><br>Total cost: £%{value:,.0f}<br>Amortised cost: £%{customdata[0]:,.0f}"
    core_fig = px.pie(
        ccsd_df_grouped, names="ConsumedService", values="total_cost", hole=0.3
    )
    project_fig = px.pie(
        pcsd_dff_grouped, names="ConsumedService", values="total_cost", hole=0.3
    )
    for fig in [core_fig, project_fig]:
        fig.update_traces(
            textposition="inside", textinfo="label+percent", showlegend=False
        )
        fig.update_layout(
            hoverlabel=dict(bgcolor="rgba(0, 0, 0, 0.1)", font_size=16),
            hovermode="closest",
            width=700,
            height=700,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )

    core_fig.update_traces(
        hovertemplate=hovertemp, customdata=ccsd_df_grouped["amortised_cost"]
    )
    core_fig.add_annotation(
        x=0.5, y=0.5, text="Core", showarrow=False, font=dict(size=20)
    )
    project_fig.add_annotation(
        x=0.5, y=0.5, text="Project", showarrow=False, font=dict(size=20)
    )
    project_fig.update_traces(
        hovertemplate=hovertemp, customdata=pcsd_dff_grouped["amortised_cost"]
    )

    # forecast plot core
    core_dfs = []
    for sub_id in core_subscriptions:
        usage_daily_total = [
            UsageDailyTotal(**i)
            for i in await get_daily_usage_total(
                sub_id, datetime.date(2015, 4, 6), raise_404=False
            )
        ]
        usage_df = await convert_to_pd_df(usage_daily_total)
        core_dfs.append(usage_df)
    combined_core_df = (
        pd.concat(core_dfs).groupby("date")["total_cost"].sum().reset_index()
    )
    combined_core_df["ds"] = combined_core_df["date"]
    combined_core_df["y"] = combined_core_df["total_cost"]
    combined_core_df = combined_core_df[["ds", "y"]]
    forecased_core_df = forecast_usage(combined_core_df, financial_year_start)
    combined_core_df["date"] = combined_core_df["ds"]
    combined_core_df["total_cost"] = combined_core_df["y"]
    combined_core_df["DTYPE"] = "Actual"
    combined_core_df = combined_core_df[["date", "total_cost", "DTYPE"]]
    combined_core_df = combined_core_df[
        (combined_core_df["date"] >= financial_year_start)
        & (combined_core_df["date"] < financial_year_end)
    ]
    core_usage_forecast_df = pd.concat([combined_core_df, forecased_core_df])
    core_usage_forecast_df["cumulative_total_cost"] = core_usage_forecast_df[
        "total_cost"
    ].cumsum()
    core_forecast_fig = px.area(
        core_usage_forecast_df,
        x="date",
        y="cumulative_total_cost",
        title="",
        color="DTYPE",
        color_discrete_map={"Actual": "blue", "Forecast": "green"},
        width=800,
        height=600,
        labels={
            "date": "Date",
            "cumulative_total_cost": "Cumulative Total Cost (£)",
            "DTYPE": "Data",
        },
    )
    core_forecast_fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # Plot monthly usage with forecast
    core_usage_forecast_df["date"] = pd.to_datetime(core_usage_forecast_df["date"])
    cufd_grouped = (
        core_usage_forecast_df.groupby(core_usage_forecast_df["date"].dt.to_period("M"))
        .agg({"total_cost": "sum"})
        .reset_index()
    )
    cufd_grouped["DTYPE"] = np.where(
        cufd_grouped["date"].dt.to_timestamp() >= datetime.datetime.now(),
        "Forecast",
        "Actual",
    )
    cufd_grouped["Month-Year"] = cufd_grouped["date"].dt.strftime("%b-%Y")
    cufd_grouped.sort_values("date", inplace=True)
    core_monthly_plot = px.bar(
        cufd_grouped,
        x="Month-Year",
        y="total_cost",
        title="",
        color="DTYPE",
        color_discrete_map={"Actual": "blue", "Forecast": "green"},
        opacity=0.6,
        width=800,
        height=600,
        labels={
            "Month-Year": "Month Year",
            "cumulative_total_cost": "Total Cost (£)",
            "DTYPE": "Data",
        },
    )
    core_monthly_plot.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # forecast plot project
    project_dfs = []
    for sub_id in project_subscriptions:
        usage_daily_total = [
            UsageDailyTotal(**i)
            for i in await get_daily_usage_total(
                sub_id, datetime.date(2015, 4, 6), raise_404=False
            )
        ]
        usage_df = await convert_to_pd_df(usage_daily_total)
        project_dfs.append(usage_df)
    combined_project_df = (
        pd.concat(project_dfs).groupby("date")["total_cost"].sum().reset_index()
    )
    combined_project_df["ds"] = combined_project_df["date"]
    combined_project_df["y"] = combined_project_df["total_cost"]
    combined_project_df = combined_project_df[["ds", "y"]]
    forecased_project_df = forecast_usage(combined_project_df, financial_year_start)
    combined_project_df["date"] = combined_project_df["ds"]
    combined_project_df["total_cost"] = combined_project_df["y"]
    combined_project_df["DTYPE"] = "Actual"
    combined_project_df = combined_project_df[["date", "total_cost", "DTYPE"]]
    combined_project_df = combined_project_df[
        (combined_project_df["date"] >= financial_year_start)
        & (combined_project_df["date"] < financial_year_end)
    ]
    project_usage_forecast_df = pd.concat([combined_project_df, forecased_project_df])
    project_usage_forecast_df["cumulative_total_cost"] = project_usage_forecast_df[
        "total_cost"
    ].cumsum()
    project_forecast_fig = px.area(
        project_usage_forecast_df,
        x="date",
        y="cumulative_total_cost",
        title="",
        color="DTYPE",
        color_discrete_map={"Actual": "blue", "Forecast": "green"},
        width=800,
        height=600,
        labels={
            "date": "Date",
            "cumulative_total_cost": "Cumulative Total Cost (£)",
            "DTYPE": "Data",
        },
    )
    project_forecast_fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # Plot monthly usage with forecast
    project_usage_forecast_df["date"] = pd.to_datetime(
        project_usage_forecast_df["date"]
    )
    pufd_grouped = (
        project_usage_forecast_df.groupby(
            project_usage_forecast_df["date"].dt.to_period("M")
        )
        .agg({"total_cost": "sum"})
        .reset_index()
    )
    pufd_grouped["DTYPE"] = np.where(
        pufd_grouped["date"].dt.to_timestamp() >= datetime.datetime.now(),
        "Forecast",
        "Actual",
    )
    pufd_grouped["Month-Year"] = pufd_grouped["date"].dt.strftime("%b-%Y")
    pufd_grouped.sort_values("date", inplace=True)
    project_monthly_plot = px.bar(
        pufd_grouped,
        x="Month-Year",
        y="total_cost",
        title="",
        color="DTYPE",
        color_discrete_map={"Actual": "blue", "Forecast": "green"},
        opacity=0.6,
        width=800,
        height=600,
        labels={
            "Month-Year": "Month Year",
            "cumulative_total_cost": "Total Cost (£)",
            "DTYPE": "Data",
        },
    )
    project_monthly_plot.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return templates.TemplateResponse(
        "azure_report.html",
        {
            "request": request,
            "is_admin": access_to_span(access_status.is_admin),
            "version": __version__,
            "financial_year": financial_year,
            "current_year": datetime.datetime.now().year,
            "report_pivot": report_pivot,
            "subscription_pivot": subscription_pivot,
            "core_fig": core_fig.to_html(full_html=False, include_plotlyjs="cdn"),
            "project_fig": project_fig.to_html(full_html=False, include_plotlyjs="cdn"),
            "forecast_core_fig": core_forecast_fig.to_html(
                full_html=False, include_plotlyjs="cdn"
            ),
            "forecast_project_fig": project_forecast_fig.to_html(
                full_html=False, include_plotlyjs="cdn"
            ),
            "core_monthly_fig": core_monthly_plot.to_html(
                full_html=False, include_plotlyjs="cdn"
            ),
            "project_monthly_fig": project_monthly_plot.to_html(
                full_html=False, include_plotlyjs="cdn"
            ),
        },
    )


@router.get("/azreport")
async def azure_report_form(
    request: Request,
    user: UserIdentityToken = Depends(user_authenticated_no_error),
) -> _TemplateResponse:
    # check user is an admin to display the report
    if not user:
        return templates.TemplateResponse("index.html", {"request": request})

    # Check the users access status
    access_status = await check_user_access(
        user.oid, raise_http_exception=False
    )  # pylint: disable=unexpected-keyword-arg

    if not access_status.is_admin:
        return templates.TemplateResponse("index.html", {"request": request})

    return templates.TemplateResponse(
        "azreport.html",
        {
            "request": request,
            "is_admin": access_to_span(access_status.is_admin),
            "version": __version__,
            "current_year": datetime.datetime.now().year,
        },
    )


def plot_subscription_usage_forecast(
    usage: pd.DataFrame, approvals: pd.DataFrame
) -> px:
    fig = px.area(
        usage,
        x="date",
        y="cumulative_total_cost",
        title="",
        color="DTYPE",
        color_discrete_map={"Actual": "blue", "Forecast": "green"},
        width=1200,
        height=900,
        labels={
            "date": "Date",
            "cumulative_total_cost": "Cumulative Total Cost (£)",
            "DTYPE": "Data",
        },
    )
    for i in range(len(fig["data"])):
        fig["data"][i]["line"]["width"] = 0
    for index, row in approvals.iterrows():
        fig.add_shape(
            dict(
                type="rect",
                x0=row["date_from"],
                x1=row["date_to"],
                y0=0,
                y1=row["cumulative_approval_amount"],
                fillcolor="rgba(0, 0, 0, 0)",
                line=dict(color="rgba(255, 0, 0, 0.6)", width=3),
            )
        )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)")
    usage_fig = fig.to_html(full_html=False, include_plotlyjs="cdn").replace(
        "<div>", '<div class="usageFigure">'
    )
    return usage_fig


def forecast_usage(df: pd.DataFrame, financial_year_start: datetime) -> pd.DataFrame:
    """Forecast usage data up until the end of the financial year."""
    financial_year_end = datetime.datetime(financial_year_start.year + 1, 4, 1)
    future_dates = pd.date_range(
        df["ds"].max() + datetime.timedelta(days=1), financial_year_end
    )
    df["cap"] = 10000
    df["floor"] = 0
    model = Prophet(growth="logistic")
    model.fit(df)
    future = model.make_future_dataframe(len(future_dates))
    future["cap"] = 10000
    future["floor"] = 0
    forecast = model.predict(future)
    forecast["total_cost"] = forecast["yhat"]
    forecast = forecast[forecast["ds"] > pd.to_datetime(df["ds"].max())]
    forecast["DTYPE"] = "Forecast"
    forecast["date"] = forecast["ds"].dt.date
    return forecast[["date", "total_cost", "DTYPE"]]
