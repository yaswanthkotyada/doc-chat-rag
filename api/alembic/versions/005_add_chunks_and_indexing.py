"""add chunks table and document indexing columns

Revision ID: 005_add_chunks_and_indexing
Revises: 004_add_docling_parsing
Create Date: 2026-11-07 11:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '005_add_chunks_and_indexing'
down_revision: Union[str, None] = '004_add_docling_parsing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add indexing columns to documents table
    op.add_column('documents', sa.Column('index_status', sa.String(length=20), nullable=True))
    op.add_column('documents', sa.Column('index_error', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('chunks_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('documents', sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        'ix_documents_index_status',
        'documents',
        ['index_status']
    )

    # 2. Create chunks table
    op.create_table(
        'chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embed_text', sa.Text(), nullable=False),
        sa.Column('page_start', sa.Integer(), nullable=False),
        sa.Column('page_end', sa.Integer(), nullable=False),
        sa.Column('heading_path', JSONB(), nullable=False, server_default='[]'),
        sa.Column('chunk_type', sa.String(length=20), nullable=False, server_default='text'),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('char_start', sa.Integer(), nullable=True),
        sa.Column('char_end', sa.Integer(), nullable=True),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column('tsv', TSVECTOR(), sa.Computed("to_tsvector('simple', text)", persisted=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('document_id', 'chunk_index', name='uq_chunks_document_id_chunk_index')
    )

    op.create_index(
        'ix_chunks_document_id_chunk_index',
        'chunks',
        ['document_id', 'chunk_index']
    )

    # 3. Create HNSW vector index with cosine distance
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
    )

    # 4. Create GIN index on tsvector for hybrid/keyword search
    op.execute(
        "CREATE INDEX ix_chunks_tsv_gin ON chunks USING gin (tsv);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_gin;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.drop_index('ix_chunks_document_id_chunk_index', table_name='chunks')
    op.drop_table('chunks')
    op.drop_index('ix_documents_index_status', table_name='documents')
    op.drop_column('documents', 'indexed_at')
    op.drop_column('documents', 'chunks_count')
    op.drop_column('documents', 'index_error')
    op.drop_column('documents', 'index_status')

