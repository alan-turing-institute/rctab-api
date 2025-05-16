# pylint: disable=invalid-name
"""${message if message.endswith(".") else message + "."}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade the database."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade the database."""
    ${downgrades if downgrades else "pass"}
