"""add docling parsing to documents and create document_pages table

Revision ID: 004_add_docling_parsing
Revises: 003_create_documents_table
Create Date: 2026-11-06 19:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = '004_add_docling_parsing'
down_revision: Union[str, None] = '003_create_documents_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add parsing columns to documents table
    op.add_column('documents', sa.Column('parse_status', sa.String(length=20), nullable=True))
    op.add_column('documents', sa.Column('parse_error', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('parser_name', sa.String(length=64), nullable=True))
    op.add_column('documents', sa.Column('parser_version', sa.String(length=64), nullable=True))
    op.add_column('documents', sa.Column('parse_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('documents', sa.Column('parse_finished_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('documents', sa.Column('pages_parsed', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('documents', sa.Column('parse_options', JSONB(), nullable=True))

    op.create_index(
        'ix_documents_parse_status',
        'documents',
        ['parse_status']
    )

    # 2. Create document_pages table
    op.create_table(
        'document_pages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_no', sa.Integer(), nullable=False),
        sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('plain_text', sa.Text(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('has_table', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('has_figure', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('ocr_used', sa.Boolean(), nullable=True),
        sa.Column('warnings', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('document_id', 'page_no', name='uq_document_pages_document_id_page_no')
    )

    op.create_index(
        'ix_document_pages_document_id_page_no',
        'document_pages',
        ['document_id', 'page_no']
    )


def downgrade() -> None:
    op.drop_index('ix_document_pages_document_id_page_no', table_name='document_pages')
    op.drop_table('document_pages')

    op.drop_index('ix_documents_parse_status', table_name='documents')
    op.drop_column('documents', 'parse_options')
    op.drop_column('documents', 'pages_parsed')
    op.drop_column('documents', 'parse_finished_at')
    op.drop_column('documents', 'parse_started_at')
    op.drop_column('documents', 'parser_version')
    op.drop_column('documents', 'parser_name')
    op.drop_column('documents', 'parse_error')
    op.drop_column('documents', 'parse_status')

