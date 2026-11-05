import uuid
from typing import Any, Dict, Optional
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

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
    meta = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="documents")

    __table_args__ = (
        Index("ix_documents_conversation_id_created_at", "conversation_id", "created_at"),
    )

