"""Drop legacy max_min/max_max columns from parameter health config.

Revision ID: 20260413_0002
Revises: 20260413_0001
Create Date: 2026-04-13
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260413_0002"
down_revision: Union[str, tuple[str, str], None] = "20260413_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("parameter_health_config")}

    if "max_max" in columns:
        op.drop_column("parameter_health_config", "max_max")
    if "max_min" in columns:
        op.drop_column("parameter_health_config", "max_min")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("parameter_health_config")}

    if "max_min" not in columns:
        op.add_column("parameter_health_config", sa.Column("max_min", sa.Float(), nullable=True))
    if "max_max" not in columns:
        op.add_column("parameter_health_config", sa.Column("max_max", sa.Float(), nullable=True))
