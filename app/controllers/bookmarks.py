from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database.connection import get_db
from app.database.models import Bookmark as BookmarkModel, User
from app.models.bookmark import BookmarkCreate, BookmarkResponse
from app.services.firebase_auth import get_current_user

router = APIRouter()

@router.post("/", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    bookmark: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt_check = select(BookmarkModel).where(
        BookmarkModel.user_id == current_user.id,
        BookmarkModel.place_id == bookmark.place_id
    )
    result = await db.execute(stmt_check)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This place is already bookmarked.",
        )

    db_bookmark = BookmarkModel(**bookmark.model_dump(), user_id=current_user.id)
    db.add(db_bookmark)
    await db.commit()
    await db.refresh(db_bookmark)
    return db_bookmark

@router.get("/", response_model=List[BookmarkResponse])
async def get_user_bookmarks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BookmarkModel).where(BookmarkModel.user_id == current_user.id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BookmarkModel).where(
        BookmarkModel.id == bookmark_id,
        BookmarkModel.user_id == current_user.id
    )
    result = await db.execute(stmt)
    bookmark_to_delete = result.scalars().first()

    if not bookmark_to_delete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bookmark not found."
        )

    await db.delete(bookmark_to_delete)
    await db.commit()
    return

@router.get("/check/{place_id}", response_model=dict)
async def check_if_bookmarked(
    place_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BookmarkModel).where(
        BookmarkModel.user_id == current_user.id,
        BookmarkModel.place_id == place_id
    )
    result = await db.execute(stmt)
    bookmark = result.scalars().first()

    if bookmark:
        return {"is_bookmarked": True, "bookmark_id": bookmark.id}
    return {"is_bookmarked": False, "bookmark_id": None}