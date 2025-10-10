# file: services/generation_service.py

import os
import json
import google.generativeai as genai
from typing import List, Dict, Optional

from app.models.user import UserResponse
from app.models.itinerary import ItineraryCreate
from app.models.recommendations import Place


# --- NEW HELPER FUNCTION ---
def _filter_places_by_budget(places: List[Place], budget: Optional[str]) -> List[Place]:
    """
    Filters a list of places based on a budget string.
    - "Low": price_level <= 2
    - "Medium": price_level <= 3
    - "High" or None: No filtering
    Google Price Levels: 0=Free, 1=Inexpensive, 2=Moderate, 3=Expensive, 4=Very Expensive
    """
    if not budget:
        return places

    budget = budget.lower()

    if budget == "low":
        max_level = 2
    elif budget == "medium":
        max_level = 3
    else:  # "high" or any other value
        return places

    filtered_list = []
    for place in places:
        # Keep attractions (often priceLevel is None) and restaurants within budget
        if place.priceLevel is None or place.priceLevel <= max_level:
            filtered_list.append(place)

    return filtered_list


def configure_gemini():
    api_key = os.getenv("GOOGLE_GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)


# --- UPDATED PROMPT GENERATION ---
def generate_itinerary_prompt(
        itinerary_details: ItineraryCreate,
        user_prefs: UserResponse,
        attractions: List[Place],
        restaurants: List[Place]
) -> str:
    # UPDATED: Include price_level in the data for the AI
    attraction_list = [
        {"id": p.id, "name": p.name, "types": p.types, "price_level": p.priceLevel}
        for p in attractions
    ]
    restaurant_list = [
        {"id": p.id, "name": p.name, "types": p.types, "price_level": p.priceLevel}
        for p in restaurants
    ]

    prompt = f"""
You are an expert travel planner. Your task is to create a balanced and exciting daily schedule for a trip based on user preferences and a list of available places.

**Itinerary Details:**
- Trip Name: {itinerary_details.name}
- Budget Guideline: {itinerary_details.budget or 'Not specified. Plan a balanced trip.'}
- Start Date: {itinerary_details.start_date.strftime('%Y-%m-%d')}
- End Date: {itinerary_details.end_date.strftime('%Y-%m-%d')}

**User Preferences:**
- Tourist Type: {', '.join(user_prefs.tourist_type or [])}
- Preferred Activities: {', '.join(user_prefs.preferred_activities or [])}
- Preferred Cuisines: {', '.join(user_prefs.preferred_cuisines or [])}
- Preferred Dining: {', '.join(user_prefs.preferred_dining or [])}
- Preferred Times: {', '.join(user_prefs.preferred_times or [])}

**Available Places:**
- Attractions: {json.dumps(attraction_list, indent=2)}
- Restaurants: {json.dumps(restaurant_list, indent=2)}

**Instructions & Rules:**
1.  **MANDATORY: Adhere strictly to the Budget Guideline.** Your primary goal is to respect the user's budget.
2.  **Budgeting Rules:**
    - The `price_level` for restaurants is a number from 0 (Free) to 4 (Very Expensive).
    - If Budget is 'Low', you MUST ONLY select restaurants with a `price_level` of 0, 1, or 2. Prioritize free attractions.
    - If Budget is 'Medium', you can select restaurants with a `price_level` up to 3.
    - If Budget is 'High', you can select any restaurant.
3.  **Place Selection:** You MUST ONLY select places from the 'Available Places' lists provided. Do not invent new places or use places not on the lists.
4.  **Schedule Logic:** Create a schedule for each day from the start_date to the end_date. Assign a logical time for each activity using a 24-hour format ("HH:MM").
5.  **Activity Pacing:** Estimate a reasonable duration in minutes for each activity (e.g., museum 120 mins, lunch 60 mins). Aim for 2-3 attractions and 2 meals (lunch, dinner) per day. Do not pack the schedule too tightly.
6.  **Final Output Format:** The final output MUST be a valid JSON array of objects, with no other text, comments, or explanations. Each object must have these exact keys: "place_id", "place_name", "scheduled_date" (in "YYYY-MM-DD" format), "scheduled_time" (in "HH:MM" format), and "duration_minutes".

**Example of required JSON output format:**
[
  {{
    "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
    "place_name": "Sydney Opera House",
    "scheduled_date": "2024-08-15",
    "scheduled_time": "10:00",
    "duration_minutes": 120
  }}
]

Now, generate the JSON schedule based on all these rules.
"""
    return prompt


# --- UPDATED MAIN FUNCTION ---
async def auto_generate_schedule(
        itinerary_details: ItineraryCreate,
        user: UserResponse,
        attractions: List[Place],
        restaurants: List[Place]
) -> List[Dict]:
    configure_gemini()

    # ADDED: Pre-filter the lists based on the budget before sending to the AI
    budget = itinerary_details.budget
    filtered_attractions = _filter_places_by_budget(attractions, budget)
    filtered_restaurants = _filter_places_by_budget(restaurants, budget)

    # Check if we have enough places to build a schedule
    if not filtered_attractions or not filtered_restaurants:
        print("Warning: Not enough places available after filtering by budget. Generation may fail.")
        # We can still proceed, the AI might use what's left, or we could return an error here.

    model = genai.GenerativeModel('gemini-flash-latest')

    # Pass the newly filtered lists to the prompt generator
    prompt = generate_itinerary_prompt(itinerary_details, user, filtered_attractions, filtered_restaurants)

    response = None
    try:
        response = await model.generate_content_async(prompt)
        # Clean the response to ensure it's valid JSON
        cleaned_response = response.text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]

        schedule_data = json.loads(cleaned_response.strip())

        if not isinstance(schedule_data, list):
            print(f"Error: Gemini response was not a JSON list. Response: {schedule_data}")
            return []

        return schedule_data
    except (json.JSONDecodeError, Exception) as e:
        print(f"Error generating or parsing Gemini response: {e}")
        if response:
            print(f"Raw Gemini response was: {response.text}")
        else:
            print("No response from Gemini.")
        return []