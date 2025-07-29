import asyncio
from datetime import datetime, timedelta, time
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from firebase_admin import messaging
import os
import requests
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

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
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination=place_id:{destination_place_id}&key={GOOGLE_MAPS_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data['status'] == 'OK':
            return data['routes'][0]['legs'][0]['duration']['value']
    except Exception as e:
        print(f"Error fetching travel time: {e}")
    return 15 * 60


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
                ScheduleItem.scheduled_time >= time_window_start.strftime('%H:%M'),
                ScheduleItem.scheduled_time <= time_window_end.strftime('%H:%M'),
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
            user = item.itinerary.user
            user_current_location = "48.8584,2.2945"  # Placeholder for user's real-time location
            travel_time_sec = await get_travel_time_seconds(user_current_location, item.place_id)
            travel_time_min = travel_time_sec // 60
            user_buffer_min = 10
            total_lead_time = timedelta(minutes=(travel_time_min + user_buffer_min))
            item_time = time.fromisoformat(item.scheduled_time)
            item_datetime = datetime.combine(item.scheduled_date, item_time)
            notification_time = item_datetime - total_lead_time

            if now >= notification_time:
                print(f"Sending notification for '{item.place_name}' to {user.email}...")
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=f"Time for {item.place_name}",
                        body=f"Time to head out! It's a {travel_time_min}-minute ride. Tap for directions.",
                    ),
                    token=user.fcm_token,
                    data={"screen": "itinerary", "itineraryId": str(item.itinerary.id), "itemId": str(item.id)}
                )
                try:
                    messaging.send(message)
                    print(f"Successfully sent notification for '{item.place_name}'.")
                    item.notification_sent = True
                    await db.commit()
                except Exception as e:
                    print(f"Failed to send notification for '{item.place_name}': {e}")
                    if isinstance(e, messaging.UnregisteredError):
                        print(f"FCM token for user {user.email} is invalid. Clearing from DB.")
                        user.fcm_token = None
                        await db.commit()


async def main_scheduler_loop():
    while True:
        await check_and_send_smart_alerts()
        await asyncio.sleep(300)


if __name__ == "__main__":
    print("Starting notification scheduler...")
    asyncio.run(main_scheduler_loop())