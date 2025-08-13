# file: scripts/notification_scheduler.py

import asyncio
from datetime import datetime, timedelta, time
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
import os
import httpx
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials
import sys

# Add the project root to the Python path to allow absolute imports from the 'app' package
# This is necessary because we are running this file as a standalone script.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.database.connection import get_db_session
from app.database.models import ScheduleItem, User, Itinerary, Notification, SentOpportunity

# Initialize Firebase Admin SDK if it hasn't been already
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("../serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        print("Scheduler: Firebase Admin SDK initialized.")
    except Exception as e:
        print(f"Scheduler: FATAL Error initializing Firebase Admin SDK: {e}")

# Load environment variables from .env file
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")


# --- HELPER FUNCTIONS ---

async def get_travel_time_seconds(origin: str, destination_place_id: str) -> int:
    """Calculates travel time between two points using Google Directions API."""
    if not GOOGLE_MAPS_API_KEY:
        print("WARNING: GOOGLE_PLACES_API_KEY not set. Using default travel time of 15 mins.")
        return 15 * 60

    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination=place_id:{destination_place_id}&key={GOOGLE_MAPS_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data['status'] == 'OK':
                return data['routes'][0]['legs'][0]['duration']['value']
    except Exception as e:
        print(f"Error fetching travel time: {e}")
    return 15 * 60


async def send_expo_push_notification(token: str, title: str, body: str, data: dict):
    """Sends a push notification to a specific user via Expo's Push API."""
    expo_push_url = "https://exp.host/--/api/v2/push/send"
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate',
        'Content-Type': 'application/json',
    }
    payload = {
        'to': token,
        'sound': 'default',
        'title': title,
        'body': body,
        'data': data,
        'channelId': 'default',  # Required for custom Android notification channels
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(expo_push_url, json=payload, headers=headers)
            response.raise_for_status()
            print(f" -> Successfully sent notification via Expo. Response: {response.json()}")
        except httpx.HTTPStatusError as e:
            print(
                f" -> Failed to send notification. Expo server responded with {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            print(f" -> An error occurred while requesting Expo's push service: {e}")


async def _get_place_coordinates(place_id: str) -> dict | None:
    """Fetches the latitude and longitude for a given Google Place ID."""
    if not GOOGLE_MAPS_API_KEY: return None
    url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=geometry&key={GOOGLE_MAPS_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data['status'] == 'OK':
                return data['result']['geometry']['location']
    except Exception as e:
        print(f"Error fetching coordinates for place {place_id}: {e}")
    return None


async def _get_google_weather_forecast(lat: float, lon: float) -> dict | None:
    """Gets the hourly weather forecast using the official Google Weather API."""
    if not GOOGLE_MAPS_API_KEY: return None

    url = "https://weather.googleapis.com/v1/forecast:getHourlyForecast"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY}
    payload = {"location": {"latitude": lat, "longitude": lon}, "hours": 24}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error fetching Google Weather forecast: {e}")
    return None


# --- CORE SCHEDULER FUNCTIONS ---

async def check_and_send_smart_alerts():
    """Checks for upcoming itinerary items and sends departure alerts."""
    print(f"[{datetime.now()}] Running Smart Itinerary Alert check (for users with this setting ON)...")
    async with get_db_session() as db:
        now = datetime.now()
        stmt = (
            select(ScheduleItem)
            .join(Itinerary).join(User)
            .options(selectinload(ScheduleItem.itinerary).selectinload(Itinerary.user))
            .where(
                ScheduleItem.scheduled_date == now.date(),
                ScheduleItem.notification_sent == False,
                User.fcm_token != None,
                User.allow_smart_alerts == True
            )
        )
        result = await db.execute(stmt)
        upcoming_items = result.scalars().unique().all()

        if not upcoming_items:
            print(" -> No upcoming items found for smart alerts.")
            return

        print(f" -> Found {len(upcoming_items)} upcoming items to process for smart alerts.")
        for item in upcoming_items:
            item_time = time.fromisoformat(item.scheduled_time)
            if not (now.time() <= item_time <= (now + timedelta(minutes=90)).time()):
                continue

            user = item.itinerary.user
            travel_time_sec = await get_travel_time_seconds("48.8584,2.2945", item.place_id)  # Placeholder origin
            notification_time = datetime.combine(item.scheduled_date, item_time) - timedelta(
                minutes=(travel_time_sec // 60 + 10))

            if now >= notification_time:
                print(f" -> Sending smart alert for '{item.place_name}' to {user.email}...")
                await send_expo_push_notification(
                    token=user.fcm_token,
                    title=f"Time for {item.place_name}",
                    body=f"Time to head out! It's a {travel_time_sec // 60}-minute ride. Tap for directions.",
                    data={"screen": "itinerary", "itineraryId": str(item.itinerary.id), "itemId": str(item.id)}
                )
                item.notification_sent = True
                await db.commit()


async def check_for_opportunities():
    """Finds users on active trips and suggests highly-rated nearby places."""
    print(f"[{datetime.now()}] Running Opportunity Alert check (for users with this setting ON)...")
    async with get_db_session() as db:
        today = datetime.now().date()

        subquery = (
            select(User.id)
            .join(User.itineraries)
            .where(
                User.allow_opportunity_alerts == True,
                User.fcm_token != None,
                Itinerary.start_date <= today,
                Itinerary.end_date >= today
            )
            .distinct()
            .scalar_subquery()
        )
        stmt = select(User).where(User.id.in_(subquery))

        result = await db.execute(stmt)
        users_on_trip = result.scalars().all()

        if not users_on_trip:
            print(" -> No active users found for opportunity alerts.")
            return

        print(f" -> Found {len(users_on_trip)} users eligible for opportunity alerts.")
        for user in users_on_trip:
            first_item_stmt = select(ScheduleItem).where(ScheduleItem.itinerary.has(user_id=user.id),
                                                         ScheduleItem.scheduled_date == today).order_by(
                ScheduleItem.scheduled_time).limit(1)
            first_item_today = (await db.execute(first_item_stmt)).scalars().first()
            if not first_item_today: continue

            coords = await _get_place_coordinates(first_item_today.place_id)
            if not coords: continue

            search_query = " OR ".join(user.preferred_activities or ['tourist_attraction'])
            url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={search_query}&location={coords['lat']},{coords['lng']}&radius=2000&key={GOOGLE_MAPS_API_KEY}"

            async with httpx.AsyncClient() as client:
                response = await client.get(url)
            if response.status_code != 200: continue
            places = response.json().get('results', [])

            sent_ops_result = await db.execute(
                select(SentOpportunity.place_id).where(SentOpportunity.user_id == user.id))
            itinerary_places_result = await db.execute(
                select(ScheduleItem.place_id).where(ScheduleItem.itinerary.has(user_id=user.id)))
            seen_place_ids = set(sent_ops_result.scalars().all()) | set(itinerary_places_result.scalars().all())

            best_opportunity = next((p for p in sorted(places, key=lambda p: p.get('rating', 0), reverse=True) if
                                     p['place_id'] not in seen_place_ids and p.get('rating', 0) >= 4.5), None)

            if best_opportunity:
                print(f" -> Found opportunity '{best_opportunity['name']}' for user {user.email}")
                title = "✨ Opportunity Nearby!"
                body = f"A highly-rated spot, '{best_opportunity['name']}', is near your current plans. Tap to see more."
                await send_expo_push_notification(user.fcm_token, title, body,
                                                  {"placeId": best_opportunity['place_id']})
                db.add_all([
                    Notification(user_id=user.id, title=title, body=body),
                    SentOpportunity(user_id=user.id, place_id=best_opportunity['place_id'])
                ])
                await db.commit()


async def check_for_real_time_tips():
    """Checks for upcoming outdoor activities and sends a weather warning if rain is expected."""
    print(f"[{datetime.now()}] Running Real-Time Tips check (for users with this setting ON)...")
    outdoor_types = {'park', 'zoo', 'natural_feature', 'tourist_attraction', 'hiking'}

    async with get_db_session() as db:
        now = datetime.now()
        stmt = (
            select(ScheduleItem).join(Itinerary).join(User).options(
                selectinload(ScheduleItem.itinerary).selectinload(Itinerary.user))
            .where(
                User.allow_real_time_tips == True,
                User.fcm_token != None,
                ScheduleItem.scheduled_date == now.date(),
                ScheduleItem.scheduled_time >= now.strftime('%H:%M'),
                ScheduleItem.scheduled_time <= (now + timedelta(hours=6)).strftime('%H:%M'),
                and_(*[ScheduleItem.place_type.ilike(f'%{ot}%') for ot in outdoor_types])
            )
        )
        outdoor_items = (await db.execute(stmt)).scalars().unique().all()

        if not outdoor_items:
            print(" -> No upcoming outdoor activities found to check for weather tips.")
            return

        print(f" -> Found {len(outdoor_items)} upcoming outdoor activities to check.")
        for item in outdoor_items:
            coords = await _get_place_coordinates(item.place_id)
            if not coords: continue

            forecast_data = await _get_google_weather_forecast(coords['lat'], coords['lng'])
            if not forecast_data or not forecast_data.get('hourlyForecasts'): continue

            item_dt = datetime.combine(now.date(), time.fromisoformat(item.scheduled_time))
            rain_imminent = any(
                'rain' in hf.get('description', '').lower()
                for hf in forecast_data['hourlyForecasts']
                if abs((datetime.fromisoformat(hf['dateTime'].replace('Z', '+00:00')).replace(
                    tzinfo=None) - item_dt).total_seconds()) < 7200
            )

            if rain_imminent:
                print(
                    f" -> Rain detected for '{item.place_name}'. Finding alternative for {item.itinerary.user.email}...")
                url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query=indoor%20attraction&location={coords['lat']},{coords['lng']}&radius=3000&key={GOOGLE_MAPS_API_KEY}"
                async with httpx.AsyncClient() as client:
                    response = await client.get(url)
                if response.status_code != 200: continue

                if alternatives := response.json().get('results'):
                    alt = alternatives[0]
                    title = "☔️ Heads Up: Rain Expected!"
                    body = f"Rain is in the forecast for your visit to '{item.place_name}'. Maybe check out '{alt['name']}' instead?"

                    await send_expo_push_notification(item.itinerary.user.fcm_token, title, body,
                                                      {"placeId": alt['place_id']})
                    db.add(Notification(user_id=item.itinerary.user.id, title=title, body=body))
                    await db.commit()


async def main_scheduler_loop():
    """The main event loop for the scheduler daemon."""
    while True:
        print(f"\n--- [{datetime.now()}] STARTING NEW SCHEDULER CYCLE ---")
        try:
            await check_and_send_smart_alerts()
            await check_for_opportunities()
            await check_for_real_time_tips()
        except Exception as e:
            print(f"An error occurred in the scheduler loop: {e}")

        print(f"--- Scheduler cycle finished. Waiting for 15 minutes. ---\n")
        await asyncio.sleep(900)


if __name__ == "__main__":
    print("Starting notification scheduler...")
    asyncio.run(main_scheduler_loop())