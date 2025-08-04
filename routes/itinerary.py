# routes/itinerary.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, orm
from datetime import datetime
import logging
from pydantic import BaseModel
from typing import Optional

from database.db import get_db, User
from database.db import Itinerary as ItineraryModel, ScheduleItem as ScheduleItemModel
from models.itinerary import ItineraryCreate, Itinerary as ItineraryResponse, ScheduleItem as ScheduleItemResponse, \
    ScheduleItemUpdate
from services.firebase_auth import get_current_user
from services.generation_service import auto_generate_schedule
from routes.recommendations import get_personalized_places
from models.recommendations import Place

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
    # This function is safe as long as the schedule_items are pre-loaded.
    return ItineraryResponse(
        id=db_itinerary.id,
        type=db_itinerary.type,
        budget=db_itinerary.budget,
        name=db_itinerary.name,
        start_date=db_itinerary.start_date,
        end_date=db_itinerary.end_date,
        user_id=db_itinerary.user_id,
        schedule_items=[
            ScheduleItemResponse.from_orm(item) for item in db_itinerary.schedule_items
        ]
    )


@router.get("/", response_model=list[ItineraryResponse])
async def get_user_itineraries(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        stmt = (
            select(ItineraryModel)
            .where(ItineraryModel.user_id == current_user.id)
            .options(orm.selectinload(ItineraryModel.schedule_items))  # Eagerly load schedule items
            .order_by(ItineraryModel.start_date.desc())
        )
        result = await db.execute(stmt)
        itineraries = result.scalars().unique().all()
        return [convert_to_pydantic(it) for it in itineraries]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")


@router.post("/", response_model=ItineraryResponse)
async def create_itinerary(itinerary: ItineraryCreate, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    try:
        budget_value = itinerary.budget if itinerary.budget else "Not Specified"
        db_itinerary = ItineraryModel(user_id=current_user.id, type="Customized", budget=budget_value,
                                      name=itinerary.name, start_date=itinerary.start_date, end_date=itinerary.end_date)
        db.add(db_itinerary)
        await db.commit()

        await db.refresh(db_itinerary, attribute_names=['schedule_items'])

        return convert_to_pydantic(db_itinerary)
    except Exception as e:
        await db.rollback()
        # Log the full error to the console for debugging
        logger.error(f"Failed to create itinerary: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to create itinerary: {str(e)}")


@router.post("/generate", response_model=ItineraryResponse)
async def generate_itinerary(itinerary_data: ItineraryCreate, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    try:
        user_preferences = {"tourist_type": current_user.tourist_type or [],
                            "preferred_activities": current_user.preferred_activities or [],
                            "preferred_cuisines": current_user.preferred_cuisines or [],
                            "preferred_dining": current_user.preferred_dining or [],
                            "preferred_times": current_user.preferred_times or []}
        attractions_task = get_personalized_places(user_preferences, "tourist_attraction")
        restaurants_task = get_personalized_places(user_preferences, "restaurant")
        attractions, restaurants = await attractions_task, await restaurants_task
        all_places_map = {p.id: p for p in attractions + restaurants}
        generated_items = await auto_generate_schedule(itinerary_data, current_user, attractions, restaurants)
        if not generated_items:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Failed to generate itinerary schedule from AI. Please try again.")
        budget_value = itinerary_data.budget if itinerary_data.budget else "Not Specified"
        db_itinerary = ItineraryModel(user_id=current_user.id, type="Auto-generated", budget=budget_value,
                                      name=itinerary_data.name, start_date=itinerary_data.start_date,
                                      end_date=itinerary_data.end_date)
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
                schedule_items_to_add.append(ScheduleItemModel(itinerary_id=db_itinerary.id, place_id=place_details.id,
                                                               place_name=place_details.name,
                                                               place_type=next(iter(place_details.types or []),
                                                                               "attraction"),
                                                               place_address=place_details.address,
                                                               place_rating=place_details.rating,
                                                               place_image=place_details.image,
                                                               scheduled_date=scheduled_date_obj,
                                                               scheduled_time=item["scheduled_time"],
                                                               duration_minutes=item.get("duration_minutes", 60)))
            except (ValueError, KeyError) as e:
                logger.error(f"Could not parse schedule item from AI. Error: {e}. Item: {item}")
                continue
        if not schedule_items_to_add:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="AI generated a schedule, but all items were invalid.")
        db.add_all(schedule_items_to_add)
        await db.commit()
        await db.refresh(db_itinerary, attribute_names=["schedule_items"])  # This is correct
        return convert_to_pydantic(db_itinerary)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create generated itinerary: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to create generated itinerary: {str(e)}")


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(itinerary_id: int, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    stmt = select(ItineraryModel).where(ItineraryModel.id == itinerary_id, ItineraryModel.user_id == current_user.id)
    result = await db.execute(stmt)
    db_itinerary = result.scalars().first()
    if not db_itinerary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Itinerary not found or you don't have permission to delete it.")
    try:
        await db.delete(db_itinerary)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete itinerary {itinerary_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete itinerary.")
    return


@router.post("/{itinerary_id}/items", response_model=ScheduleItemResponse, status_code=status.HTTP_201_CREATED)
async def add_schedule_item_to_itinerary(itinerary_id: int, item: ScheduleItemCreate,
                                         current_user: User = Depends(get_current_user),
                                         db: AsyncSession = Depends(get_db)):
    stmt = select(ItineraryModel).where(ItineraryModel.id == itinerary_id, ItineraryModel.user_id == current_user.id)
    result = await db.execute(stmt)
    db_itinerary = result.scalars().first()
    if not db_itinerary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Itinerary not found or you don't have permission to access it.")
    try:
        scheduled_date_obj = datetime.strptime(item.scheduled_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid scheduled_date format. Use YYYY-MM-DD.")
    if not (db_itinerary.start_date <= scheduled_date_obj <= db_itinerary.end_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Scheduled date must be within the itinerary's range ({db_itinerary.start_date} to {db_itinerary.end_date}).")
    db_schedule_item = ScheduleItemModel(itinerary_id=itinerary_id, place_id=item.place_id, place_name=item.place_name,
                                         place_type=item.place_type, place_address=item.place_address,
                                         place_rating=item.place_rating, place_image=item.place_image,
                                         scheduled_date=scheduled_date_obj, scheduled_time=item.scheduled_time,
                                         duration_minutes=item.duration_minutes)
    try:
        db.add(db_schedule_item)
        await db.commit()
        await db.refresh(db_schedule_item)
        return ScheduleItemResponse.from_orm(db_schedule_item)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to add schedule item: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to add item to itinerary.")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_item(item_id: int, current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    item_to_delete = await db.get(ScheduleItemModel, item_id)
    if not item_to_delete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule item not found.")
    stmt = select(ItineraryModel).where(ItineraryModel.id == item_to_delete.itinerary_id,
                                        ItineraryModel.user_id == current_user.id)
    result = await db.execute(stmt)
    owner_itinerary = result.scalars().first()
    if not owner_itinerary:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have permission to delete this item.")
    try:
        await db.delete(item_to_delete)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete schedule item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete schedule item.")
    return


@router.put("/items/{item_id}", response_model=ScheduleItemResponse)
async def update_schedule_item(
        item_id: int,
        item_update: ScheduleItemUpdate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    stmt = select(ScheduleItemModel).options(orm.selectinload(ScheduleItemModel.itinerary)).where(
        ScheduleItemModel.id == item_id)
    result = await db.execute(stmt)
    item_to_update = result.scalars().first()

    if not item_to_update:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule item not found.")

    if item_to_update.itinerary.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have permission to edit this item.")

    if not (item_to_update.itinerary.start_date <= item_update.scheduled_date <= item_to_update.itinerary.end_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Scheduled date must be within the itinerary's range ({item_to_update.itinerary.start_date} to {item_to_update.itinerary.end_date}).")

    item_to_update.scheduled_date = item_update.scheduled_date
    item_to_update.scheduled_time = item_update.scheduled_time

    try:
        await db.commit()
        await db.refresh(item_to_update)
        return ScheduleItemResponse.from_orm(item_to_update)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update schedule item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update schedule item.")