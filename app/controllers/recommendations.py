from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
import os
import httpx
import google.generativeai as genai
import asyncio
from pydantic import BaseModel
from app.models.recommendations import Place
from app.services.firebase_auth import get_optional_current_user
from app.database.models import User
import logging
import time

router = APIRouter()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.error("FATAL: GOOGLE_GEMINI_API_KEY is not set in the environment.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

description_cache = {}

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


class PlaceDetails(Place):
    description: str


def calculate_relevance(place_types: List[str], user_preferences: dict) -> float:
    if not user_preferences: return 0.5
    score, max_possible = 0, 0
    for category, mapping in PREFERENCE_MAPPING.items():
        user_prefs = user_preferences.get(category, [])
        if not user_prefs: continue
        max_possible += len(user_prefs)
        for pref in user_prefs:
            if any(pt in place_types for pt in mapping.get(pref, [])):
                score += 1
                break
    return round(score / max_possible, 2) if max_possible > 0 else 0.5


def build_place_types_query(user_preferences: dict, place_category: str = "tourist_attraction") -> str:
    types = set()
    if place_category == "restaurant":
        types.add("restaurant")
        if "Foodie" in user_preferences.get("tourist_type", []):
            types.update(PREFERENCE_MAPPING["tourist_type"]["Foodie"])
        for cuisine in user_preferences.get("preferred_cuisines", []):
            types.update(PREFERENCE_MAPPING["preferred_cuisines"].get(cuisine, []))
        for dining in user_preferences.get("preferred_dining", []):
            types.update(PREFERENCE_MAPPING["preferred_dining"].get(dining, []))
        return "|".join(t for t in types if t in ["restaurant", "cafe", "bakery", "meal_takeaway"]) or "restaurant"
    elif place_category == "tourist_attraction":
        for t_type in user_preferences.get("tourist_type", []):
            if t_type != "Foodie":
                types.update(PREFERENCE_MAPPING["tourist_type"].get(t_type, []))
        for activity in user_preferences.get("preferred_activities", []):
            types.update(PREFERENCE_MAPPING["preferred_activities"].get(activity, []))
    return "|".join(types) or place_category


def process_results(all_place_results: List[dict], place_category: str, user_preferences: dict) -> List[dict]:
    places, seen_names = [], set()
    for place in all_place_results:
        name = place.get('name')
        if not name or name in seen_names: continue
        types = place.get('types', [])
        is_food = any(t in types for t in ["restaurant", "cafe", "bakery", "meal_takeaway", "food"])
        if (place_category == "restaurant" and not is_food) or (place_category == "tourist_attraction" and is_food):
            continue
        image = None
        if place.get('photos'):
            ref = place['photos'][0]['photo_reference']
            image = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={ref}&key={GOOGLE_PLACES_API_KEY}"
        places.append({
            "id": place['place_id'], "name": name, "rating": place.get('rating', 0),
            "image": image, "address": place.get('vicinity') or place.get('formatted_address'),
            "priceLevel": place.get('price_level'),
            "isOpen": place.get('opening_hours', {}).get('open_now'),
            "types": types, "placeId": place['place_id'],
            "relevance_score": calculate_relevance(types, user_preferences)
        })
        seen_names.add(name)
    places.sort(key=lambda x: (x.get('relevance_score', 0), x.get('rating', 0)), reverse=True)
    return places


async def get_personalized_places(latitude: float, longitude: float, user_preferences: dict, place_category: str) -> \
List[Place]:
    last_status = ""

    async def fetch_pages(client: httpx.AsyncClient, url: str):
        nonlocal last_status
        results = []
        current_url = url
        for _ in range(3):
            try:
                res = await client.get(current_url, timeout=10)
                data = res.json()
                last_status = data.get('status')
                if last_status == 'OK':
                    results.extend(data['results'])
                    token = data.get('next_page_token')
                    if token:
                        await asyncio.sleep(2)
                        current_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?pagetoken={token}&key={GOOGLE_PLACES_API_KEY}"
                    else:
                        break
                else:
                    break
            except (httpx.RequestError, httpx.TimeoutException):
                break
        return results

    try:
        types_query = build_place_types_query(user_preferences, place_category)
        logger.info(f"Searching for {place_category} with types: {types_query} near ({latitude}, {longitude})")
        async with httpx.AsyncClient() as client:
            url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=20000&type={types_query}&opennow=true&key={GOOGLE_PLACES_API_KEY}"
            results = await fetch_pages(client, url)
            if not results:
                logger.warning(f"No results for specific types. Falling back to general search for {place_category}.")
                fallback_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=20000&type={place_category}&opennow=true&key={GOOGLE_PLACES_API_KEY}"
                results = await fetch_pages(client, fallback_url)

        if not results and last_status not in ['OK', 'ZERO_RESULTS']:
            raise HTTPException(status_code=400, detail=f"Google Places API error: {last_status}")
        return [Place(**p) for p in process_results(results, place_category, user_preferences)]
    except Exception as e:
        logger.error(f"Error in get_personalized_places: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommendations/restaurants", response_model=List[Place])
async def get_restaurant_recommendations(latitude: float = Query(...), longitude: float = Query(...),
                                         current_user: Optional[User] = Depends(get_optional_current_user)):
    prefs = {}
    if current_user:
        prefs = {k: getattr(current_user, k) or [] for k in
                 ["tourist_type", "preferred_activities", "preferred_cuisines", "preferred_dining", "preferred_times"]}
    return await get_personalized_places(
        latitude=latitude,
        longitude=longitude,
        user_preferences=prefs,
        place_category="restaurant"
    )


@router.get("/recommendations/attractions", response_model=List[Place])
async def get_attraction_recommendations(latitude: float = Query(...), longitude: float = Query(...),
                                         current_user: Optional[User] = Depends(get_optional_current_user)):
    prefs = {}
    if current_user:
        prefs = {k: getattr(current_user, k) or [] for k in
                 ["tourist_type", "preferred_activities", "preferred_cuisines", "preferred_dining", "preferred_times"]}
    return await get_personalized_places(
        latitude=latitude,
        longitude=longitude,
        user_preferences=prefs,
        place_category="tourist_attraction"
    )


@router.get("/recommendations/popular", response_model=List[Place])
async def get_popular_destinations(latitude: float = Query(...), longitude: float = Query(...)):
    if not GOOGLE_PLACES_API_KEY: raise HTTPException(status_code=500, detail="Server API key not configured.")
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=25000&type=tourist_attraction&key={GOOGLE_PLACES_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            res.raise_for_status()
        data = res.json()
        if data.get('status') == 'OK':
            raw = [p for p in data.get('results', []) if p.get('rating', 0) >= 4.3 and 'photos' in p]
            processed = process_results(raw, "tourist_attraction", {})
            processed.sort(key=lambda x: x.get('rating', 0), reverse=True)
            return [Place(**p) for p in processed[:10]]
        else:
            raise HTTPException(status_code=400, detail=f"Google Places API error: {data.get('status')}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to Google Places: {e}")


@router.get("/recommendations/place/{place_id}/details", response_model=PlaceDetails)
async def get_place_details_and_description(place_id: str):
    if place_id in description_cache: return PlaceDetails(**description_cache[place_id])
    fields = "name,place_id,formatted_address,rating,types,photos,opening_hours,price_level,reviews"
    url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields={fields}&key={GOOGLE_PLACES_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            res.raise_for_status()
        details = res.json().get('result')
        if not details: raise HTTPException(status_code=404, detail="Place not found.")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Could not connect to Google Places.")

    try:
        if not GEMINI_API_KEY: raise ValueError("Gemini API key not configured.")
        reviews = " ".join([r.get('text', '') for r in details.get('reviews', [])[:2]])
        prompt = f"Generate a compelling, 2-paragraph travel description for a mobile app. Details: Name: {details.get('name')}, Types: {', '.join(details.get('types', []))}, Review Summary: \"{reviews}\". Be inviting and focus on atmosphere. No addresses or hours."
        gen_res = await generation_model.generate_content_async(prompt)
        desc = gen_res.text
    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        desc = f"Discover the charm of {details.get('name')}. A must-visit spot offering unique experiences."

    photo_url = None
    if details.get('photos'):
        ref = details['photos'][0]['photo_reference']
        photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={ref}&key={GOOGLE_PLACES_API_KEY}"

    full_details = {
        "id": details['place_id'], "placeId": details['place_id'],
        "name": details.get('name'), "rating": details.get('rating'),
        "address": details.get('formatted_address'),
        "isOpen": details.get('opening_hours', {}).get('open_now'),
        "types": details.get('types'), "image": photo_url,
        "priceLevel": details.get('price_level'),
        "description": desc.strip(), "relevance_score": 0.5
    }
    response_model = PlaceDetails(**full_details)
    description_cache[place_id] = response_model.model_dump()
    return response_model


@router.get("/recommendations/directions")
async def get_directions(
        origin: str = Query(..., description="User's current location as 'latitude,longitude'"),
        destination_place_id: str = Query(..., description="Google Place ID of the destination")
):
    """
    Provides a route polyline from an origin to a destination.
    """
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured.")

    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination=place_id:{destination_place_id}&key={GOOGLE_PLACES_API_KEY}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()

        data = response.json()
        if data.get('status') == 'OK' and data.get('routes'):
            # Extract the encoded polyline string from the first route
            polyline = data['routes'][0]['overview_polyline']['points']
            return {"encoded_polyline": polyline}
        else:
            logger.error(f"Google Directions API error: {data.get('status')} - {data.get('error_message', '')}")
            raise HTTPException(status_code=400, detail="Could not find a route to the destination.")
    except httpx.RequestError as e:
        logger.error(f"HTTP request to Google Directions failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Could not connect to the directions service.")
    except Exception as e:
        logger.error(f"Error getting directions: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")