"""Background tasks that run daily."""
import contextlib
import logging
from asyncio import sleep
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Final, List, Optional, Type
from uuid import UUID

import numpy as np
import pandas as pd
import plotly.express as px
from prophet import Prophet
from sqlalchemy import create_engine, desc, insert, select
from statsmodels.tsa.arima.model import ARIMA

from rctab.constants import ADMIN_OID, EMAIL_TYPE_SUMMARY
from rctab.crud.accounting_models import emails, failed_emails
from rctab.crud.models import database
from rctab.crud.schema import (
    ApprovalListItem,
    CostRecovery,
    FinanceWithCostRecovery,
    SubscriptionDetails,
    UsageDailyTotal,
)
from rctab.routers.accounting.abolishment import abolish_subscriptions
from rctab.routers.accounting.routes import (
    get_approvals,
    get_costrecovery,
    get_daily_usage_total,
    get_finance_costs_recovered,
    get_subscriptions_with_disable,
)
from rctab.routers.accounting.send_emails import (
    MissingEmailParamsError,
    prepare_summary_email,
    send_with_sendgrid,
)
from rctab.settings import get_settings

logger = logging.getLogger(__name__)
pd.options.mode.chained_assignment = None  # default='warn'

DESIRED_RUNTIME: Final = "16:00:00"


