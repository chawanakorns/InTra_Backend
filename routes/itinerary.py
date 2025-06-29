from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, orm
from database.db import get_db
from database.db import Itinerary as ItineraryModel, ScheduleItem as ScheduleItemModel
from models.itinerary import ItineraryCreate, Itinerary as ItineraryResponse, ScheduleItem as ScheduleItemResponse
from routes.auth import get_current_user_dependency
from models.user import UserResponse
from datetime import datetime
from services.generation_service import auto_generate_schedule
from routes.recommendations import get_personalized_places
from models.recommendations import Place
import logging
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class ScheduleItemCreate(BaseModel):
    place_id: str
    place_name: str
    place_type: Optional[str] = None
    place_address: Optional[str] = None
    place_rating: Optional[float] = None
    place_image: Optional[str] = None
    scheduled_date: str
    scheduled_time: str
    duration_minutes: int


def convert_to_pydantic(db_itinerary: ItineraryModel) -> ItineraryResponse:
    return ItineraryResponse(
        id=db_itinerary.id,
        type=db_itinerary.type,
        budget=db_itinerary.budget,
        name=db_itinerary.name,
        start_date=db_itinerary.start_date,
        end_date=db_itinerary.end_date,
        user_id=db_itinerary.user_id,
        schedule_items=[
            ScheduleItemResponse(
                place_id=item.place_id,
                place_name=item.place_name,
                place_type=item.place_type,
                place_address=item.place_address,
                place_rating=item.place_rating,
                place_image=item.place_image,
                scheduled_date=item.scheduled_date.strftime("%Y-%m-%d"),
                scheduled_time=item.scheduled_time,
                duration_minutes=item.duration_minutes,
            ) for item in db_itinerary.schedule_items
        ]
    )


@router.get("/", response_model=list[ItineraryResponse])
async def get_user_itineraries(
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db),
):
    try:
        stmt = (
            select(ItineraryModel)
            .where(ItineraryModel.user_id == current_user.id)
            .options(orm.selectinload(ItineraryModel.schedule_items))
            .order_by(ItineraryModel.start_date.desc())
        )
        result = await db.execute(stmt)
        itineraries = result.scalars().unique().all()

        return [convert_to_pydantic(it) for it in itineraries]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/", response_model=ItineraryResponse)
