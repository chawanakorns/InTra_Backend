# file: services/auth.py

# --- IMPORTS ---
from fastapi import HTTPException, status, Depends  # <--- FIX: Added Depends
from fastapi.security import OAuth2PasswordBearer  # <--- FIX: Added OAuth2PasswordBearer
import jwt
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Assuming these are correct paths from your project structure
from database.db import get_db_session, User
from models.user import UserCreate, UserResponse
from utils.security import hash_password, verify_password, create_access_token

# --- CONSTANTS ---
SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 43200

# --- FIX: Define the OAuth2 scheme ---
# This tells FastAPI to look for the token in the 'Authorization: Bearer <token>' header.
# The tokenUrl points to your login endpoint for documentation purposes.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# --- UNCHANGED FUNCTIONS (No changes needed here) ---

async def register_user(user: UserCreate) -> UserResponse:
    # This function is fine as-is.
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

            return UserResponse.from_orm(new_user)

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            # It's better to log this than print
            # import logging; logging.error(...)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Registration failed due to database error"
            )


async def authenticate_user(email: str, password: str) -> dict:
    # This function is fine as-is.
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

            access_token = create_access_token(data={"sub": user.email})
            return {"access_token": access_token, "token_type": "bearer"}

        except HTTPException:
            raise
        except Exception as e:
            # import logging; logging.error(...)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication failed due to database error"
            )


# --- CORRECTED get_current_user FUNCTION ---

async def get_current_user(
        token: str = Depends(oauth2_scheme)) -> User:  # <--- FIX 1 & 2: Use Depends and return the User model
    """
    This dependency gets the token from the 'Authorization' header,
    validates it, and returns the SQLAlchemy User object.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception

    async with get_db_session() as session:
        # No need for a try/except here if we let the main error handler catch DB issues
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            raise credentials_exception

        return user  # <--- FIX 3: Return the actual User ORM object, not a Pydantic model