from pydantic import BaseModel
from typing import List, Optional
from datetime import date

# This model is used when creating a new itinerary
class ItineraryCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    budget: Optional[str] = None

# This model is used for individual items in the response
class ScheduleItem(BaseModel):
    place_id: str
    place_name: str
    place_type: Optional[str] = None
    place_address: Optional[str] = None
    place_rating: Optional[float] = None
    place_image: Optional[str] = None
    scheduled_date: str # Returning as string for API consistency
    scheduled_time: str
    duration_minutes: int

# This is the main response model for an itinerary
class Itinerary(BaseModel):
    id: int
    user_id: int
    type: str
    budget: str
    name: str
    start_date: date
    end_date: date
    schedule_items: List[ScheduleItem] = []

    class Config:
        from_attributes = True