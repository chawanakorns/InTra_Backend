import os
import json
import google.generativeai as genai
from typing import List, Dict

from models.user import UserResponse
from models.itinerary import ItineraryCreate
from models.recommendations import Place


def configure_gemini():
    api_key = os.getenv("GOOGLE_GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)


def generate_itinerary_prompt(
        itinerary_details: ItineraryCreate,
        user_prefs: UserResponse,
        attractions: List[Place],
        restaurants: List[Place]
) -> str:
    attraction_list = [{"id": p.id, "name": p.name, "types": p.types} for p in attractions]
    restaurant_list = [{"id": p.id, "name": p.name, "types": p.types} for p in restaurants]

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

**Instructions:**
1.  Create a schedule for each day from the start_date to the end_date. Adhere to the Budget Guideline when selecting places if one is provided.
2.  Select a mix of attractions and restaurants from the provided lists ONLY. Do not invent new places.
3.  Assign a logical time for each activity. Use a 24-hour format ("HH:MM").
4.  Estimate a reasonable duration in minutes for each activity (e.g., museum 120 mins, lunch 60 mins).
5.  Try to include 2-3 attractions and 2 meals (lunch, dinner) per day. Avoid packing the schedule too tightly.
6.  The final output MUST be a valid JSON array of objects, with no other text or explanations. Each object must have these exact keys: "place_id", "place_name", "scheduled_date" (in "YYYY-MM-DD" format), "scheduled_time" (in "HH:MM" format), and "duration_minutes".

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

Now, generate the JSON schedule.
"""
    return prompt


async def auto_generate_schedule(
        itinerary_details: ItineraryCreate,
        user: UserResponse,
        attractions: List[Place],
        restaurants: List[Place]
) -> List[Dict]:
    configure_gemini()
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    prompt = generate_itinerary_prompt(itinerary_details, user, attractions, restaurants)

    response = None
    try:
        response = await model.generate_content_async(prompt)
        cleaned_response = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        schedule_data = json.loads(cleaned_response)
        if not isinstance(schedule_data, list):
            return []
        return schedule_data
    except Exception as e:
        print(f"Error generating or parsing Gemini response: {e}")
        if response:
            print(f"Raw Gemini response was: {response.text}")
        else:
            print("No response from Gemini.")
        return []