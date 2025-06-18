from fastapi import APIRouter, HTTPException, Query, Depends, Request
from typing import List, Optional
import os
import requests
from pydantic import BaseModel
from models.user import UserResponse
from routes.auth import get_current_user_dependency
import logging
import time

router = APIRouter()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Map user preferences to Google Places types
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
    relevance_score: float | None = None


def calculate_relevance(place_types: List[str], user_preferences: dict) -> float:
    """Calculate how relevant a place is to the user's preferences"""
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
                    break  # Match once per preference

    return round(score / max_possible, 2) if max_possible > 0 else 0.5


def build_place_types_query(user_preferences: dict, place_category: str = "tourist_attraction") -> str:
    """Build the type parameter for Google Places API based on user preferences and category"""
    types = set()

    # If it's a restaurant request, focus on restaurant-related preferences
    if place_category == "restaurant":
        # Add base restaurant type
        types.add("restaurant")

        # Add cuisine-based types
        cuisines = user_preferences.get("preferred_cuisines", [])
        for cuisine in cuisines:
            types.update(PREFERENCE_MAPPING["preferred_cuisines"].get(cuisine, ["restaurant"]))

        # Add dining preference types
        dining_prefs = user_preferences.get("preferred_dining", [])
        for dining in dining_prefs:
            types.update(PREFERENCE_MAPPING["preferred_dining"].get(dining, ["restaurant"]))

        # Add foodie tourist type
        tourist_types = user_preferences.get("tourist_type", [])
        if "Foodie" in tourist_types:
            types.update(PREFERENCE_MAPPING["tourist_type"]["Foodie"])

    # If it's attractions, focus on tourist attraction preferences
    elif place_category == "tourist_attraction":
        tourist_types = user_preferences.get("tourist_type", [])
        for t_type in tourist_types:
            if t_type != "Foodie":  # Exclude foodie for attractions
                types.update(PREFERENCE_MAPPING["tourist_type"].get(t_type, []))

        activities = user_preferences.get("preferred_activities", [])
        for activity in activities:
            types.update(PREFERENCE_MAPPING["preferred_activities"].get(activity, []))

    # Return the appropriate type query
    if place_category == "restaurant" and types:
        # For restaurants, prioritize restaurant types
        restaurant_types = [t for t in types if t in ["restaurant", "cafe", "bakery", "meal_takeaway"]]
        return "|".join(restaurant_types) if restaurant_types else "restaurant"
    elif types:
        return "|".join(types)
    else:
        return place_category


async def get_personalized_places(
        latitude: float,
        longitude: float,
        user_preferences: dict,
        place_category: str = "tourist_attraction"
) -> List[Place]:
    """
    Fetches places from Google Places API, handling pagination to get more results
    and falling back to a broader search if necessary.
    """
    all_results = []
    last_status = ""

    # Function to fetch pages of results
    def fetch_pages(base_url: str):
        nonlocal last_status
        page_results = []
        url = base_url
        # Fetch up to 3 pages (approx. 60 results)
        for _ in range(3):
            try:
                response = requests.get(url)
                data = response.json()
                last_status = data.get('status')

                if last_status == 'OK':
                    page_results.extend(data['results'])
                    next_page_token = data.get('next_page_token')
                    if next_page_token:
                        # Wait for the token to become valid
                        time.sleep(2)
                        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?pagetoken={next_page_token}&key={GOOGLE_PLACES_API_KEY}"
                    else:
                        # No more pages
                        break
                elif last_status == 'ZERO_RESULTS':
                    break  # No results, stop trying
                else:
                    logger.error(f"Google Places API error on a page: {last_status}")
                    break
            except Exception as e:
                logger.error(f"HTTP request failed during pagination: {str(e)}")
                break
        return page_results

    try:
        # Try specific types first
        types_query = build_place_types_query(user_preferences, place_category)
        logger.info(f"Searching for {place_category} with types: {types_query}")
        primary_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=20000&type={types_query}&opennow=true&key={GOOGLE_PLACES_API_KEY}"
        all_results = fetch_pages(primary_url)

        if all_results:
            return process_results(all_results, place_category, user_preferences)

        # If no results, fall back to a broader search
        logger.warning(
            f"No results for specific types: {types_query}. Falling back to general '{place_category}' search.")
        fallback_type = "tourist_attraction" if place_category == "tourist_attraction" else "restaurant"
        fallback_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius=20000&type={fallback_type}&opennow=true&key={GOOGLE_PLACES_API_KEY}"
        all_results = fetch_pages(fallback_url)

        if not all_results and last_status not in ['OK', 'ZERO_RESULTS']:
            logger.error(f"Google Places API error after fallback: {last_status}")
            raise HTTPException(status_code=400, detail=f"Google Places API error: {last_status}")

        places = process_results(all_results, place_category, user_preferences)
        logger.info(f"Found {len(places)} unique places using fallback query")
        return places

    except Exception as e:
        logger.error(f"Error getting personalized places: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def process_results(all_place_results: List[dict], place_category: str, user_preferences: dict) -> List[dict]:
    """
    Processes a list of place results, filters them, calculates relevance,
    and removes duplicates based on the place name.
    """
    places = []
    seen_names = set()  # Set to track names of places already added

    for place in all_place_results:
        place_name = place.get('name')
        # NEW: Skip if the place has no name or if the name has already been processed
        if not place_name or place_name in seen_names:
            continue

        # Filter restaurants vs attractions
        place_types = place.get('types', [])
        is_food_place = any(t in place_types for t in ["restaurant", "cafe", "bakery", "meal_takeaway", "food"])

        if place_category == "restaurant" and not is_food_place:
            continue
        elif place_category == "tourist_attraction" and is_food_place:
            continue

        # Create place object
        image = None
        if 'photos' in place and place['photos']:
            photo_ref = place['photos'][0]['photo_reference']
            image = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_ref}&key={GOOGLE_PLACES_API_KEY}"

        relevance = calculate_relevance(place_types, user_preferences)

        places.append({
            "id": place['place_id'],
            "name": place_name,
            "rating": place.get('rating', 0),
            "image": image,
            "address": place.get('vicinity') or place.get('formatted_address'),
            "priceLevel": place.get('price_level'),
            "isOpen": place.get('opening_hours', {}).get('open_now') if 'opening_hours' in place else None,
            "types": place_types,
            "placeId": place['place_id'],
            "relevance_score": relevance
        })
        # NEW: Add the name to our set of seen names
        seen_names.add(place_name)

    # Sort by relevance and then by rating
    places.sort(key=lambda x: (x.get('relevance_score', 0), x.get('rating', 0)), reverse=True)
    logger.info(
        f"Processed and de-duplicated {len(all_place_results)} results into {len(places)} unique {place_category} places")
    return places


