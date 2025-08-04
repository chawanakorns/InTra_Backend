# file: models/notification.py

from pydantic import BaseModel, ConfigDict
from datetime import datetime

class NotificationBase(BaseModel):
    title: str
    body: str

class NotificationCreate(NotificationBase):
    pass

class NotificationResponse(NotificationBase):
    id: int
    user_id: int
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)