class FileLockContextManager(contextlib.AbstractContextManager):
    """Create a file on enter and remove that file on exit.

    Will raise an error on enter if the file already exists.
    """

    def __init__(self, filename: str) -> None:
        """Initialise the context manager.

        Args:
            filename: Path of the file that will be created.
        """
        self.filename = filename
        self.lock_file = Path(self.filename)

    def __enter__(self) -> None:
        """Try to create the lock file and raise if it already exists."""
        self.lock_file.touch(exist_ok=False)  # raises error if file exists

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Remove the lock file on exit."""
        logger.warning("Deleting lock file")
        self.lock_file.unlink()


def datetime_utcnow() -> datetime:
    """Returns the current date and time in the UTC timezone.

    Returns:
        The current UTC date and time.
    """
    # This can be patched for testing more easily than datetime

    return datetime.now(timezone.utc)


def calc_how_long_to_sleep_for(desired_runtime: str) -> float:
    """Work out how long to sleep for to wake at the desired time.

    Args:
        desired_runtime: Desired wake time, such as "13:00:00".

    Returns:
        Seconds until daily task has to be performed.
    """
    # make sure all timestamps are UTC
    right_now = datetime_utcnow()
    date_today = right_now.strftime("%d/%m/%Y")
    sleep_until = datetime.strptime(
        f"{date_today} {desired_runtime}", "%d/%m/%Y %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    if sleep_until < right_now:
        sleep_until += timedelta(days=1)
    seconds_to_sleep = (sleep_until - right_now).total_seconds()
    seconds_to_sleep = max(seconds_to_sleep, 1)
    logger.info("Sleep for %s seconds until routine tasks", seconds_to_sleep)
    return seconds_to_sleep


async def send_summary_email(
    recipients: List[str], since_this_datetime: Optional[datetime] = None
) -> None:
    """Sends a summary email to the addresses in the recipients list.

    The summary email contains information about:
    - new subscriptions
    - status changes of subscriptions
    - notification emails sent
    within from the `since_this_datetime` until now.

    Items in the jinja2 template are replaced with those in template_data.

    Args:
        recipients : The email addresses to send summary emails to.
        since_this_datetime : Include information since this date and time, by default None.
    """
    # pylint: disable=invalid-name
    template_name = "daily_summary.html"
    template_data = await prepare_summary_email(database, since_this_datetime)
    subject = "Daily summary"
    if recipients:
        try:
            status = send_with_sendgrid(
                subject,
                template_name,
                template_data,
                recipients,
            )
            insert_statement = insert(emails).values(
                {
                    "status": status,
                    "type": EMAIL_TYPE_SUMMARY,
                    "recipients": ";".join(recipients),
                }
            )
            await database.execute(insert_statement)
            logger.info(
                "Status code summary email: %s",
                status,
            )
        except MissingEmailParamsError as error:
            insert_statement = (
                insert(failed_emails)
                .values(
                    {
                        "subscription_id": UUID(int=0),
                        "type": subject,
                        "subject": error.subject,
                        "recipients": ";".join(error.recipients),
                        "from_email": error.from_email,
                        "message": error.message,
                    }
                )
                .returning(failed_emails.c.id)
            )
            row = await database.execute(insert_statement)
            logger.error(
                "'%s' email failed to send due to missing "
                "api_key or send email address.\n"
                "It has been logged in the 'failed_emails' table with id=%s.\n"
                "Use 'get_failed_emails.py' to retrieve it to send manually.",
                subject,
                row,
            )

    else:
        logger.error("Missing summary email recipient.")


async def routine_tasks() -> None:
    """An infinite loop to run routine tasks such as sending summary emails."""
    # pylint: disable=broad-except
    logger.info("Starting routine background tasks %s", datetime_utcnow())
    # print("running forecast upload")
    # engine = create_engine(str(database.url))
    # forecast_df_summary, forecast_df_full = await get_all_subscription_data()
    # forecast_df_summary.to_sql("subscription_usage_forecast_summary", engine, schema = "accounting", if_exists="replace", index=False)
    # forecast_df_full.to_sql("subscription_usage_forecast", engine, schema = "accounting", if_exists="replace", index=False)
    # print("finished forecast upload")
    try:
        # Create a .lock file to make sure only one worker is running routine tasks
        with FileLockContextManager("routine_tasks.lock"):
            # Catch a wide array of Exceptions so that we can log them immediately
            # rather than them being printed at server shutdown.
            try:
                while True:
                    needs_to_send = True
                    recipients = get_settings().admin_email_recipients
                    time_last_summary_email = await get_timestamp_last_summary_email()
                    if not recipients:
                        # We should not send a summary email if we are testing
                        # as there are issues with the databases library
                        # that prohibit us from using the same databases object
                        # in multiple async tasks if force_rollback == True
                        # (see, amongst others, https://github.com/encode/databases/issues/456)
                        needs_to_send = False
                        logger.warning("No recipients for summary email found")

                    elif (
                        time_last_summary_email
                        and time_last_summary_email.date() == datetime_utcnow().date()
                    ):
                        needs_to_send = False
                        logger.info("No need to send another summary email today")

                    # Check whether it's time to run the background tasks
                    right_now = datetime_utcnow()
                    date_today = right_now.strftime("%d/%m/%Y")
                    scheduled_time = datetime.strptime(
                        f"{date_today} {DESIRED_RUNTIME}", "%d/%m/%Y %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    if scheduled_time <= right_now:
                        logger.info("Time to run background tasks")
                        await abolish_subscriptions(UUID(ADMIN_OID))
                        if needs_to_send:
                            await send_summary_email(
                                recipients, time_last_summary_email
                            )
                    else:
                        logger.info(
                            "Too early for background tasks - sleep until %s UTC",
                            DESIRED_RUNTIME,
                        )
                    # We want to sleep for at least a second to avoid busy waiting
                    seconds_to_sleep = max(
                        1, calc_how_long_to_sleep_for(DESIRED_RUNTIME)
                    )
                    await sleep(seconds_to_sleep)

            except BaseException:
                logger.exception("Exception in routine_tasks")

    except FileExistsError:
        logger.exception("Exiting as we only need one routine tasks thread")


async def get_timestamp_last_summary_email() -> Optional[datetime]:
    """Retrieve the timestamp from the emails table of the most recent summary email sent.

    Returns:
        The timestamp of the last summary email sent.
    """
    query = (
        select([emails])
        .where(emails.c.type == EMAIL_TYPE_SUMMARY)
        .order_by(desc(emails.c.id))
    )
    row = await database.fetch_one(query)
    if row:
        time_last_summary = row["time_created"]
        logger.info("Last summary email was sent at: %s", time_last_summary)
    else:
        time_last_summary = None
        logger.info("There's been no summary email so far.")
    return time_last_summary


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


def forecast_usage(df: pd.DataFrame, financial_year_start: datetime) -> pd.DataFrame:
    """Forecast usage data up until the end of the financial year."""
    financial_year_end = datetime(financial_year_start.year + 1, 4, 1)
    future_dates = pd.date_range(df["ds"].max() + timedelta(days=1), financial_year_end)
    df["cap"] = max(df["y"])
    df["floor"] = 0
    model = Prophet(
        growth="logistic",
        daily_seasonality=False,
        weekly_seasonality=False,
        yearly_seasonality=False,
    )
    model.fit(df)
    future = model.make_future_dataframe(len(future_dates))
    future["cap"] = max(df["y"])
    future["floor"] = 0
    forecast = model.predict(future)
    forecast["total_cost"] = forecast["yhat"]
    forecast = forecast[forecast["ds"] > pd.to_datetime(df["ds"].max())]
    forecast["DTYPE"] = "Forecast"
    forecast["date"] = forecast["ds"].dt.date
    forecast["total_cost"] = np.where(
        forecast["total_cost"] < 0, 0, forecast["total_cost"]
    )
    # assert forecast[forecast["total_cost"] < 0].empty
    return forecast[["date", "total_cost", "DTYPE"]]


def plot_daily_usage_forecast(usage: pd.DataFrame, approvals: pd.DataFrame) -> px:
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


async def forecast_subscription_usage_df(
    subscription_id: UUID,
    usage_object_list: list,
    approvals_object_list: list,
    cost_recovery_object_list: list,
    finance_costs_recovered_object_list: list,
    financial_year_start: datetime.date,
) -> px:
    """Plot usage and approvals."""
    # unpack data into dataframes
    usage_df = await convert_to_pd_df(usage_object_list)
    approvals_df = await convert_to_pd_df(approvals_object_list)
    cr_all_df = await convert_to_pd_df(cost_recovery_object_list)
    cr_df = await convert_to_pd_df(finance_costs_recovered_object_list)

    # create default values for empty dataframes
    ## approvals
    if (
        approvals_df.empty
        or approvals_df[approvals_df["date_to"] >= financial_year_start.date()].empty
    ):
        approval_end_date = None
        total_approved_amount = 0
        fy_approved_amount = 0
        approval_final_spend = 0
    else:
        approval_end_date = pd.Timestamp(approvals_df.tail(1)["date_to"].values[0])
        approvals_df["cumulative_total_approval_amount"] = approvals_df[
            "amount"
        ].cumsum()
        total_approved_amount = approvals_df.tail(1)[
            "cumulative_total_approval_amount"
        ].values[0]
        approvals_df = approvals_df[
            approvals_df["date_to"] >= financial_year_start.date()
        ]
        approvals_df["cumulative_approval_amount"] = approvals_df["amount"].cumsum()
        fy_approved_amount = approvals_df.tail(1)["cumulative_approval_amount"].values[
            0
        ]

    ## usage
    if (
        usage_df.empty
        or len(
            usage_df[usage_df["date"] >= financial_year_start.date()]["subscription_id"]
        )
        < 10
    ):
        fy_spend_to_date = 0
        fy_projected_spend = 0
        approval_final_spend = None
        usage_forecast_data = pd.DataFrame(
            data={
                "subscription_id": [subscription_id],
                "date": [None],
                "total_cost": [0],
                "cumulative_total_cost": [0],
                "DTYPE": [None],
            }
        )
    else:
        usage_df["y"] = usage_df["total_cost"]
        usage_df["ds"] = usage_df["date"]
        model_data = usage_df[["ds", "y"]]
        print(f"forecasting usage for {subscription_id}")
        forecast_usage_data = forecast_usage(model_data, financial_year_start)
        model_data["date"] = model_data["ds"]
        model_data["total_cost"] = model_data["y"]
        model_data["DTYPE"] = "Actual"
        model_data = model_data[["date", "total_cost", "DTYPE"]]
        usage_with_forecast = pd.concat([model_data, forecast_usage_data])
        usage_with_forecast["Financial_year"] = np.where(
            usage_with_forecast["date"] >= financial_year_start.date(),
            "CURRENT",
            "PREVIOUS",
        )
        usage_forecast_data = usage_with_forecast[
            usage_with_forecast["Financial_year"] == "CURRENT"
        ]
        usage_forecast_data["subscription_id"] = subscription_id
        usage_forecast_data["cumulative_total_cost"] = usage_forecast_data[
            "total_cost"
        ].cumsum()
        if approval_end_date in pd.to_datetime(usage_forecast_data["date"]).values:
            approval_final_spend = usage_forecast_data[
                pd.to_datetime(usage_forecast_data["date"]) == approval_end_date
            ]["cumulative_total_cost"].values[0]
        else:
            approval_final_spend = 0

        # usage results
        fy_spend_to_date = (
            usage_forecast_data[usage_forecast_data["DTYPE"] == "Actual"]
            .tail(1)["cumulative_total_cost"]
            .values[0]
        )
        fy_projected_spend = usage_forecast_data.tail(1)[
            "cumulative_total_cost"
        ].values[0]

    ## cost recovery with finance
    if cr_all_df.empty:
        costs_recovered_fy = 0
    else:
        costs_recovered_fy = cr_all_df[
            cr_all_df["month"]
            >= datetime(financial_year_start.year, financial_year_start.month, 1).date()
        ]["amount"].sum()

    ## cost recovery
    if cr_df.empty:
        current_fy_finance = 0
    else:
        current_fy_finance = cr_df[cr_df["date_to"] > financial_year_start.date()][
            "amount"
        ].sum()

    # Create reports dataframe
    report_df = pd.DataFrame(
        data={
            "subscription_id": [subscription_id],
            "approval_end_date": [approval_end_date],
            "total_approved_amount": [total_approved_amount],
            "fy_approved_amount": [fy_approved_amount],
            "approval_end_date_projected_spend": [approval_final_spend],
            "fy_end_date": [datetime(financial_year_start.year + 1, 4, 1)],
            "fy_spend_to_date": [fy_spend_to_date],
            "fy_projected_spend": [fy_projected_spend],
            "costs_recovered_fy": [costs_recovered_fy],
            "current_fy_finance": [current_fy_finance],
            "datetime_data_updated": [datetime.now()],
        }
    )
    report_df["fy_projected_dif"] = (
        report_df["fy_projected_spend"] - report_df["fy_approved_amount"]
    )
    report_df["fy_predicted_core_spending"] = max(
        0, (report_df["fy_projected_spend"] - report_df["current_fy_finance"])[0]
    )

    # forecast data platform
    usage_forecast_data["datetime_data_updated"] = datetime.now()
    return report_df, usage_forecast_data


async def get_subscription_data(subscription_id: UUID) -> pd.DataFrame:
    """Get the subscription data for reporting."""
    logger.info("Getting reports data for subscription %s", subscription_id)
    all_approvals = [
        ApprovalListItem(**i)
        for i in await get_approvals(
            subscription_id, raise_404=False
        )  # pylint: disable=unexpected-keyword-arg
    ]

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

    # Get usage data for the current financial year
    today = datetime.now()
    today_last_year = datetime(today.year - 1, today.month, 1)
    financial_year_start = datetime(today.year, 4, 6)
    if today.month < 4:
        financial_year_start = datetime(today.year - 1, 4, 6)

    usage_daily_total = [
        UsageDailyTotal(**i)
        for i in await get_daily_usage_total(
            subscription_id, today_last_year, raise_404=False
        )
    ]
    forecast_summary, forecast_df = await forecast_subscription_usage_df(
        subscription_id,
        usage_daily_total,
        all_approvals,
        all_costrecovery,
        all_finance_with_costs_recovered,
        financial_year_start,
    )
    return forecast_summary, forecast_df


async def get_all_subscription_data() -> pd.DataFrame:
    """Get report data for all subscriptions."""
    all_subscription_data = [
        SubscriptionDetails(**i)
        for i in await get_subscriptions_with_disable(raise_404=False)
    ]

    forecast_data = [
        await get_subscription_data(subcription_object.subscription_id)
        for subcription_object in all_subscription_data
    ]
    forecast_df_summary = pd.concat([fd[0] for fd in forecast_data])
    forecast_df_full = pd.concat([fd[1] for fd in forecast_data])
    return forecast_df_summary, forecast_df_full
