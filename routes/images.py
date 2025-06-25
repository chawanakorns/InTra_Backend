# file: images.py

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
import uuid
import shutil
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

# Ensure your imports match your project structure
from database.db import get_db, User
from services.auth import get_current_user

# ✅ FIX: The redundant prefix has been removed.
# The prefix is now correctly handled only in main.py.
router = APIRouter(tags=["images"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def _upload_image(
    file: UploadFile,
    current_user: User,
    db: AsyncSession,
    upload_type: Literal["profile", "background"]
):
    """Handles file validation, saving, and updating the user model."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

    file_extension = Path(file.filename).suffix or ".jpg"
    prefix = "profile_" if upload_type == "profile" else "bg_"
    filename = f"{prefix}{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        image_path = f"/uploads/{filename}"
        if upload_type == "profile":
            current_user.image_uri = image_path
            response_key = "image_uri"
        else:
            current_user.background_uri = image_path
            response_key = "background_uri"

        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)

        return {response_key: image_path}
    except Exception as e:
        await db.rollback()
        print(f"!!! DATABASE OR FILE SYSTEM ERROR DURING IMAGE UPLOAD: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed.")


@router.post("/profile/upload")
async def upload_profile_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await _upload_image(file, current_user, db, "profile")


@router.post("/background/upload")
async def upload_background_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await _upload_image(file, current_user, db, "background")