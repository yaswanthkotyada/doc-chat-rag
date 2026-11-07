"""add mode_override to documents table

Revision ID: 006_add_document_mode_override
Revises: 005_add_chunks_and_indexing
Create Date: 2026-11-07 13:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_add_document_mode_override'
down_revision: Union[str, None] = '005_add_chunks_and_indexing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('mode_override', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'mode_override')
