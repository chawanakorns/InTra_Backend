from fastapi import APIRouter, HTTPException, Query, Depends, Request
from typing import List, Optional
import os
import requests
import google.generativeai as genai
from pydantic import BaseModel
from models.user import UserResponse
from models.recommendations import Place
from routes.auth import get_current_user_dependency
import logging
import time

router = APIRouter()

# --- Centralized Location Constants ---
DEFAULT_LATITUDE = 48.8566
DEFAULT_LONGITUDE = 2.3522

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.error("FATAL: GOOGLE_GEMINI_API_KEY is not set in the environment.")
    # In a real production app, you might want to raise an error here to stop the server
    # raise ValueError("GOOGLE_GEMINI_API_KEY environment variable not set")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# Simple in-memory cache. For production, consider using Redis or a database.
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
        logger.info(f"Searching for {place_category} with types: {types_query}")

        primary_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=20000&type={types_query}&opennow=true&key={GOOGLE_PLACES_API_KEY}"

        all_results = fetch_pages(primary_url)
        if all_results:
            # --- FIX: Convert dicts to Place objects before returning ---
            processed_places = process_results(all_results, place_category, user_preferences)
            return [Place(**p) for p in processed_places]

        logger.warning(f"No results for specific types: {types_query}. Falling back to general search.")
        fallback_type = "tourist_attraction" if place_category == "tourist_attraction" else "restaurant"

        fallback_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=20000&type={fallback_type}&opennow=true&key={GOOGLE_PLACES_API_KEY}"

        all_results = fetch_pages(fallback_url)
        if not all_results and last_status not in ['OK', 'ZERO_RESULTS']:
            raise HTTPException(status_code=400, detail=f"Google Places API error: {last_status}")

        places_as_dicts = process_results(all_results, place_category, user_preferences)
        logger.info(f"Found {len(places_as_dicts)} unique places using fallback query")
        # --- FIX: Convert dicts to Place objects before returning ---
        return [Place(**p) for p in places_as_dicts]
    except Exception as e:
        logger.error(f"Error getting personalized places: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def process_results(all_place_results: List[dict], place_category: str, user_preferences: dict) -> List[dict]:
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
        places.append({
            "id": place['place_id'], "name": place_name, "rating": place.get('rating', 0),
            "image": image, "address": place.get('vicinity') or place.get('formatted_address'),
            "priceLevel": place.get('price_level'),
            "isOpen": place.get('opening_hours', {}).get('open_now') if 'opening_hours' in place else None,
            "types": place_types, "placeId": place['place_id'], "relevance_score": relevance
        })
        seen_names.add(place_name)
    places.sort(key=lambda x: (x.get('relevance_score', 0), x.get('rating', 0)), reverse=True)
    logger.info(f"Processed {len(all_place_results)} results into {len(places)} unique {place_category} places")
    return places


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
    user_email = current_user.email if current_user else 'Anonymous'
    logger.info("=== RESTAURANT RECOMMENDATIONS REQUEST ===")
    logger.info(f"User: {user_email}, Location: Hardcoded to ({DEFAULT_LATITUDE}, {DEFAULT_LONGITUDE})")

    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }

    result = await get_personalized_places(user_preferences, place_category="restaurant")
    logger.info(f"Returning {len(result)} restaurant recommendations for {user_email}")
    return result


@router.get("/recommendations/attractions", response_model=List[Place])
async def get_attraction_recommendations(
        request: Request,
        current_user: Optional[UserResponse] = Depends(get_current_user_with_debug)
):
    user_email = current_user.email if current_user else 'Anonymous'
    logger.info("=== ATTRACTION RECOMMENDATIONS REQUEST ===")
    logger.info(f"User: {user_email}, Location: Hardcoded to ({DEFAULT_LATITUDE}, {DEFAULT_LONGITUDE})")

    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }

    result = await get_personalized_places(user_preferences, place_category="tourist_attraction")
    logger.info(f"Returning {len(result)} attraction recommendations for {user_email}")
    return result


