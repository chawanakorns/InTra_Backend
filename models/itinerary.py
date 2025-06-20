from pydantic import BaseModel
from datetime import date
from typing import List, Optional

class ItineraryBase(BaseModel):
    type: str
    budget: Optional[str] = None
    name: str
    start_date: date
    end_date: date

class ItineraryCreate(ItineraryBase):
    pass

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

class Itinerary(ItineraryBase):
    id: int
    user_id: int
    schedule_items: List[ScheduleItem]

    class Config:
        from_attributes = True