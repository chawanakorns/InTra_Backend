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

router = APIRouter()
logger = logging.getLogger(__name__)


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
            type=itinerary.type,
            budget=budget_value,  # Use the validated budget value
            name=itinerary.name,
            start_date=itinerary.start_date,
            end_date=itinerary.end_date,
        )
        db.add(db_itinerary)
        await db.commit()
        await db.refresh(db_itinerary)

        return ItineraryResponse(
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

        # Provide a default value for budget if it's missing from the request.
        budget_value = itinerary_data.budget if itinerary_data.budget else "Not Specified"

        db_itinerary = ItineraryModel(
            user_id=current_user.id,
            type=itinerary_data.type,
            budget=budget_value,  # Use the validated budget value
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