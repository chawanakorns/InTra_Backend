import firebase_admin
from firebase_admin import credentials, auth
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database.models import User
from app.database.connection import get_db

# Singleton pattern: Check if the app is already initialized
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        print(f"FATAL: Error initializing Firebase Admin SDK: {e}")
else:
    print("Firebase Admin SDK already initialized.")

# Scheme to extract token. auto_error=False makes it optional for certain controllers.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/sync", auto_error=False)


async def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db)
) -> User:
    """
    Required dependency: Verifies Firebase ID token and returns the DB user.
    Raises HTTPException if the token is missing or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        decoded_token = auth.verify_id_token(token)
        firebase_uid = decoded_token['uid']
    except auth.InvalidIdTokenError:
        raise credentials_exception
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise credentials_exception

    stmt = select(User).where(User.firebase_uid == firebase_uid)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found in application database. Please sync your account."
        )
    return user


async def get_optional_current_user(
        token: Optional[str] = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Optional dependency: Returns the User object if a valid token is provided,
    or None if the token is missing or invalid. Does not raise exceptions.
    """
    if not token:
        return None
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        stmt = select(User).where(User.firebase_uid == uid)
        result = await db.execute(stmt)
        return result.scalars().first()
    except Exception:
        return None