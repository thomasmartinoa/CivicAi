"""add the citation join key and headers to retrieved_chunks

Revision ID: e56cafd34161
Revises: 3824041ecdd1
Create Date: 2026-09-27 18:31:00.149048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e56cafd34161'
down_revision: Union[str, Sequence[str], None] = '3824041ecdd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('retrieved_chunks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('document_chunk_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('headers', sa.JSON(), nullable=True))
        batch_op.create_index(batch_op.f('ix_retrieved_chunks_document_chunk_id'), ['document_chunk_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_retrieved_chunks_document_chunk_id', 'document_chunks',
            ['document_chunk_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('retrieved_chunks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_retrieved_chunks_document_chunk_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_retrieved_chunks_document_chunk_id'))
        batch_op.drop_column('headers')
        batch_op.drop_column('document_chunk_id')
