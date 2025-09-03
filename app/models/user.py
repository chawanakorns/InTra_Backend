from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Literal, Optional, List
from datetime import date


# --- START OF THE FIX ---
# New model for updating settings
class UserSettingsUpdate(BaseModel):
    allow_smart_alerts: Optional[bool] = None
    allow_opportunity_alerts: Optional[bool] = None
    allow_real_time_tips: Optional[bool] = None


# --- END OF THE FIX ---

class UserCreate(BaseModel):
    full_name: str
    date_of_birth: str
    gender: Literal["Male", "Female", "Other", "Prefer not to say"]
    email: EmailStr
    password: str

    @field_validator('full_name')
    def validate_full_name(cls, v):
        if not v.strip():
            raise ValueError('Full name cannot be empty')
        return v.strip()

    @field_validator('password')
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


class UserUpdate(BaseModel):
    fullName: Optional[str] = None
    aboutMe: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    email: Optional[EmailStr] = None
    imageUri: Optional[str] = None
    backgroundUri: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    has_completed_personalization: bool
    about_me: Optional[str] = None
    image_uri: Optional[str] = None
    background_uri: Optional[str] = None
    tourist_type: Optional[List[str]] = None
    preferred_activities: Optional[List[str]] = None
    preferred_cuisines: Optional[List[str]] = None
    preferred_dining: Optional[List[str]] = None
    preferred_times: Optional[List[str]] = None

    # --- START OF THE FIX ---
    # Add new settings to the main user response model
    allow_smart_alerts: bool
    allow_opportunity_alerts: bool
    allow_real_time_tips: bool
    # --- END OF THE FIX ---

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v