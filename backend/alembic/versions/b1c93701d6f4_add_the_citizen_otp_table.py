"""add the citizen otp table

Revision ID: b1c93701d6f4
Revises: 196fc6710719
Create Date: 2026-10-05 15:07:35.067340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c93701d6f4'
down_revision: Union[str, Sequence[str], None] = '196fc6710719'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('citizen_otps',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('code_hash', sa.String(length=255), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('citizen_otps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_citizen_otps_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_citizen_otps_email'), ['email'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('citizen_otps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_citizen_otps_email'))
        batch_op.drop_index(batch_op.f('ix_citizen_otps_created_at'))

    op.drop_table('citizen_otps')