"""persist the routing justification

Revision ID: 196fc6710719
Revises: e56cafd34161
Create Date: 2026-09-29 12:39:50.039621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '196fc6710719'
down_revision: Union[str, Sequence[str], None] = 'e56cafd34161'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.add_column(sa.Column('routing_justification', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('complaints', schema=None) as batch_op:
        batch_op.drop_column('routing_justification')
