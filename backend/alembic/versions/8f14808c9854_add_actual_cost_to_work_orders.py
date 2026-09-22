"""add actual_cost to work_orders

Revision ID: 8f14808c9854
Revises: 0001_baseline
Create Date: 2026-09-23 01:06:13.376347

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f14808c9854'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actual_cost', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.drop_column('actual_cost')
