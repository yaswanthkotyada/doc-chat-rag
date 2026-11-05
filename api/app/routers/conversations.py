import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.conversation import Conversation
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationListItem,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: Optional[ConversationCreate] = None,
    db: AsyncSession = Depends(get_db)
):
    title = payload.title.strip() if payload and payload.title else None
    conversation = Conversation(title=title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return {"id": conversation.id, "title": conversation.title}


@router.get("", response_model=List[ConversationListItem])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Conversation)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return conversations


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    await db.delete(conversation)
    await db.commit()
    return None
