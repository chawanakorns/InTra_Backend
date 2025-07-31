# file: services/notification_scheduler.py

import asyncio
from datetime import datetime, timedelta, time
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import os
import httpx
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

# Firebase is still needed for initialization to access other services if needed,
# but we won't use its messaging component here.
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("../serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        print("Scheduler: Firebase Admin SDK initialized.")
    except Exception as e:
        print(f"Scheduler: FATAL Error initializing Firebase Admin SDK: {e}")

from database.db import get_db_session, ScheduleItem, User, Itinerary

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")


async def get_travel_time_seconds(origin: str, destination_place_id: str) -> int:
    if not GOOGLE_MAPS_API_KEY:
        print("WARNING: GOOGLE_MAPS_API_KEY not set. Using default travel time of 15 mins.")
        return 15 * 60

    # Use httpx for this async call as well for consistency
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
    """
    Sends a push notification using Expo's Push API.
    """
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
        'channelId': 'default',  # <-- THE FINAL FIX IS HERE
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(expo_push_url, json=payload, headers=headers)
            # Raise an exception for bad status codes (4xx or 5xx)
            response.raise_for_status()
            print(f"Successfully sent notification via Expo. Response: {response.json()}")
        except httpx.HTTPStatusError as e:
            # This will catch errors from Expo's server, including invalid tokens
            print(
                f"Failed to send notification. Expo server responded with {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            print(f"An error occurred while requesting Expo's push service: {e}")


async def check_and_send_smart_alerts():
    print(f"[{datetime.now()}] Running Smart Itinerary Alert check...")
    async with get_db_session() as db:
        now = datetime.now()
        time_window_start = now.time()
        time_window_end = (now + timedelta(minutes=90)).time()

        stmt = (
            select(ScheduleItem)
            .join(Itinerary).join(User)
            .options(selectinload(ScheduleItem.itinerary).selectinload(Itinerary.user))
            .where(
                ScheduleItem.scheduled_date == now.date(),
                ScheduleItem.notification_sent == False,
                User.fcm_token != None
            )
        )
        result = await db.execute(stmt)
        upcoming_items = result.scalars().unique().all()

        if not upcoming_items:
            print("No upcoming items to notify.")
            return
        print(f"Found {len(upcoming_items)} upcoming items to process.")

        for item in upcoming_items:
            # Check time window here, inside the loop, for more accuracy
            item_time = time.fromisoformat(item.scheduled_time)
            if not (time_window_start <= item_time <= time_window_end):
                continue  # Skip items that are not in the window anymore

            user = item.itinerary.user
            user_current_location = "48.8584,2.2945"  # Placeholder
            travel_time_sec = await get_travel_time_seconds(user_current_location, item.place_id)
            travel_time_min = travel_time_sec // 60
            user_buffer_min = 10
            total_lead_time = timedelta(minutes=(travel_time_min + user_buffer_min))
            item_datetime = datetime.combine(item.scheduled_date, item_time)
            notification_time = item_datetime - total_lead_time

            if now >= notification_time:
                print(f"Sending notification for '{item.place_name}' to {user.email}...")

                await send_expo_push_notification(
                    token=user.fcm_token,
                    title=f"Time for {item.place_name}",
                    body=f"Time to head out! It's a {travel_time_min}-minute ride. Tap for directions.",
                    data={"screen": "itinerary", "itineraryId": str(item.itinerary.id), "itemId": str(item.id)}
                )

                # Mark as sent regardless of delivery status for now
                item.notification_sent = True
                await db.commit()


async def main_scheduler_loop():
    while True:
        await check_and_send_smart_alerts()
        await asyncio.sleep(300)  # Check every 5 minutes


if __name__ == "__main__":
    print("Starting notification scheduler...")
    asyncio.run(main_scheduler_loop())