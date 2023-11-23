"""SQLAlchemy models for the accounting schema."""
from databases import Database
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, ENUM, JSONB, UUID
from sqlalchemy.sql import func

from rctab.crud.models import metadata  # database

subscription = Table(
    "subscription",
    metadata,
    Column("subscription_id", UUID(), primary_key=True),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("abolished", Boolean, server_default=false(), nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

persistence = Table(
    "persistence",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column(
        "always_on",
        Boolean,
        server_default=false(),
        nullable=False,
    ),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

status = Table(
    "status",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column(
        "active",
        Boolean,
        server_default=true(),
        nullable=False,
    ),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    Column(
        "reason",
        ENUM(
            "OVER_BUDGET",
            "EXPIRED",
            "OVER_BUDGET_AND_EXPIRED",
            name="billingstatus",
            create_type=True,
        ),
    ),
    schema="accounting",
)

subscription_details = Table(
    "subscription_details",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("display_name", String, nullable=False),
    Column("state", String, nullable=False),
    Column("role_assignments", JSONB),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

approvals = Table(
    "approvals",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("ticket", String),
    Column("amount", DOUBLE_PRECISION, nullable=False),
    Column("currency", ENUM("GBP", name="currency", create_type=False), nullable=False),
    Column(
        "date_from",
        Date,
        nullable=False,
    ),
    Column(
        "date_to",
        Date,
        nullable=False,
    ),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

allocations = Table(
    "allocations",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("ticket", String),
    Column("amount", DOUBLE_PRECISION, nullable=False),
    Column("currency", ENUM("GBP", name="currency", create_type=False), nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

usage = Table(
    "usage",
    metadata,
    Column("id", String(), primary_key=True),
    Column(
        "name",
        String(),
    ),
    Column(
        "type",
        String(),
    ),
    Column(
        "tags",
        JSONB(),
    ),
    Column(
        "billing_account_id",
        String(),
    ),
    Column(
        "billing_account_name",
        String(),
    ),
    Column("billing_period_start_date", Date()),
    Column("billing_period_end_date", Date()),
    Column("billing_profile_id", String()),
    Column("billing_profile_name", String()),
    Column("account_owner_id", String()),
    Column("account_name", String()),
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("subscription_name", String()),
    Column("date", Date(), nullable=False),
    Column("product", String()),
    Column("part_number", String()),
    Column("meter_id", String()),
    Column("quantity", Float()),
    Column("effective_price", Float()),
    Column("cost", Float()),
    Column("amortised_cost", Float()),
    Column("total_cost", Float(), nullable=False),
    Column("unit_price", Float()),
    Column("billing_currency", String()),
    Column("resource_location", String()),
    Column("consumed_service", String()),
    Column("resource_id", String()),
    Column("resource_name", String()),
    Column("service_info1", String()),
    Column("service_info2", String()),
    Column("additional_info", String()),
    Column("invoice_section", String(), nullable=False),
    Column("cost_center", String()),
    Column("resource_group", String()),
    Column("reservation_id", String()),
    Column("reservation_name", String()),
    Column("product_order_id", String()),
    Column("offer_id", String()),
    Column("is_azure_credit_eligible", Boolean()),
    Column("term", String()),
    Column("publisher_name", String()),
    Column("publisher_type", String()),
    Column("plan_name", String()),
    Column("charge_type", String()),
    Column("frequency", String()),
    Column("monthly_upload", Date()),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)


async def refresh_materialised_view(
    database: Database, view: Table, concurrently: bool = False
) -> None:
    """Refresh a materialised view."""
    await database.execute(
        """
        REFRESH MATERIALIZED VIEW {concurrently} {schema}.{view};
        """.format(
            concurrently="CONCURRENTLY" if concurrently else "",
            view=view.name,
            schema=view.schema,
        )
    )


usage_view = Table(
    # Generated with raw SQL rather than SQLAlchemy as it's a materialised view
    "usage_view",
    metadata,
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("first_usage", Date()),
    Column("latest_usage", Date()),
    Column("cost", Float()),
    Column("amortised_cost", Float()),
    Column("total_cost", Float()),
    schema="accounting",
    info={"is_view": True},
)

costmanagement = Table(
    "costmanagement",
    metadata,
    Column(
        "subscription_id",
        UUID(),
        ForeignKey("accounting.subscription.subscription_id"),
        primary_key=True,
    ),
    Column("name", String()),
    Column("start_datetime", Date(), nullable=False),
    Column("end_datetime", Date(), nullable=False),
    Column("cost", Float(), nullable=False),
    Column("billing_currency", String(), nullable=False),
    schema="accounting",
)

emails = Table(
    "emails",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID,
        ForeignKey("accounting.subscription.subscription_id"),
    ),
    Column("status", Integer, nullable=False),
    Column("type", String, nullable=False),
    Column("recipients", String, nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    Column("extra_info", String),
    schema="accounting",
)

failed_emails = Table(
    "failed_emails",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID,
        ForeignKey("accounting.subscription.subscription_id"),
    ),
    Column("type", String, nullable=False),
    Column("subject", String, nullable=False),
    Column("from_email", String, nullable=True),
    Column("recipients", String, nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    Column("message", String, nullable=False),
    schema="accounting",
)

finance = Table(
    "finance",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column(
        "subscription_id",
        UUID,
        ForeignKey("accounting.subscription.subscription_id"),
    ),
    Column("date_from", Date, nullable=False),
    Column("date_to", Date, nullable=False),
    Column("amount", DOUBLE_PRECISION, nullable=False),
    Column("ticket", String, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("finance_code", String, nullable=False),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

# Note: this is populated by a trigger on the finance table.
finance_history = Table(
    "finance_history",
    metadata,
    Column(
        "id", Integer, nullable=False
    ),  # Note that this is the finance.id, not a new PK
    Column(
        "subscription_id",
        UUID,
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("date_from", Date, nullable=False),
    Column("date_to", Date, nullable=False),
    Column("amount", DOUBLE_PRECISION, nullable=False),
    Column("ticket", String, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("finance_code", String, nullable=False),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("time_created", DateTime(timezone=True)),
    Column("time_deleted", DateTime(timezone=True), server_default=func.now()),
    schema="accounting",
)

cost_recovery = Table(
    "cost_recovery",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column("finance_id", Integer, ForeignKey("accounting.finance.id"), nullable=False),
    Column(
        "subscription_id",
        UUID,
        ForeignKey("accounting.subscription.subscription_id"),
        nullable=False,
    ),
    Column("month", Date, nullable=False),
    Column("finance_code", String, nullable=False),
    Column("amount", Float, nullable=False),
    Column("date_recovered", DateTime(timezone=True)),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

cost_recovery_log = Table(
    "cost_recovery_log",
    metadata,
    Column("month", Date, nullable=False),
    Column("admin", UUID, ForeignKey("user_rbac.oid"), nullable=False),
    Column("time_created", DateTime(timezone=True), server_default=func.now()),
    Column("time_updated", DateTime(timezone=True), onupdate=func.now()),
    schema="accounting",
)

subscription_usage_forecast_summary = Table(
    "subscription_usage_forecast_summary",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column("subscription_id", UUID, nullable=False),
    Column("approval_end_date", Date, nullable=False),
    Column("total_approved_amount", Float, nullable=False),
    Column("fy_approved_amount", Float, nullable=False),
    Column("approval_end_date_projected_spend", Float, nullable=True),
    Column("fy_end_date", Date, nullable=False),
    Column("fy_spend_to_date", Float, nullable=False),
    Column("fy_projected_spend", Float, nullable=False),
    Column("costs_recovered_fy", Float, nullable=False),
    Column("current_fy_finance", Float, nullable=False),
    Column("fy_projected_dif", Float, nullable=False),
    Column("fy_predicted_core_spending", Float, nullable=False),
    Column("datetime_data_updated", DateTime(timezone=True), nullable=False),
    schema="accounting",
)

subscription_usage_forecast = Table(
    "subscription_usage_forecast",
    metadata,
    Column("id", Integer, autoincrement=True, primary_key=True),
    Column("subscription_id", UUID, nullable=False),
    Column("date", Date, nullable=True),
    Column("total_cost", Float, nullable=False),
    Column("cumulative_total_cost", Float, nullable=False),
    Column("DTYPE", String, nullable=True),
    Column("datetime_data_updated", DateTime(timezone=True), nullable=False),
    schema="accounting",
)