async def get_current_user_with_debug(request: Request):
    try:
        auth_header = request.headers.get("authorization")
        logger.info(f"Authorization header present: {bool(auth_header)}")
        logger.info(f"Raw Authorization value: {auth_header}")  # New line
        if not auth_header:
            logger.warning("No authorization header found - returning anonymous user")
            return None
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
        logger.info(f"Extracted token length: {len(token) if token else 0}")
        user = await get_current_user_dependency(token)
        logger.info(f"Successfully authenticated user: {user.email}")
        return user
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}")
        return None


@router.get("/recommendations/restaurants", response_model=List[Place])
async def get_restaurant_recommendations(
        request: Request,
        latitude: float = Query(..., description="Latitude of user's location"),
        longitude: float = Query(..., description="Longitude of user's location"),
        current_user: Optional[UserResponse] = Depends(get_current_user_with_debug)
):
    user_email = current_user.email if current_user else 'Anonymous'
    logger.info(f"=== RESTAURANT RECOMMENDATIONS REQUEST ===")
    logger.info(f"User: {user_email}")
    logger.info(f"Location: {latitude}, {longitude}")

    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }
        logger.info(f"User preferences for restaurants: {user_preferences}")
    else:
        logger.info("No user authenticated - using default preferences")

    result = await get_personalized_places(
        latitude,
        longitude,
        user_preferences,
        place_category="restaurant"
    )

    logger.info(f"Returning {len(result)} restaurant recommendations for {user_email}")
    return result


@router.get("/recommendations/attractions", response_model=List[Place])
async def get_attraction_recommendations(
        request: Request,
        latitude: float = Query(..., description="Latitude of user's location"),
        longitude: float = Query(..., description="Longitude of user's location"),
        current_user: Optional[UserResponse] = Depends(get_current_user_with_debug)
):
    user_email = current_user.email if current_user else 'Anonymous'
    logger.info(f"=== ATTRACTION RECOMMENDATIONS REQUEST ===")
    logger.info(f"User: {user_email}")
    logger.info(f"Location: {latitude}, {longitude}")

    user_preferences = {}
    if current_user:
        user_preferences = {
            "tourist_type": current_user.tourist_type or [],
            "preferred_activities": current_user.preferred_activities or [],
            "preferred_cuisines": current_user.preferred_cuisines or [],
            "preferred_dining": current_user.preferred_dining or [],
            "preferred_times": current_user.preferred_times or []
        }
        logger.info(f"User preferences for attractions: {user_preferences}")
    else:
        logger.info("No user authenticated - using default preferences")

    result = await get_personalized_places(
        latitude,
        longitude,
        user_preferences,
        place_category="tourist_attraction"
    )

    logger.info(f"Returning {len(result)} attraction recommendations for {user_email}")
    return result


# Test endpoint to check auth
@router.get("/test-auth")
async def test_auth(current_user: UserResponse = Depends(get_current_user_dependency)):
    return {"message": f"Auth working for user: {current_user.email}"}