from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import get_db, User
from fastapi.responses import FileResponse
from services.auth import get_current_user
from models.user import UserResponse
import os
import uuid
from pathlib import Path

router = APIRouter(prefix="/api/images", tags=["images"])

# Directory to store uploaded images
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


async def save_image(file: UploadFile) -> str:
    """Save uploaded image and return its path."""
    file_extension = file.filename.split(".")[-1]
    file_name = f"{uuid.uuid4()}.{file_extension}"
    file_path = UPLOAD_DIR / file_name

    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    return str(file_path)


@router.post("/profile/upload")
async def upload_profile_image(
        file: UploadFile = File(...),
        current_user: UserResponse = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Upload or update user's profile image."""
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        image_path = await save_image(file)

        user = await db.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.image_uri = image_path
        await db.commit()
        await db.refresh(user)

        return {"image_uri": user.image_uri}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload profile image: {str(e)}")


@router.post("/background/upload")
async def upload_background_image(
        file: UploadFile = File(...),
        current_user: UserResponse = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Upload or update user's background image."""
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")

        image_path = await save_image(file)

        user = await db.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.background_uri = image_path
        await db.commit()
        await db.refresh(user)

        return {"background_uri": user.background_uri}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload background image: {str(e)}")


@router.get("/profile/{user_id}")
async def get_profile_image(user_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve user's profile image."""
    user = await db.get(User, user_id)
    if not user or not user.image_uri:
        raise HTTPException(status_code=404, detail="Profile image not found")

    if not os.path.exists(user.image_uri):
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(user.image_uri)


@router.get("/background/{user_id}")
async def get_background_image(user_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve user's background image."""
    user = await db.get(User, user_id)
    if not user or not user.background_uri:
        raise HTTPException(status_code=404, detail="Background image not found")

    if not os.path.exists(user.background_uri):
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(user.background_uri)