async def create_itinerary(
        itinerary: ItineraryCreate,
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db),
):
    try:
        # Provide a default value for budget if it's missing from the request.
        budget_value = itinerary.budget if itinerary.budget else "Not Specified"

        db_itinerary = ItineraryModel(
            user_id=current_user.id,
            type="Customized",
            budget=budget_value,
            name=itinerary.name,
            start_date=itinerary.start_date,
            end_date=itinerary.end_date,
        )
        db.add(db_itinerary)
        await db.commit()
        await db.refresh(db_itinerary)

        # Manually construct the response to ensure the correct type is sent back
        return ItineraryResponse(
            id=db_itinerary.id,
            type="Customized",
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


@router.post("/generate", response_model=ItineraryResponse)
async def generate_itinerary(
        itinerary_data: ItineraryCreate,
        current_user: UserResponse = Depends(get_current_user_dependency),
        db: AsyncSession = Depends(get_db),
):
    try:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }
        attractions_task = get_personalized_places(user_preferences, "tourist_attraction")
        restaurants_task = get_personalized_places(user_preferences, "restaurant")

        attractions, restaurants = await attractions_task, await restaurants_task

        all_places_map = {p.id: p for p in attractions + restaurants}

        generated_items = await auto_generate_schedule(itinerary_data, current_user, attractions, restaurants)

        if not generated_items:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate itinerary schedule from AI. Please try again."
            )

        budget_value = itinerary_data.budget if itinerary_data.budget else "Not Specified"

        db_itinerary = ItineraryModel(
            user_id=current_user.id,
            type="Auto-generated",
            budget=budget_value,
            name=itinerary_data.name,
            start_date=itinerary_data.start_date,
            end_date=itinerary_data.end_date,
        )
        db.add(db_itinerary)
        await db.flush()

        schedule_items_to_add = []
        for item in generated_items:
            try:
                place_details = all_places_map.get(item.get("place_id"))
                if not place_details:
                    logger.warning(f"AI returned unknown place_id, skipping: {item.get('place_id')}")
                    continue

                if "scheduled_date" not in item or "scheduled_time" not in item:
                    logger.warning(f"AI response missing required fields, skipping: {item}")
                    continue

                scheduled_date_obj = datetime.strptime(item["scheduled_date"], "%Y-%m-%d").date()

                schedule_items_to_add.append(
                    ScheduleItemModel(
                        itinerary_id=db_itinerary.id,
                        place_id=place_details.id,
                        place_name=place_details.name,
                        place_type=next(iter(place_details.types or []), "attraction"),
                        place_address=place_details.address,
                        place_rating=place_details.rating,
                        place_image=place_details.image,
                        scheduled_date=scheduled_date_obj,
                        scheduled_time=item["scheduled_time"],
                        duration_minutes=item.get("duration_minutes", 60),
                    )
                )
            except (ValueError, KeyError) as e:
                logger.error(f"Could not parse schedule item from AI. Error: {e}. Item: {item}")
                continue

        if not schedule_items_to_add:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI generated a schedule, but all items were invalid."
            )

        db.add_all(schedule_items_to_add)
        await db.commit()
        await db.refresh(db_itinerary, attribute_names=["schedule_items"])

        return convert_to_pydantic(db_itinerary)

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create generated itinerary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create generated itinerary: {str(e)}",
        )


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(
    itinerary_id: int,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a specific itinerary by its ID.
    Ensures that only the owner of the itinerary can delete it.
    """
    stmt = select(ItineraryModel).where(
        ItineraryModel.id == itinerary_id,
        ItineraryModel.user_id == current_user.id
    )
    result = await db.execute(stmt)
    db_itinerary = result.scalars().first()

    if not db_itinerary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Itinerary not found or you don't have permission to delete it."
        )

    try:
        await db.delete(db_itinerary)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete itinerary {itinerary_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete itinerary."
        )
    return


@router.post("/{itinerary_id}/items", response_model=ScheduleItemResponse, status_code=status.HTTP_201_CREATED)
async def add_schedule_item_to_itinerary(
    itinerary_id: int,
    item: ScheduleItemCreate,
    current_user: UserResponse = Depends(get_current_user_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Adds a new schedule item to an existing itinerary.
    """
    stmt = select(ItineraryModel).where(
        ItineraryModel.id == itinerary_id,
        ItineraryModel.user_id == current_user.id
    )
    result = await db.execute(stmt)
    db_itinerary = result.scalars().first()

    if not db_itinerary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Itinerary not found or you don't have permission to access it."
        )

    try:
        scheduled_date_obj = datetime.strptime(item.scheduled_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid scheduled_date format. Use YYYY-MM-DD."
        )

    if not (db_itinerary.start_date <= scheduled_date_obj <= db_itinerary.end_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scheduled date must be within the itinerary's range ({db_itinerary.start_date} to {db_itinerary.end_date})."
        )

    db_schedule_item = ScheduleItemModel(
        itinerary_id=itinerary_id,
        place_id=item.place_id,
        place_name=item.place_name,
        place_type=item.place_type,
        place_address=item.place_address,
        place_rating=item.place_rating,
        place_image=item.place_image,
        scheduled_date=scheduled_date_obj,
        scheduled_time=item.scheduled_time,
        duration_minutes=item.duration_minutes
    )

    try:
        db.add(db_schedule_item)
        await db.commit()
        await db.refresh(db_schedule_item)

        return ScheduleItemResponse(
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
        logger.error(f"Failed to add schedule item: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add item to itinerary."
        )