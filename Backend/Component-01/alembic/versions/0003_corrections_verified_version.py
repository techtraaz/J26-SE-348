"""corrections verified version

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # The verified version a correction was confirmed in (M5).
    op.add_column('corrections', sa.Column('verified_version', sa.Integer(), nullable=True))

def downgrade() -> None:
    op.drop_column('corrections', 'verified_version')
