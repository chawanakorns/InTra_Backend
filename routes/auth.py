from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from firebase_admin import auth

# --- NEW: Import for catching specific database errors ---
from sqlalchemy.exc import IntegrityError

from models.user import UserResponse, UserUpdate, UserPersonalization
from services.firebase_auth import get_current_user, oauth2_scheme
from database.db import User, get_db

router = APIRouter()

@router.post("/sync", response_model=UserResponse)
async def sync_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase token: {e}"
        )

    stmt = select(User).where(User.firebase_uid == uid)
    result = await db.execute(stmt)
    db_user = result.scalars().first()

    if db_user:
        return UserResponse.from_orm(db_user)
    else:
        # --- IMPROVED: Better error handling for database creation ---
        try:
            firebase_user_record = auth.get_user(uid)
            new_user = User(
                firebase_uid=firebase_user_record.uid,
                email=firebase_user_record.email,
                full_name=firebase_user_record.display_name,
                image_uri=firebase_user_record.photo_url,
                has_completed_personalization=False
            )
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            return UserResponse.from_orm(new_user)
        except IntegrityError:
            # This can happen in a race condition if two requests come at once.
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User profile already exists."
            )
        except Exception as e:
            # Catch any other unexpected errors during profile creation.
            await db.rollback()
            # Log the detailed error for debugging on the backend.
            print(f"!!! SERVER ERROR during user creation: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user profile in the database."
            )

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
            current_user.date_of_birth = datetime.strptime(user_update.dob, "%Y-%m-%d").date()
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