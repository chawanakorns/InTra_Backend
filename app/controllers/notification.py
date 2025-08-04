# file: controllers/notification.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List

from app.database.connection import get_db
from app.database.models import Notification as NotificationModel, User
from app.models.notification import NotificationCreate, NotificationResponse
from app.services.firebase_auth import get_current_user

router = APIRouter()


@router.post("/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(
        notification: NotificationCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Creates a new notification for the currently authenticated user.
    """
    db_notification = NotificationModel(
        **notification.dict(),
        user_id=current_user.id
    )
    db.add(db_notification)
    await db.commit()
    await db.refresh(db_notification)
    return db_notification


@router.get("/", response_model=List[NotificationResponse])
async def get_user_notifications(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Retrieves all notifications for the currently authenticated user,
    ordered by most recent first.
    """
    stmt = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_as_read(
        notification_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Marks a specific notification as read.
    """
    stmt = select(NotificationModel).where(
        NotificationModel.id == notification_id,
        NotificationModel.user_id == current_user.id
    )
    result = await db.execute(stmt)
    db_notification = result.scalars().first()

    if not db_notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    db_notification.is_read = True
    await db.commit()
    await db.refresh(db_notification)
    return db_notification


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_notifications(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Deletes all notifications for the currently authenticated user.
    """
    stmt = delete(NotificationModel).where(NotificationModel.user_id == current_user.id)
    await db.execute(stmt)
    await db.commit()
    return


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
        notification_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """
    Deletes a specific notification.
    """
    stmt = select(NotificationModel).where(
        NotificationModel.id == notification_id,
        NotificationModel.user_id == current_user.id
    )
    result = await db.execute(stmt)
    db_notification = result.scalars().first()

    if not db_notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    await db.delete(db_notification)
    await db.commit()
    return