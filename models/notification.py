# file: models/notification.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificationBase(BaseModel):
    title: str
    body: Optional[str] = None


class NotificationCreate(NotificationBase):
    pass


class NotificationResponse(NotificationBase):
    id: int
    user_id: int
    created_at: datetime
    is_read: bool

    class Config:
        from_attributes = True