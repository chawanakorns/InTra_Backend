from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy import select
from utils.security import create_access_token, hash_password
from models.user import UserCreate, UserResponse, Token, UserPersonalization, UserUpdate
from services.auth import authenticate_user, get_current_user
from database.db import User, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


async def get_current_user_dependency(token: str = Depends(oauth2_scheme)):
    return await get_current_user(token)


@router.post("/register", response_model=Token)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email == user.email)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # --- FIX: Convert date string to a date object ---
    try:
        dob_object = datetime.strptime(user.date_of_birth, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date_of_birth format. Use YYYY-MM-DD."
        )

    # --- FIX: Create the DB user instance manually with the correct data types ---
    db_user = User(
        full_name=user.full_name,
        date_of_birth=dob_object,  # Pass the date object here
        gender=user.gender,
        email=user.email,
        # about_me, image_uri etc. will default to None, which is correct
    )
    db_user.password = hash_password(user.password)

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    return await authenticate_user(form_data.username, form_data.password)


@router.post("/logout")
async def logout(current_user: UserResponse = Depends(get_current_user_dependency)):
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user_dependency)):
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
        user_update: UserUpdate,
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db)
):
    stmt = select(User).where(User.id == current_user.id)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user_update.fullName is not None:
        user.full_name = user_update.fullName
    if user_update.aboutMe is not None:
        user.about_me = user_update.aboutMe
    if user_update.gender is not None:
        user.gender = user_update.gender
    if user_update.imageUri is not None:
        user.image_uri = user_update.imageUri
    if user_update.backgroundUri is not None:
        user.background_uri = user_update.backgroundUri
    if user_update.dob:
        try:
            user.date_of_birth = datetime.strptime(user_update.dob, "%d/%m/%Y").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Expected DD/MM/YYYY.")

    await db.commit()
    await db.refresh(user)

    return UserResponse.from_orm(user)


@router.post("/personalization", response_model=UserResponse)
async def save_personalization(
        personalization: UserPersonalization,
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db)
):
    try:
        stmt = select(User).where(User.id == current_user.id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        user.tourist_type = personalization.tourist_type
        user.preferred_activities = personalization.preferred_activities
        user.preferred_cuisines = personalization.preferred_cuisines
        user.preferred_dining = personalization.preferred_dining
        user.preferred_times = personalization.preferred_times
        user.has_completed_personalization = True

        await db.commit()
        await db.refresh(user)

        return UserResponse.from_orm(user)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"Database error during personalization save: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save personalization data"
        )