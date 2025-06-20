from fastapi import APIRouter, HTTPException, Query, Depends, Request
from typing import List, Optional
import os
import requests
from pydantic import BaseModel
from models.user import UserResponse
from routes.auth import get_current_user_dependency
import logging
import time

from models.recommendations import Place

router = APIRouter()

DEFAULT_LATITUDE = 48.8566
DEFAULT_LONGITUDE = 2.3522

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PREFERENCE_MAPPING = {
    "tourist_type": {
        "Adventurous": ["amusement_park", "park", "hiking", "zoo"],
        "Relaxed": ["spa", "beach", "park"],
        "Cultural": ["museum", "art_gallery", "place_of_worship", "library"],
        "Foodie": ["restaurant", "cafe", "bakery", "food"]
    },
    "preferred_activities": {
        "Sightseeing": ["tourist_attraction", "point_of_interest"],
        "Nature": ["park", "zoo", "aquarium", "natural_feature"],
        "Shopping": ["shopping_mall", "clothing_store", "jewelry_store"],
        "Museum": ["museum", "art_gallery"]
    },
    "preferred_cuisines": {
        "Local": ["restaurant"],
        "International": ["restaurant"],
        "Street Food": ["restaurant", "meal_takeaway"],
        "Vegetarian": ["restaurant"]
    },
    "preferred_dining": {
        "Riverside Dining": ["restaurant"],
        "Night Market Vibes": ["restaurant", "meal_takeaway"],
        "Quiet Cafes": ["cafe"],
        "Scenic Views": ["restaurant"]
    }
}


def calculate_relevance(place_types: List[str], user_preferences: dict) -> float:
    if not user_preferences:
        return 0.5
    score = 0
    max_possible = 0
    for preference_category, mapping in PREFERENCE_MAPPING.items():
        user_prefs = user_preferences.get(preference_category, [])
        if not user_prefs:
            continue
        max_possible += len(user_prefs)
        for pref in user_prefs:
            preferred_types = mapping.get(pref, [])
            for preferred_type in preferred_types:
                if preferred_type in place_types:
                    score += 1
                    break
    return round(score / max_possible, 2) if max_possible > 0 else 0.5


def build_place_types_query(user_preferences: dict, place_category: str = "tourist_attraction") -> str:
    types = set()
    if place_category == "restaurant":
        types.add("restaurant")
        cuisines = user_preferences.get("preferred_cuisines", [])
        for cuisine in cuisines:
            types.update(PREFERENCE_MAPPING["preferred_cuisines"].get(cuisine, ["restaurant"]))
        dining_prefs = user_preferences.get("preferred_dining", [])
        for dining in dining_prefs:
            types.update(PREFERENCE_MAPPING["preferred_dining"].get(dining, ["restaurant"]))
        tourist_types = user_preferences.get("tourist_type", [])
        if "Foodie" in tourist_types:
            types.update(PREFERENCE_MAPPING["tourist_type"]["Foodie"])
    elif place_category == "tourist_attraction":
        tourist_types = user_preferences.get("tourist_type", [])
        for t_type in tourist_types:
            if t_type != "Foodie":
                types.update(PREFERENCE_MAPPING["tourist_type"].get(t_type, []))
        activities = user_preferences.get("preferred_activities", [])
        for activity in activities:
            types.update(PREFERENCE_MAPPING["preferred_activities"].get(activity, []))

    if place_category == "restaurant" and types:
        restaurant_types = [t for t in types if t in ["restaurant", "cafe", "bakery", "meal_takeaway"]]
        return "|".join(restaurant_types) if restaurant_types else "restaurant"
    elif types:
        return "|".join(types)
    else:
        return place_category


