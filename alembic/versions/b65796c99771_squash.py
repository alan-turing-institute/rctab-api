"""Squash

Revision ID: b65796c99771
Revises:
Create Date: 2023-07-06 22:17:36.160486

"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "b65796c99771"
down_revision = None
branch_labels = None
depends_on = None


class FinanceHistorySql:
    """Trigger and function for finance history table."""

    CREATE_TRIGGER = (
        "CREATE TRIGGER FINANCE_HISTORY "
        "AFTER delete OR update ON {schema}.finance "
        "FOR EACH ROW "
        "EXECUTE FUNCTION {schema}.finance_changed();"
    )

    DROP_TRIGGER = "DROP TRIGGER FINANCE_HISTORY ON {schema}.finance;"

    CREATE_FUNCTION = (
        "CREATE FUNCTION {schema}.finance_changed() "
        "RETURNS TRIGGER AS "
        "$trigger_save_changed$"
        "BEGIN "
        "  insert into {schema}.finance_history ("
        "    id,"
        "    subscription_id,"
        "    date_from,"
        "    date_to,"
        "    amount,"
        "    ticket,"
        "    priority,"
        "    finance_code,"
        "    admin,"
        "    time_created"
        "  ) values ("
        "    OLD.id,"
        "    OLD.subscription_id,"
        "    OLD.date_from,"
        "    OLD.date_to,"
        "    OLD.amount,"
        "    OLD.ticket,"
        "    OLD.priority,"
        "    OLD.finance_code,"
        "    OLD.admin,"
        "    OLD.time_created"
        "  );"
        "  RETURN NULL; "
        "END; "
        "$trigger_save_changed$ "
        "LANGUAGE 'plpgsql';"
    )
    DROP_FUNCTION = "DROP FUNCTION {schema}.finance_changed();"


def upgrade():
    op.execute(text("create schema accounting"))
    op.create_table(
        "user_cache",
        sa.Column("oid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cache", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("oid"),
    )
    op.create_table(
        "user_rbac",
        sa.Column("oid", postgresql.UUID(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("has_access", sa.Boolean(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("oid"),
    )
    op.create_table(
        "cost_recovery_log",
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        schema="accounting",
    )
    op.create_table(
        "subscription",
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "abolished", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.PrimaryKeyConstraint("subscription_id"),
        schema="accounting",
    )
    op.create_table(
        "allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column("ticket", sa.String(), nullable=True),
        sa.Column("amount", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("currency", postgresql.ENUM("GBP", name="currency"), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column("ticket", sa.String(), nullable=True),
        sa.Column("amount", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("currency", postgresql.ENUM("GBP", name="currency"), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "costmanagement",
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("start_datetime", sa.Date(), nullable=False),
        sa.Column("end_datetime", sa.Date(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("billing_currency", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("subscription_id"),
        schema="accounting",
    )
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("recipients", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_info", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "failed_emails",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("from_email", sa.String(), nullable=True),
        sa.Column("recipients", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "finance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("amount", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("ticket", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("finance_code", sa.String(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "finance_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("amount", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("ticket", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("finance_code", sa.String(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column("time_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_deleted",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        schema="accounting",
    )
    op.execute(FinanceHistorySql.CREATE_FUNCTION.format(schema="accounting"))
    op.execute(FinanceHistorySql.CREATE_TRIGGER.format(schema="accounting"))
    op.create_table(
        "persistence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "always_on", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reason",
            postgresql.ENUM(
                "OVER_BUDGET",
                "EXPIRED",
                "OVER_BUDGET_AND_EXPIRED",
                name="billingstatus",
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "subscription_details",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column(
            "role_assignments", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.create_table(
        "usage",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("billing_account_id", sa.String(), nullable=True),
        sa.Column("billing_account_name", sa.String(), nullable=True),
        sa.Column("billing_period_start_date", sa.Date(), nullable=True),
        sa.Column("billing_period_end_date", sa.Date(), nullable=True),
        sa.Column("billing_profile_id", sa.String(), nullable=True),
        sa.Column("billing_profile_name", sa.String(), nullable=True),
        sa.Column("account_owner_id", sa.String(), nullable=True),
        sa.Column("account_name", sa.String(), nullable=True),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("subscription_name", sa.String(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("product", sa.String(), nullable=True),
        sa.Column("part_number", sa.String(), nullable=True),
        sa.Column("meter_id", sa.String(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("effective_price", sa.Float(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("amortised_cost", sa.Float(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("billing_currency", sa.String(), nullable=True),
        sa.Column("resource_location", sa.String(), nullable=True),
        sa.Column("consumed_service", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("resource_name", sa.String(), nullable=True),
        sa.Column("service_info1", sa.String(), nullable=True),
        sa.Column("service_info2", sa.String(), nullable=True),
        sa.Column("additional_info", sa.String(), nullable=True),
        sa.Column("invoice_section", sa.String(), nullable=False),
        sa.Column("cost_center", sa.String(), nullable=True),
        sa.Column("resource_group", sa.String(), nullable=True),
        sa.Column("reservation_id", sa.String(), nullable=True),
        sa.Column("reservation_name", sa.String(), nullable=True),
        sa.Column("product_order_id", sa.String(), nullable=True),
        sa.Column("offer_id", sa.String(), nullable=True),
        sa.Column("is_azure_credit_eligible", sa.Boolean(), nullable=True),
        sa.Column("term", sa.String(), nullable=True),
        sa.Column("publisher_name", sa.String(), nullable=True),
        sa.Column("publisher_type", sa.String(), nullable=True),
        sa.Column("plan_name", sa.String(), nullable=True),
        sa.Column("charge_type", sa.String(), nullable=True),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column("monthly_upload", sa.Date(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )
    op.execute(
        "CREATE MATERIALIZED VIEW {schema}.usage_view AS "
        "SELECT subscription_id, "
        "    MIN(date) AS first_usage, "
        "    MAX(date) AS latest_usage, "
        "    COALESCE(SUM(cost), 0.0) AS cost, "
        "    COALESCE(SUM(amortised_cost), 0.0) AS amortised_cost, "
        "    SUM(total_cost) as total_cost "
        "FROM {schema}.usage "
        "GROUP BY subscription_id;".format(schema="accounting")
    )
    op.create_table(
        "cost_recovery",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finance_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("finance_code", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("date_recovered", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin", postgresql.UUID(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin"],
            ["user_rbac.oid"],
        ),
        sa.ForeignKeyConstraint(
            ["finance_id"],
            ["accounting.finance.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["accounting.subscription.subscription_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="accounting",
    )


def downgrade():
    op.drop_table("cost_recovery", schema="accounting")
    op.execute(
        "DROP MATERIALIZED VIEW {schema}.usage_view;".format(schema="accounting")
    )
    op.drop_table("usage", schema="accounting")
    op.drop_table("subscription_details", schema="accounting")
    op.drop_table("status", schema="accounting")
    op.drop_table("persistence", schema="accounting")
    op.execute(FinanceHistorySql.DROP_TRIGGER.format(schema="accounting"))
    op.execute(FinanceHistorySql.DROP_FUNCTION.format(schema="accounting"))
    op.drop_table("finance_history", schema="accounting")
    op.drop_table("finance", schema="accounting")
    op.drop_table("failed_emails", schema="accounting")
    op.drop_table("emails", schema="accounting")
    op.drop_table("costmanagement", schema="accounting")
    op.drop_table("approvals", schema="accounting")
    op.drop_table("allocations", schema="accounting")
    op.drop_table("subscription", schema="accounting")
    op.drop_table("cost_recovery_log", schema="accounting")
    op.drop_table("user_rbac")
    op.drop_table("user_cache")
    op.execute("drop type if exists billingstatus")
    op.execute("drop type currency")
    op.execute(text("drop schema accounting"))
