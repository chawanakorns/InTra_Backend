from pydantic import BaseModel
from typing import List, Optional

class Place(BaseModel):
    id: str
    name: str
    rating: float
    image: Optional[str] = None
    address: Optional[str] = None
    priceLevel: Optional[int] = None
    isOpen: Optional[bool] = None
    types: Optional[List[str]] = None
    placeId: str
    relevance_score: Optional[float] = None