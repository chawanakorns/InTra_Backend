from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, date
from firebase_admin import auth
from typing import Optional
from pydantic import BaseModel

from models.user import UserResponse, UserUpdate, UserPersonalization
from services.firebase_auth import get_current_user, oauth2_scheme
from database.db import User, get_db

router = APIRouter()


# --- NEW: Pydantic model for the sync request body ---
class UserSyncRequest(BaseModel):
    fullName: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None


@router.post("/sync", response_model=UserResponse)
async def sync_user(
        sync_data: UserSyncRequest,  # <-- Use the new request body model
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db)
):
    """
    Called by the frontend after a user signs up/in.
    Verifies the Firebase token and creates a user profile in our database
    if one doesn't already exist, populating it with data from the sign-up form.
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid Firebase token: {e}")

    stmt = select(User).where(User.firebase_uid == uid)
    result = await db.execute(stmt)
    db_user = result.scalars().first()

    if db_user:
        # User exists, just return their data
        return UserResponse.from_orm(db_user)
    else:
        # User does not exist, create them
        try:
            firebase_user_record = auth.get_user(uid)

            # Create user with all data from the start
            new_user = User(
                firebase_uid=firebase_user_record.uid,
                email=firebase_user_record.email,
                full_name=sync_data.fullName or firebase_user_record.display_name,  # Prioritize data from form
                date_of_birth=sync_data.dob,
                gender=sync_data.gender,
                has_completed_personalization=False
            )
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            return UserResponse.from_orm(new_user)
        except Exception as e:
            await db.rollback()
            # Log the error for debugging
            print(f"!!! DATABASE ERROR ON USER SYNC: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create user profile in DB.")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.from_orm(current_user)


@router.put("/me", response_model=UserResponse)
async def update_me(
        user_update: UserUpdate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    if user_update.fullName is not None:
        current_user.full_name = user_update.fullName
    if user_update.aboutMe is not None:
        current_user.about_me = user_update.aboutMe
    if user_update.gender is not None:
        current_user.gender = user_update.gender
    if user_update.imageUri is not None:
        current_user.image_uri = user_update.imageUri
    if user_update.backgroundUri is not None:
        current_user.background_uri = user_update.backgroundUri
    if user_update.dob:
        try:
            # Handle both string and date object inputs gracefully
            if isinstance(user_update.dob, str):
                current_user.date_of_birth = datetime.strptime(user_update.dob, "%Y-%m-%d").date()
            else:
                current_user.date_of_birth = user_update.dob
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.from_orm(current_user)


@router.post("/personalization", response_model=UserResponse)
async def save_personalization(
        personalization: UserPersonalization,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    current_user.tourist_type = personalization.tourist_type
    current_user.preferred_activities = personalization.preferred_activities
    current_user.preferred_cuisines = personalization.preferred_cuisines
    current_user.preferred_dining = personalization.preferred_dining
    current_user.preferred_times = personalization.preferred_times
    current_user.has_completed_personalization = True
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.from_orm(current_user)