def process_results(all_place_results: List[dict], place_category: str, user_preferences: dict) -> List[Place]:
    places = []
    seen_names = set()
    for place in all_place_results:
        place_name = place.get('name')
        if not place_name or place_name in seen_names:
            continue
        place_types = place.get('types', [])
        is_food_place = any(t in place_types for t in ["restaurant", "cafe", "bakery", "meal_takeaway", "food"])
        if place_category == "restaurant" and not is_food_place:
            continue
        elif place_category == "tourist_attraction" and is_food_place:
            continue
        image = None
        if 'photos' in place and place['photos']:
            photo_ref = place['photos'][0]['photo_reference']
            image = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_ref}&key={GOOGLE_PLACES_API_KEY}"
        relevance = calculate_relevance(place_types, user_preferences)

        places.append(Place(
            id=place['place_id'],
            name=place_name,
            rating=place.get('rating', 0),
            image=image,
            address=place.get('vicinity') or place.get('formatted_address'),
            priceLevel=place.get('price_level'),
            isOpen=place.get('opening_hours', {}).get('open_now') if 'opening_hours' in place else None,
            types=place_types,
            placeId=place['place_id'],
            relevance_score=relevance
        ))
        seen_names.add(place_name)

    places.sort(key=lambda x: (x.relevance_score or 0, x.rating or 0), reverse=True)
    return places


async def get_personalized_places(
        user_preferences: dict,
        place_category: str = "tourist_attraction"
) -> List[Place]:
    all_results = []
    last_status = ""

    def fetch_pages(base_url: str):
        nonlocal last_status
        page_results = []
        url = base_url
        for _ in range(3):
            try:
                response = requests.get(url, timeout=10)
                data = response.json()
                last_status = data.get('status')
                if last_status == 'OK':
                    page_results.extend(data['results'])
                    next_page_token = data.get('next_page_token')
                    if next_page_token:
                        time.sleep(2)
                        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?pagetoken={next_page_token}&key={GOOGLE_PLACES_API_KEY}"
                    else:
                        break
                else:
                    break
            except (requests.exceptions.RequestException, requests.exceptions.Timeout):
                break
        return page_results

    try:
        types_query = build_place_types_query(user_preferences, place_category)
        primary_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=20000&type={types_query}&opennow=true&key={GOOGLE_PLACES_API_KEY}"

        all_results = fetch_pages(primary_url)
        if all_results:
            return process_results(all_results, place_category, user_preferences)

        fallback_type = "tourist_attraction" if place_category == "tourist_attraction" else "restaurant"
        fallback_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=20000&type={fallback_type}&opennow=true&key={GOOGLE_PLACES_API_KEY}"
        all_results = fetch_pages(fallback_url)

        if not all_results and last_status not in ['OK', 'ZERO_RESULTS']:
            raise HTTPException(status_code=400, detail=f"Google Places API error: {last_status}")

        return process_results(all_results, place_category, user_preferences)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_current_user_with_debug(request: Request):
    try:
        auth_header = request.headers.get("authorization")
        if not auth_header:
            return None
        token = auth_header.replace("Bearer ", "")
        user = await get_current_user_dependency(token)
        return user
    except Exception:
        return None


@router.get("/recommendations/restaurants", response_model=List[Place])
async def get_restaurant_recommendations(
        request: Request,
        current_user: Optional[UserResponse] = Depends(get_current_user_with_debug)
):
    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }
    return await get_personalized_places(user_preferences, place_category="restaurant")


@router.get("/recommendations/attractions", response_model=List[Place])
async def get_attraction_recommendations(
        request: Request,
        current_user: Optional[UserResponse] = Depends(get_current_user_with_debug)
):
    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }
    return await get_personalized_places(user_preferences, place_category="tourist_attraction")


@router.get("/recommendations/popular", response_model=List[Place])
async def get_popular_destinations():
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured.")
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=25000&type=tourist_attraction&key={GOOGLE_PLACES_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get('status')
        if status == 'OK':
            raw_places = [p for p in data.get('results', []) if p.get('rating', 0) >= 4.3 and 'photos' in p]
            places = process_results(raw_places, "tourist_attraction", {})
            places.sort(key=lambda x: x.rating or 0, reverse=True)
            return places[:10]
        else:
            raise HTTPException(status_code=400, detail=f"Google Places API error: {status}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to Google Places service: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")