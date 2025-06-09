from fastapi import APIRouter, HTTPException, Query
from typing import List
import os
import requests
from pydantic import BaseModel

router = APIRouter()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

class Place(BaseModel):
    id: str
    name: str
    rating: float
    image: str | None = None
    address: str | None = None
    priceLevel: int | None = None
    isOpen: bool | None = None
    types: List[str] | None = None
    placeId: str

@router.get("/recommendations/restaurants", response_model=List[Place])
async def get_restaurant_recommendations(
    latitude: float = Query(..., description="Latitude of user's location"),
    longitude: float = Query(..., description="Longitude of user's location")
):
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=2000&type=restaurant&key={GOOGLE_PLACES_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if data['status'] != 'OK':
            raise HTTPException(status_code=400, detail=f"Google Places API error: {data['status']}")

        places = []
        for place in data['results']:
            image = None
            if 'photos' in place and place['photos']:
                photo_ref = place['photos'][0]['photo_reference']
                image = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_ref}&key={GOOGLE_PLACES_API_KEY}"

            places.append({
                "id": place['place_id'],
                "name": place['name'],
                "rating": place.get('rating', 0),
                "image": image,
                "address": place.get('vicinity') or place.get('formatted_address'),
                "priceLevel": place.get('price_level'),
                "isOpen": place.get('opening_hours', {}).get('open_now') if 'opening_hours' in place else None,
                "types": place.get('types'),
                "placeId": place['place_id']
            })

        return places

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recommendations/attractions", response_model=List[Place])
async def get_attraction_recommendations(
    latitude: float = Query(..., description="Latitude of user's location"),
    longitude: float = Query(..., description="Longitude of user's location")
):
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=2000&type=tourist_attraction&key={GOOGLE_PLACES_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if data['status'] != 'OK':
            raise HTTPException(status_code=400, detail=f"Google Places API error: {data['status']}")

        places = []
        for place in data['results']:
            image = None
            if 'photos' in place and place['photos']:
                photo_ref = place['photos'][0]['photo_reference']
                image = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_ref}&key={GOOGLE_PLACES_API_KEY}"

            places.append({
                "id": place['place_id'],
                "name": place['name'],
                "rating": place.get('rating', 0),
                "image": image,
                "address": place.get('vicinity') or place.get('formatted_address'),
                "priceLevel": place.get('price_level'),
                "isOpen": place.get('opening_hours', {}).get('open_now') if 'opening_hours' in place else None,
                "types": place.get('types'),
                "placeId": place['place_id']
            })

        return places

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))