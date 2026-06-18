"""Initial schema: bookings table.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("meeting_type", sa.Text(), nullable=False, server_default="discovery"),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("time", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="confirmed"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_date", "bookings", ["date"])
    op.create_index("ix_bookings_email", "bookings", ["email"])
    op.create_index("ix_bookings_status", "bookings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_email", table_name="bookings")
    op.drop_index("ix_bookings_date", table_name="bookings")
    op.drop_table("bookings")
