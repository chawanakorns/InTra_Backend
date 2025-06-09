from pydantic import BaseModel, EmailStr, validator
from typing import Literal, Optional, List
from datetime import date

class UserCreate(BaseModel):
    full_name: str
    date_of_birth: str
    gender: Literal["Male", "Female", "Other", "Prefer not to say"]
    email: EmailStr
    password: str

    @validator('full_name')
    def validate_full_name(cls, v):
        if not v.strip():
            raise ValueError('Full name cannot be empty')
        return v.strip()

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v

class UserPersonalization(BaseModel):
    tourist_type: Optional[List[str]] = None
    preferred_activities: Optional[List[str]] = None
    preferred_cuisines: Optional[List[str]] = None
    preferred_dining: Optional[List[str]] = None
    preferred_times: Optional[List[str]] = None

class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    has_completed_personalization: bool
    tourist_type: Optional[List[str]] = None
    preferred_activities: Optional[List[str]] = None
    preferred_cuisines: Optional[List[str]] = None
    preferred_dining: Optional[List[str]] = None
    preferred_times: Optional[List[str]] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str