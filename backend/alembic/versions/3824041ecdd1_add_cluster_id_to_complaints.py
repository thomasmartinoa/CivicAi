"""add cluster_id to complaints

Revision ID: 3824041ecdd1
Revises: 8f14808c9854
Create Date: 2026-09-27 12:38:13.105946

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3824041ecdd1'
down_revision: Union[str, Sequence[str], None] = '8f14808c9854'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cluster_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_complaints_cluster_id'), ['cluster_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_complaints_cluster_id'))
        batch_op.drop_column('cluster_id')
