from fastapi import HTTPException, status
import jwt
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.db import get_db_session, User
from models.user import UserCreate, UserResponse
from utils.security import hash_password, verify_password, create_access_token

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

async def register_user(user: UserCreate) -> UserResponse:
    try:
        dob = datetime.strptime(user.date_of_birth, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date_of_birth format. Use YYYY-MM-DD."
        )

    valid_genders = ["Male", "Female", "Other", "Prefer not to say"]
    if user.gender not in valid_genders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid gender. Must be one of: {', '.join(valid_genders)}"
        )

    async with get_db_session() as session:
        try:
            stmt = select(User).where(User.email == user.email)
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            new_user = User(
                full_name=user.full_name,
                date_of_birth=dob,
                gender=user.gender,
                email=user.email,
                password=hash_password(user.password)
            )

            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)

            return UserResponse(
                id=new_user.id,
                full_name=new_user.full_name,
                email=new_user.email,
                date_of_birth=new_user.date_of_birth,
                gender=new_user.gender,
                has_completed_personalization=new_user.has_completed_personalization,
                tourist_type=new_user.tourist_type,
                preferred_activities=new_user.preferred_activities,
                preferred_cuisines=new_user.preferred_cuisines,
                preferred_dining=new_user.preferred_dining,
                preferred_times=new_user.preferred_times
            )

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            print(f"Database error during user registration: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Registration failed due to database error"
            )

async def authenticate_user(email: str, password: str) -> dict:
    async with get_db_session() as session:
        try:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user or not verify_password(password, user.password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )

            print(f"Creating token for user: {user.email}")

            access_token = create_access_token(data={"sub": user.email})
            return {"access_token": access_token, "token_type": "bearer"}

        except HTTPException:
            raise
        except Exception as e:
            print(f"Database error during authentication: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication failed due to database error"
            )

async def get_current_user(token: str) -> UserResponse:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    async with get_db_session() as session:
        try:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )

            return UserResponse(
                id=user.id,
                full_name=user.full_name,
                email=user.email,
                date_of_birth=user.date_of_birth,
                gender=user.gender,
                has_completed_personalization=user.has_completed_personalization,
                tourist_type=user.tourist_type,
                preferred_activities=user.preferred_activities,
                preferred_cuisines=user.preferred_cuisines,
                preferred_dining=user.preferred_dining,
                preferred_times=user.preferred_times
            )

        except HTTPException:
            raise
        except Exception as e:
            print(f"Database error during user lookup: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User lookup failed due to database error"
            )