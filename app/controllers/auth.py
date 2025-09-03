from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, date
from firebase_admin import auth
from typing import Optional
from pydantic import BaseModel

from app.models.user import UserResponse, UserUpdate, UserPersonalization, UserSettingsUpdate
from app.services.firebase_auth import get_current_user, oauth2_scheme
from app.database.connection import get_db
from app.database.models import User

router = APIRouter()

class UserSyncRequest(BaseModel):
    fullName: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None

class FCMTokenRequest(BaseModel):
    fcm_token: str

@router.post("/fcm-token")
async def update_fcm_token(
    request: FCMTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt_clear = (
        update(User)
        .where(User.fcm_token == request.fcm_token)
        .values(fcm_token=None)
    )
    await db.execute(stmt_clear)
    current_user.fcm_token = request.fcm_token
    await db.commit()
    return {"message": "FCM token updated successfully"}

@router.post("/sync", response_model=UserResponse)
async def sync_user(
    sync_data: UserSyncRequest,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    if not token: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid Firebase token: {e}")
    stmt = select(User).where(User.firebase_uid == uid)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    if db_user:
        return UserResponse.model_validate(db_user)
    else:
        try:
            firebase_user_record = auth.get_user(uid)
            new_user = User(
                firebase_uid=firebase_user_record.uid,
                email=firebase_user_record.email,
                full_name=sync_data.fullName or firebase_user_record.display_name,
                date_of_birth=sync_data.dob,
                gender=sync_data.gender,
                has_completed_personalization=False
            )
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            return UserResponse.model_validate(new_user)
        except Exception as e:
            await db.rollback()
            print(f"!!! DATABASE ERROR ON USER SYNC: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create user profile in DB.")

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

@router.put("/me", response_model=UserResponse)
async def update_me(user_update: UserUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_update.fullName is not None: current_user.full_name = user_update.fullName
    if user_update.aboutMe is not None: current_user.about_me = user_update.aboutMe
    if user_update.gender is not None: current_user.gender = user_update.gender
    if user_update.imageUri is not None: current_user.image_uri = user_update.imageUri
    if user_update.backgroundUri is not None: current_user.background_uri = user_update.backgroundUri
    if user_update.dob:
        try:
            if isinstance(user_update.dob, str): current_user.date_of_birth = datetime.strptime(user_update.dob, "%Y-%m-%d").date()
            else: current_user.date_of_birth = user_update.dob
        except ValueError: raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)

@router.post("/personalization", response_model=UserResponse)
async def save_personalization(personalization: UserPersonalization, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    current_user.tourist_type = personalization.tourist_type
    current_user.preferred_activities = personalization.preferred_activities
    current_user.preferred_cuisines = personalization.preferred_cuisines
    current_user.preferred_dining = personalization.preferred_dining
    current_user.preferred_times = personalization.preferred_times
    current_user.has_completed_personalization = True
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)

# --- START OF THE FIX ---
@router.put("/me/settings", response_model=UserResponse)
async def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates the notification and other settings for the current user.
    """
    if settings_update.allow_smart_alerts is not None:
        current_user.allow_smart_alerts = settings_update.allow_smart_alerts
    if settings_update.allow_opportunity_alerts is not None:
        current_user.allow_opportunity_alerts = settings_update.allow_opportunity_alerts
    if settings_update.allow_real_time_tips is not None:
        current_user.allow_real_time_tips = settings_update.allow_real_time_tips

    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)
# --- END OF THE FIX ---