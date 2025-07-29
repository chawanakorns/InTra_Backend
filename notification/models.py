# models.py
from pydantic import BaseModel
from typing import Optional, Dict

class NotificationRequest(BaseModel):
    fcm_token: str
    title: str
    body: str
    data: Optional[Dict[str, str]] = None

class InAppNotification(BaseModel):
    user_id: str
    title: str
    body: str
    category: str = "general"
    created_at: Optional[str] = None
    read: Optional[bool] = False
