# routes/image.py

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import get_db, User  # Assuming your User model is in db.py
from services.auth import get_current_user  # Assuming you have this service
from models.user import UserResponse  # Assuming you have this Pydantic model
import uuid
from pathlib import Path

router = APIRouter(prefix="/api/images", tags=["images"])

# Define the directory where uploads will be stored
UPLOAD_DIR = Path("uploads")


async def save_image(file: UploadFile) -> str:
    """
    Saves an uploaded image to the UPLOAD_DIR with a unique filename.
    Returns the relative path to the saved file (e.g., "uploads/filename.jpg").
    """
    # Create a unique filename to prevent overwrites
    file_extension = Path(file.filename).suffix
    file_name = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / file_name

    try:
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    # Return the path as a string with forward slashes for URL compatibility
    return str(file_path).replace("\\", "/")


@router.post("/profile/upload", status_code=200)
async def upload_profile_image(
        file: UploadFile = File(...),
        current_user: UserResponse = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Uploads/updates a user's profile image and returns its relative URI."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

    relative_path = await save_image(file)

    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.image_uri = relative_path
    await db.commit()

    # Return a consistent JSON key "uri" for the frontend
    return {"uri": relative_path}


@router.post("/background/upload", status_code=200)
async def upload_background_image(
        file: UploadFile = File(...),
        current_user: UserResponse = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Uploads/updates a user's background image and returns its relative URI."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

    relative_path = await save_image(file)

    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.background_uri = relative_path
    await db.commit()

    # Return a consistent JSON key "uri" for the frontend
    return {"uri": relative_path}