@router.get("/recommendations/popular", response_model=List[Place])
async def get_popular_destinations():
    logger.info("=== POPULAR DESTINATIONS REQUEST ===")
    logger.info(f"Searching near hardcoded location: ({DEFAULT_LATITUDE}, {DEFAULT_LONGITUDE})")

    if not GOOGLE_PLACES_API_KEY:
        logger.error("FATAL: GOOGLE_PLACES_API_KEY is not set.")
        raise HTTPException(status_code=500, detail="Server API key not configured.")

    places = []
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={DEFAULT_LATITUDE},{DEFAULT_LONGITUDE}&radius=25000&type=tourist_attraction&key={GOOGLE_PLACES_API_KEY}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        status = data.get('status')
        if status == 'OK':
            raw_places = [p for p in data.get('results', []) if p.get('rating', 0) >= 4.3 and 'photos' in p]
            # --- FIX: Convert dicts to Place objects before returning ---
            places_as_dicts = process_results(raw_places, "tourist_attraction", {})
            places_as_dicts.sort(key=lambda x: x.get('rating', 0), reverse=True)
            places = [Place(**p) for p in places_as_dicts]
            logger.info(f"Found {len(places)} popular destinations.")
        else:
            logger.error(f"Google Places API error: {status} - {data.get('error_message', '')}")
            raise HTTPException(status_code=400, detail=f"Google Places API error: {status}")
    except requests.exceptions.Timeout:
        logger.error("Request to Google Places API timed out.")
        raise HTTPException(status_code=504, detail="Request to external service timed out.")
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP request to Google Places failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Could not connect to Google Places service.")
    except Exception as e:
        logger.error(f"Error getting popular destinations: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")
    return places[:10]


@router.get("/recommendations/place/{place_id}/details", response_model=PlaceDetails)
async def get_place_details_and_description(place_id: str):
    if place_id in description_cache:
        cached_data = description_cache[place_id]
        logger.info(f"Serving cached details for place_id: {place_id}")
        # --- FIX: Ensure cached data is also a model instance ---
        return PlaceDetails(**cached_data) if isinstance(cached_data, dict) else cached_data

    logger.info(f"Fetching fresh details from Google Places for place_id: {place_id}")
    fields = "name,place_id,formatted_address,rating,types,photos,opening_hours,price_level,reviews"
    details_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields={fields}&key={GOOGLE_PLACES_API_KEY}"

    try:
        response = requests.get(details_url, timeout=10)
        response.raise_for_status()
        place_details = response.json().get('result')

        if not place_details:
            raise HTTPException(status_code=404, detail="Place not found.")

    except requests.exceptions.RequestException as e:
        logger.error(f"Google Places Details API request failed: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to Google Places service.")

    try:
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API key is not configured on the server.")

        reviews_summary = " ".join([review.get('text', '') for review in place_details.get('reviews', [])[:2]])
        place_types = ", ".join(place_details.get('types', []))

        prompt = f"""
        Generate a compelling and engaging travel description for a mobile app. The description should be about 2-3 short paragraphs long.

        Use the following details to create the description:
        - Place Name: {place_details.get('name')}
        - Place Types: {place_types}
        - Key Information: Known for being a {'restaurant' if 'restaurant' in place_types else 'tourist attraction'}.
        - Summary of recent reviews: "{reviews_summary}"

        Write the description in a friendly, inviting tone, as if recommending it to a traveler.
        Focus on the atmosphere and what makes it special. Do not include address or opening hours.
        """

        logger.info(f"Generating description with Gemini for: {place_details.get('name')}")
        gemini_response = generation_model.generate_content(prompt)
        generated_description = gemini_response.text

    except Exception as e:
        logger.error(f"Gemini description generation failed: {e}")
        generated_description = f"Discover the charm of {place_details.get('name')}. This spot is a must-visit, offering unique experiences and beautiful sights. Whether you're a local or a tourist, you'll find something to love here."

    photo_url = None
    if 'photos' in place_details and place_details['photos']:
        photo_ref = place_details['photos'][0]['photo_reference']
        photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_ref}&key={GOOGLE_PLACES_API_KEY}"

    full_details = {
        "id": place_details['place_id'],
        "placeId": place_details['place_id'],
        "name": place_details.get('name'),
        "rating": place_details.get('rating'),
        "address": place_details.get('formatted_address'),
        "isOpen": place_details.get('opening_hours', {}).get('open_now'),
        "types": place_details.get('types'),
        "image": photo_url,
        "priceLevel": place_details.get('price_level'),
        "description": generated_description.strip(),
        "relevance_score": 0.5
    }

    response_model = PlaceDetails(**full_details)
    description_cache[place_id] = response_model.dict()  # Cache the dict representation

    return response_model