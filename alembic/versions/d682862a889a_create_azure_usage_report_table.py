"""create azure usage report table

Revision ID: d682862a889a
Revises: b65796c99771
Create Date: 2023-11-13 16:49:20.596570

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "d682862a889a"
down_revision = "b65796c99771"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_usage_forecast_summary",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("approval_end_date", sa.DateTime, nullable=False),
        sa.Column("total_approved_amount", sa.Float, nullable=False),
        sa.Column("fy_approved_amount", sa.Float, nullable=False),
        sa.Column("approval_end_date_projected_spend", sa.Float, nullable=True),
        sa.Column("fy_end_date", sa.DateTime, nullable=False),
        sa.Column("fy_spend_to_date", sa.Float, nullable=False),
        sa.Column("fy_projected_spend", sa.Float, nullable=False),
        sa.Column("costs_recovered_fy", sa.Float, nullable=False),
        sa.Column("current_fy_finance", sa.Float, nullable=False),
        sa.Column("fy_projected_dif", sa.Float, nullable=False),
        sa.Column("fy_predicted_core_spending", sa.Float, nullable=False),
        sa.Column("datetime_data_updated", sa.DateTime, nullable=False),
        schema="accounting",
    )
    op.create_table(
        "subscription_usage_forecast",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(), nullable=False),
        sa.Column("date", sa.DateTime, nullable=True),
        sa.Column("total_cost", sa.Float, nullable=False),
        sa.Column("cumulative_total_cost", sa.Float, nullable=False),
        sa.Column("DTYPE", sa.String, nullable=True),
        sa.Column("datetime_data_updated", sa.DateTime, nullable=False),
        schema="accounting",
    )


def downgrade():
    op.drop_table("subscription_usage_forecast_summary", schema="accounting")
    op.drop_table("subscription_usage_forecast", schema="accounting")
