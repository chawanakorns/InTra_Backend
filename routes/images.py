from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
import uuid
import shutil
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from database.db import get_db, User
from services.auth import get_current_user

router = APIRouter(tags=["images"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ✅ FIX: Refactored shared logic into a helper function
async def _upload_image(
    file: UploadFile,
    current_user: User,
    db: AsyncSession,
    upload_type: Literal["profile", "background"]
):
    """
    Handles file validation, saving, and updating the user model.
    """
    # ✅ FIX: Add file type validation for security
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

    # ✅ FIX: Dynamically get file extension instead of hardcoding .jpg
    file_extension = Path(file.filename).suffix or ".jpg" # Default to .jpg if no extension
    prefix = "profile_" if upload_type == "profile" else "bg_"
    filename = f"{prefix}{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Update the correct attribute on the user model
        image_path = f"/uploads/{filename}"
        if upload_type == "profile":
            current_user.image_uri = image_path
            response_key = "image_uri"
        else:
            current_user.background_uri = image_path
            response_key = "background_uri"

        await db.commit()
        await db.refresh(current_user)

        return {response_key: image_path}
    except Exception as e:
        await db.rollback()
        # It's good practice to log the actual error for debugging
        # import logging; logging.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image upload failed.")


@router.post("/profile/upload")
async def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Uploads a profile image for the current user."""
    return await _upload_image(file, current_user, db, "profile")


@router.post("/background/upload")
async def upload_background_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Uploads a background image for the current user."""
    return await _upload_image(file, current_user, db, "background")