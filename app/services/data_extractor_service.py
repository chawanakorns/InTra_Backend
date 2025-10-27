import httpx
import psycopg2
import os
from dotenv import load_dotenv
import time
import asyncio
from typing import Literal, List, Dict

load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

ExtractionType = Literal["restaurants", "attractions"]


async def search_places(search_query: str, place_type: str, max_results: int) -> list[str]:
    print(f"Searching for: '{search_query}'...")
    place_ids = set()
    url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={search_query}&type={place_type}&key={API_KEY}"

    async with httpx.AsyncClient() as client:
        while len(place_ids) < max_results:
            try:
                response = await client.get(url, timeout=30)
                response.raise_for_status()
                data = response.json()

                for result in data.get('results', []):
                    place_ids.add(result['place_id'])

                next_page_token = data.get('next_page_token')
                if not next_page_token:
                    print("No more search result pages.")
                    break

                await asyncio.sleep(2)
                url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?pagetoken={next_page_token}&key={API_KEY}"
            except Exception as e:
                print(f"An error occurred during search: {e}")
                break

    return list(place_ids)


async def get_details_with_reviews(place_id: str) -> dict | None:
    fields = "name,formatted_address,rating,user_ratings_total,reviews,types"
    url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields={fields}&key={API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get('result')
    except Exception as e:
        print(f"An error occurred getting details for {place_id}: {e}")
        return None


async def fetch_and_format_data(extraction_type: ExtractionType, location: str, max_results: int) -> (List[Dict],
                                                                                                      List[Dict]):
    """
    This function performs the data fetching from Google Maps and returns formatted lists.
    It does NOT save to the database.
    """
    search_query = f"{extraction_type} in {location}"
    place_type_param = "restaurant" if extraction_type == "restaurants" else "tourist_attraction"

    place_ids = await search_places(search_query, place_type_param, max_results)
    print(f"Found {len(place_ids)} unique places.")

    all_places = []
    all_reviews = []

    print(f"Fetching details for each {extraction_type[:-1]}...")
    for i, place_id in enumerate(place_ids):
        details = await get_details_with_reviews(place_id)
        if not details:
            continue

        print(f"  - Processing {i + 1}/{len(place_ids)}: {details.get('name')}")

        all_places.append({
            'place_id': place_id,
            'name': details.get('name'),
            'address': details.get('formatted_address'),
            'rating': details.get('rating'),
            'user_ratings_total': details.get('user_ratings_total'),
            'types': details.get('types', [])
        })

        if 'reviews' in details:
            for review in details['reviews']:
                all_reviews.append({
                    'place_id': place_id,
                    'author_name': review.get('author_name'),
                    'profile_photo_url': review.get('profile_photo_url'),
                    'rating': review.get('rating'),
                    'text': review.get('text'),
                    'time_description': review.get('relative_time_description')
                })
        await asyncio.sleep(0.1)  # Be respectful to API rate limits

    return all_places, all_reviews


def save_to_database(extraction_type: ExtractionType, places_data: list, reviews_data: list):
    """Saves the fetched data to the appropriate database tables."""
    table_name = "restaurants" if extraction_type == "restaurants" else "attractions"
    review_table_name = "restaurant_reviews" if extraction_type == "restaurants" else "attraction_reviews"
    fk_column_name = "restaurant_place_id" if extraction_type == "restaurants" else "attraction_place_id"

    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        cur = conn.cursor()

        for place in places_data:
            cur.execute(
                f"""
                INSERT INTO {table_name} (place_id, name, address, rating, user_ratings_total, types)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (place_id) DO NOTHING;
                """,
                (place['place_id'], place['name'], place['address'], place['rating'], place['user_ratings_total'],
                 place['types'])
            )

        for review in reviews_data:
            cur.execute(
                f"""
                INSERT INTO {review_table_name} ({fk_column_name}, author_name, profile_photo_url, rating, review_text, published_at_text)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (review['place_id'], review['author_name'], review['profile_photo_url'], review['rating'],
                 review['text'], review['time_description'])
            )

        conn.commit()
        cur.close()
        print(f"Successfully saved {len(places_data)} places and {len(reviews_data)} reviews to '{table_name}' table.")
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database Error: {error}")
    finally:
        if conn is not None:
            conn.close()


async def run_extraction_job(extraction_type: ExtractionType, location: str, max_results: int):
    """
    High-level job function that fetches data and then saves it to the database.
    This is designed to be run as a background task.
    """
    print(f"--- Starting background extraction job for {extraction_type} in {location} ---")
    all_places, all_reviews = await fetch_and_format_data(extraction_type, location, max_results)

    if all_places:
        # Since save_to_database is synchronous, we run it in a thread to avoid blocking the asyncio loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, save_to_database, extraction_type, all_places, all_reviews)
    else:
        print("No data was fetched to save to the database.")

    print(f"\n--- Extraction job for '{extraction_type} in {location}' complete. ---")