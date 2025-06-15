from pydantic import BaseModel
from datetime import date
from typing import List, Optional

class ItineraryBase(BaseModel):
    type: str
    budget: str
    name: str
    start_date: date
    end_date: date
    schedule: Optional[List] = None

class ItineraryCreate(ItineraryBase):
    pass

class Itinerary(ItineraryBase):
    id: int
    user_id: int

    class Config:
        from_attributes = True