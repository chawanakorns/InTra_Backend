from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.db import get_db
from database.db import Itinerary as ItineraryModel  # Import from your db.py
from models.itinerary import ItineraryCreate, Itinerary
from routes.auth import get_current_user_dependency
from models.user import UserResponse

router = APIRouter()


@router.get("/", response_model=list[Itinerary])
async def get_user_itineraries(
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db)
):
    try:
        # Correct SQLAlchemy query - use the model class from db.py
        stmt = select(ItineraryModel).where(ItineraryModel.user_id == current_user.id)
        result = await db.execute(stmt)
        itineraries = result.scalars().all()

        # Convert SQLAlchemy models to Pydantic models
        return [
            Itinerary(
                id=it.id,
                type=it.type,
                budget=it.budget,
                name=it.name,
                start_date=it.start_date,
                end_date=it.end_date,
                schedule=it.schedule or []
            )
            for it in itineraries
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/", response_model=Itinerary)
async def create_itinerary(
        itinerary: ItineraryCreate,
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db)
):
    try:
        db_itinerary = ItineraryModel(
            user_id=current_user.id,
            type=itinerary.type,
            budget=itinerary.budget,
            name=itinerary.name,
            start_date=itinerary.start_date,
            end_date=itinerary.end_date,
            schedule=itinerary.schedule or []
        )
        db.add(db_itinerary)
        await db.commit()
        await db.refresh(db_itinerary)

        # Convert SQLAlchemy model to Pydantic model
        return Itinerary(
            id=db_itinerary.id,
            type=db_itinerary.type,
            budget=db_itinerary.budget,
            name=db_itinerary.name,
            start_date=db_itinerary.start_date,
            end_date=db_itinerary.end_date,
            schedule=db_itinerary.schedule or []
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create itinerary: {str(e)}"
        )