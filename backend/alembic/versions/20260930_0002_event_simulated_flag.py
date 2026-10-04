"""events.is_simulated — marks events produced from simulated demo feeds

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("is_simulated", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("events", "is_simulated")
