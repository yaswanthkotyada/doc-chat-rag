import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import BigInteger, Boolean, Column, Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False
    )
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="uploading")  # uploading, processing, ready, failed
    error = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    mode = Column(String(20), nullable=True)  # reserved: 'direct' | 'rag'
    mode_override = Column(String(20), nullable=True)  # Stage 7 manual override: 'direct' | 'rag' | None
    meta = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Parsing fields (Stage 5)
    parse_status = Column(String(20), nullable=True)  # pending, parsing, parsed, failed, skipped
    parse_error = Column(Text, nullable=True)
    parser_name = Column(String(64), nullable=True)
    parser_version = Column(String(64), nullable=True)
    parse_started_at = Column(DateTime(timezone=True), nullable=True)
    parse_finished_at = Column(DateTime(timezone=True), nullable=True)
    pages_parsed = Column(Integer, nullable=True, default=0)
    parse_options = Column(JSONB, nullable=True)

    # Indexing fields (Stage 6)
    index_status = Column(String(20), nullable=True)  # pending, indexing, indexed, failed, skipped
    index_error = Column(Text, nullable=True)
    chunks_count = Column(Integer, nullable=True, default=0)
    indexed_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="documents")
    pages = relationship(
        "DocumentPage",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_no",
    )
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )

    __table_args__ = (
        Index("ix_documents_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_documents_parse_status", "parse_status"),
        Index("ix_documents_index_status", "index_status"),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    page_no = Column(Integer, nullable=False)  # 1-based page number
    markdown = Column(Text, nullable=False)
    plain_text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    has_table = Column(Boolean, nullable=False, default=False)
    has_figure = Column(Boolean, nullable=False, default=False)
    ocr_used = Column(Boolean, nullable=True)
    warnings = Column(JSONB, nullable=False, default=list, server_default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_no", name="uq_document_pages_document_id_page_no"),
        Index("ix_document_pages_document_id_page_no", "document_id", "page_no"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embed_text = Column(Text, nullable=False)
    page_start = Column(Integer, nullable=False)
    page_end = Column(Integer, nullable=False)
    heading_path = Column(JSONB, nullable=False, default=list, server_default="[]")
    chunk_type = Column(String(20), nullable=False, default="text")
    token_count = Column(Integer, nullable=False, default=0)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    embedding = Column(Vector(768), nullable=True)
    tsv = Column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
        Index("ix_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )
