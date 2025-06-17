from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.db import get_db
from database.db import Itinerary as ItineraryModel, ScheduleItem as ScheduleItemModel
from models.itinerary import ItineraryCreate, Itinerary
from routes.auth import get_current_user_dependency
from models.user import UserResponse
from pydantic import BaseModel
from typing import Optional, List
import json
from datetime import datetime

router = APIRouter()

class ScheduleItem(BaseModel):
    place_id: str
    place_name: str
    place_type: Optional[str] = None
    place_address: Optional[str] = None
    place_rating: Optional[float] = None
    place_image: Optional[str] = None
    scheduled_date: str
    scheduled_time: str
    duration_minutes: int = 60

    class Config:
        from_attributes = True

@router.get("/", response_model=list[Itinerary])
async def get_user_itineraries(
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db),
):
    try:
        stmt = select(ItineraryModel).where(ItineraryModel.user_id == current_user.id)
        result = await db.execute(stmt)
        itineraries = result.scalars().all()

        itinerary_list = []
        for itinerary in itineraries:
            # Fetch schedule items for the itinerary
            schedule_items_stmt = select(ScheduleItemModel).where(ScheduleItemModel.itinerary_id == itinerary.id)
            schedule_items_result = await db.execute(schedule_items_stmt)
            schedule_items = schedule_items_result.scalars().all()

            # Convert SQLAlchemy models to Pydantic models
            itinerary_list.append(
                Itinerary(
                    id=itinerary.id,
                    type=itinerary.type,
                    budget=itinerary.budget,
                    name=itinerary.name,
                    start_date=itinerary.start_date,
                    end_date=itinerary.end_date,
                    user_id=itinerary.user_id,
                    schedule_items=[
                        ScheduleItem(
                            place_id=item.place_id,
                            place_name=item.place_name,
                            place_type=item.place_type,
                            place_address=item.place_address,
                            place_rating=item.place_rating,
                            place_image=item.place_image,
                            scheduled_date=item.scheduled_date.strftime(
                                "%Y-%m-%d"),  # Format date as string
                            scheduled_time=item.scheduled_time,
                            duration_minutes=item.duration_minutes,
                        ) for item in schedule_items
                    ]
                )
            )

        return itinerary_list
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/", response_model=Itinerary)
async def create_itinerary(
    itinerary: ItineraryCreate,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    try:
        db_itinerary = ItineraryModel(
            user_id=current_user.id,
            type=itinerary.type,
            budget=itinerary.budget,
            name=itinerary.name,
            start_date=itinerary.start_date,
            end_date=itinerary.end_date,
        )
        db.add(db_itinerary)
        await db.commit()
        await db.refresh(db_itinerary)

        # Convert SQLAlchemy model to Pydantic model, including the empty schedule_items
        return Itinerary(
            id=db_itinerary.id,
            type=db_itinerary.type,
            budget=db_itinerary.budget,
            name=db_itinerary.name,
            start_date=db_itinerary.start_date,
            end_date=db_itinerary.end_date,
            user_id=db_itinerary.user_id,
            schedule_items=[]
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create itinerary: {str(e)}",
        )

@router.get("/{itinerary_id}/items", response_model=List[ScheduleItem])
async def get_itinerary_schedule_items(
    itinerary_id: int,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Verify that the itinerary exists and belongs to the user
        stmt = select(ItineraryModel).where(
            ItineraryModel.id == itinerary_id, ItineraryModel.user_id == current_user.id
        )
        result = await db.execute(stmt)
        itinerary = result.scalars().first()

        if not itinerary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found"
            )

        # Fetch schedule items for the itinerary
        schedule_items_stmt = select(ScheduleItemModel).where(ScheduleItemModel.itinerary_id == itinerary_id)
        schedule_items_result = await db.execute(schedule_items_stmt)
        schedule_items = schedule_items_result.scalars().all()

        # Convert SQLAlchemy models to Pydantic models
        schedule_item_list = [
            ScheduleItem(
                place_id=item.place_id,
                place_name=item.place_name,
                place_type=item.place_type,
                place_address=item.place_address,
                place_rating=item.place_rating,
                place_image=item.place_image,
                scheduled_date=item.scheduled_date.strftime(
                    "%Y-%m-%d"),  # Format date as string
                scheduled_time=item.scheduled_time,
                duration_minutes=item.duration_minutes,
            ) for item in schedule_items
        ]

        return schedule_item_list
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

@router.post("/{itinerary_id}/items", response_model=ScheduleItem)
async def add_item_to_itinerary(
    itinerary_id: int,
    schedule_item: ScheduleItem,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Verify that the itinerary exists and belongs to the user
        stmt = select(ItineraryModel).where(
            ItineraryModel.id == itinerary_id, ItineraryModel.user_id == current_user.id
        )
        result = await db.execute(stmt)
        itinerary = result.scalars().first()

        if not itinerary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found"
            )

        db_schedule_item = ScheduleItemModel(
            itinerary_id=itinerary_id,
            place_id=schedule_item.place_id,
            place_name=schedule_item.place_name,
            place_type=schedule_item.place_type,
            place_address=schedule_item.place_address,
            place_rating=schedule_item.place_rating,
            place_image=schedule_item.place_image,
            scheduled_date=datetime.strptime(
                schedule_item.scheduled_date, "%Y-%m-%d"
            ).date(),
            scheduled_time=schedule_item.scheduled_time,
            duration_minutes=schedule_item.duration_minutes,
        )
        db.add(db_schedule_item)
        await db.commit()
        await db.refresh(db_schedule_item)

        return ScheduleItem(
            place_id=db_schedule_item.place_id,
            place_name=db_schedule_item.place_name,
            place_type=db_schedule_item.place_type,
            place_address=db_schedule_item.place_address,
            place_rating=db_schedule_item.place_rating,
            place_image=db_schedule_item.place_image,
            scheduled_date=db_schedule_item.scheduled_date.strftime("%Y-%m-%d"),
            scheduled_time=db_schedule_item.scheduled_time,
            duration_minutes=db_schedule_item.duration_minutes,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add item to itinerary: {str(e)}",
        )


@router.get("/{itinerary_id}/items", response_model=List[ScheduleItem])  # ADD THIS
async def get_schedule_items_for_itinerary(
    itinerary_id: int,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve all schedule items for a specific itinerary.
    """
    try:
        # Verify that the itinerary exists and belongs to the user
        stmt = select(ItineraryModel).where(
            ItineraryModel.id == itinerary_id, ItineraryModel.user_id == current_user.id
        )
        result = await db.execute(stmt)
        itinerary = result.scalars().first()

        if not itinerary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found"
            )

        # Fetch schedule items for the itinerary
        stmt = select(ScheduleItemModel).where(
            ScheduleItemModel.itinerary_id == itinerary_id
        )
        result = await db.execute(stmt)
        schedule_items = result.scalars().all()

        # Convert SQLAlchemy models to Pydantic models
        return [
            ScheduleItem(
                place_id=item.place_id,
                place_name=item.place_name,
                place_type=item.place_type,
                place_address=item.place_address,
                place_rating=item.place_rating,
                place_image=item.place_image,
                scheduled_date=item.scheduled_date.strftime("%Y-%m-%d"),
                scheduled_time=item.scheduled_time,
                duration_minutes=item.duration_minutes,
            )
            for item in schedule_items
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve schedule items: {str(e)}",
        )