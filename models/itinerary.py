from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from pydantic import ConfigDict

class ItineraryBase(BaseModel):
    name: str
    start_date: date
    end_date: date
    budget: Optional[str] = None

class ItineraryCreate(ItineraryBase):
    pass

class ScheduleItemUpdate(BaseModel):
    scheduled_date: date
    scheduled_time: str

class ScheduleItem(BaseModel):
    id: int
    place_id: str
    place_name: str
    place_type: Optional[str] = None
    place_address: Optional[str] = None
    place_rating: Optional[float] = None
    place_image: Optional[str] = None
    scheduled_date: date
    scheduled_time: str
    duration_minutes: int

    model_config = ConfigDict(from_attributes=True)

class Itinerary(ItineraryBase):
    id: int
    user_id: int
    type: str
    schedule_items: List[ScheduleItem] = []

    model_config = ConfigDict(from_attributes=True)