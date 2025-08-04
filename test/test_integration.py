import pytest
import pytest_asyncio
import asyncio
import os
from io import BytesIO
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# --- SETUP ---
os.environ["TESTING"] = "True"

# --- App Imports ---
# Make sure main is imported after the environment variable is set
from main import app
from app.database.db import Base, get_db
from app.models.recommendations import Place

# --- Test DB Setup ---
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- Fixtures ---
@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession, mocker) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    mock_db_manager = AsyncMock()
    mock_db_manager.__aenter__.return_value = db_session
    mocker.patch('services.auth.get_db_session', return_value=mock_db_manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    del app.dependency_overrides[get_db]


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(client: AsyncClient) -> AsyncClient:
    user_data = {"full_name": "Auth Test User", "date_of_birth": "2000-01-01", "gender": "Male",
                 "email": "authtest@example.com", "password": "a_secure_password"}
    await client.post("/auth/register", json=user_data)
    login_data = {"username": "authtest@example.com", "password": "a_secure_password"}
    login_response = await client.post("/auth/login", data=login_data)
    token = login_response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# --- Mock Data ---
MOCK_ATTRACTIONS_DATA = [
    {"id": "place1", "name": "Eiffel Tower", "rating": 4.5, "image": "http://example.com/image.png",
     "address": "123 Test St, Paris", "types": ["tourist_attraction"], "placeId": "place1"},
    {"id": "place2", "name": "Louvre Museum", "rating": 4.7, "image": "http://example.com/image.png",
     "address": "456 Art St, Paris", "types": ["museum", "tourist_attraction"], "placeId": "place2"}]

@pytest.mark.asyncio
async def test_itc_001_register_user_success(client: AsyncClient):
    response = await client.post("/auth/register",
                                 json={"full_name": "New User", "date_of_birth": "1995-05-10", "gender": "Female",
                                       "email": "new.user@test.com", "password": "good_password123"})
    print(f"\n--- ITC_001 - Register User Success ---")
    print(f"Request: POST /auth/register with new user data")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected to find 'access_token' in response.json(), Actual response: {response.json()}")
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_itc_002_register_user_duplicate_email(authenticated_client: AsyncClient):
    response = await authenticated_client.post("/auth/register",
                                               json={"full_name": "Another User", "date_of_birth": "1999-01-01",
                                                     "gender": "Other", "email": "authtest@example.com",
                                                     "password": "another_password"})
    print(f"\n--- ITC_002 - Register User Duplicate Email ---")
    print(f"Request: POST /auth/register with existing user email")
    print(f"Expected Status Code: 400, Actual Status Code: {response.status_code}")
    print(f"Expected Detail: 'Email already registered', Actual Detail: {response.json().get('detail')}")
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_itc_003_login_user_success(client: AsyncClient):
    await client.post("/auth/register",
                      json={"full_name": "Login User", "date_of_birth": "2000-01-01", "gender": "Male",
                            "email": "login@test.com", "password": "a_secure_password"})
    login_data = {"username": "login@test.com", "password": "a_secure_password"}
    response = await client.post("/auth/login", data=login_data)
    print(f"\n--- ITC_003 - Login User Success ---")
    print(f"Request: POST /auth/login with valid credentials")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected to find 'access_token' in response.json(), Actual response: {response.json()}")
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_itc_004_login_user_wrong_password(client: AsyncClient):
    await client.post("/auth/register",
                      json={"full_name": "Wrong Pass User", "date_of_birth": "2000-01-01", "gender": "Male",
                            "email": "wrongpass@test.com", "password": "correct_password"})
    login_data = {"username": "wrongpass@test.com", "password": "wrong_password"}
    response = await client.post("/auth/login", data=login_data)
    print(f"\n--- ITC_004 - Login User Wrong Password ---")
    print(f"Request: POST /auth/login with wrong password")
    print(f"Expected Status Code: 401, Actual Status Code: {response.status_code}")
    print(f"Expected Detail: 'Invalid credentials', Actual Detail: {response.json().get('detail')}")
    assert response.status_code == 401
    assert "Invalid credentials" in response.json().get("detail")


@pytest.mark.asyncio
async def test_itc_005_save_user_personalization(authenticated_client: AsyncClient):
    personalization_data = {"tourist_type": ["Cultural", "Foodie"], "preferred_activities": ["Museum", "Sightseeing"]}
    response = await authenticated_client.post("/auth/personalization", json=personalization_data)
    print(f"\n--- ITC_005 - Save User Personalization ---")
    print(f"Request: POST /auth/personalization")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected has_completed_personalization: True, Actual: {response.json().get('has_completed_personalization')}")
    assert response.status_code == 200
    assert response.json()["has_completed_personalization"] is True


@pytest.mark.asyncio
async def test_itc_006_get_user_profile(authenticated_client: AsyncClient):
    response = await authenticated_client.get("/auth/me")
    print(f"\n--- ITC_006 - Get User Profile ---")
    print(f"Request: GET /auth/me")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected Email: 'authtest@example.com', Actual Email: {response.json().get('email')}")
    assert response.status_code == 200
    assert response.json()["email"] == "authtest@example.com"


@pytest.mark.asyncio
async def test_itc_007_create_bookmark(authenticated_client: AsyncClient):
    bookmark_data = {"place_id": "place123", "place_name": "Test Place", "place_type": "cafe"}
    response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    print(f"\n--- ITC_007 - Create Bookmark ---")
    print(f"Request: POST /api/bookmarks/")
    print(f"Expected Status Code: 201, Actual Status Code: {response.status_code}")
    print(f"Expected Place ID: 'place123', Actual Place ID: {response.json().get('place_id')}")
    assert response.status_code == 201
    assert response.json()["place_id"] == "place123"


@pytest.mark.asyncio
async def test_itc_008_create_duplicate_bookmark(authenticated_client: AsyncClient):
    bookmark_data = {"place_id": "place456", "place_name": "Unique Place"}
    await authenticated_client.post("/api/bookmarks/", json=bookmark_data) # First creation
    response2 = await authenticated_client.post("/api/bookmarks/", json=bookmark_data) # Duplicate creation
    print(f"\n--- ITC_008 - Create Duplicate Bookmark ---")
    print(f"Request: POST /api/bookmarks/ (duplicate)")
    print(f"Expected Status Code: 409, Actual Status Code: {response2.status_code}")
    print(f"Expected Detail: 'already bookmarked', Actual Detail: {response2.json().get('detail')}")
    assert response2.status_code == 409
    assert "already bookmarked" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_itc_009_delete_bookmark(authenticated_client: AsyncClient):
    bookmark_data = {"place_id": "place789", "place_name": "Place to Delete"}
    create_response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    bookmark_id = create_response.json()["id"]
    delete_response = await authenticated_client.delete(f"/api/bookmarks/{bookmark_id}")
    print(f"\n--- ITC_009 - Delete Bookmark ---")
    print(f"Request: DELETE /api/bookmarks/{bookmark_id}")
    print(f"Expected Status Code: 204, Actual Status Code: {delete_response.status_code}")
    assert delete_response.status_code == 204


@pytest.mark.asyncio
async def test_itc_010_create_manual_itinerary(authenticated_client: AsyncClient):
    itinerary_data = {"type": "Manual", "budget": "Comfort", "name": "My Paris Trip", "start_date": "2025-08-15",
                      "end_date": "2025-08-20"}
    response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    print(f"\n--- ITC_010 - Create Manual Itinerary ---")
    print(f"Request: POST /api/itineraries/")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected Itinerary Name: 'My Paris Trip', Actual Name: {response.json().get('name')}")
    assert response.status_code == 200
    assert response.json()["name"] == "My Paris Trip"


@pytest.mark.asyncio
async def test_itc_011_get_user_itineraries(authenticated_client: AsyncClient):
    itinerary_data = {"type": "Manual", "budget": "Comfort", "name": "Trip to Get", "start_date": "2025-09-01",
                      "end_date": "2025-09-05"}
    await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    response = await authenticated_client.get("/api/itineraries/")
    print(f"\n--- ITC_011 - Get User Itineraries ---")
    print(f"Request: GET /api/itineraries/")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected at least 1 itinerary, Actual count: {len(response.json())}")
    print(f"Expected itinerary name: 'Trip to Get', Actual: {response.json()[0].get('name') if response.json() else 'N/A'}")
    assert response.status_code == 200
    assert len(response.json()) > 0
    assert response.json()[0]["name"] == "Trip to Get"


@pytest.mark.asyncio
async def test_itc_012_get_attraction_recommendations(authenticated_client: AsyncClient, mocker):
    mocker.patch("controllers.recommendations.get_personalized_places",
                 return_value=[Place(**p) for p in MOCK_ATTRACTIONS_DATA])
    response = await authenticated_client.get("/api/recommendations/attractions")
    print(f"\n--- ITC_012 - Get Attraction Recommendations ---")
    print(f"Request: GET /api/recommendations/attractions")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected 2 recommendations, Actual count: {len(response.json())}")
    print(f"Actual Recommendations: {response.json()}")
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_itc_013_upload_profile_image(authenticated_client: AsyncClient):
    image_data = BytesIO(b"this_is_a_fake_image_content")
    files = {"file": ("test_profile.jpg", image_data, "image/jpeg")}
    response = await authenticated_client.post("/api/images/profile/upload", files=files)
    print(f"\n--- ITC_013 - Upload Profile Image ---")
    print(f"Request: POST /api/images/profile/upload")
    print(f"Expected Status Code: 200, Actual Status Code: {response.status_code}")
    print(f"Expected 'image_uri' in response, Actual response: {response.json()}")
    assert response.status_code == 200
    assert "image_uri" in response.json()


@pytest.mark.asyncio
async def test_itc_015_delete_itinerary(authenticated_client: AsyncClient):
    itinerary_data = {"type": "Manual", "budget": "Budget", "name": "Trip to be Deleted", "start_date": "2026-01-01",
                      "end_date": "2026-01-05"}
    create_response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    itinerary_id = create_response.json()["id"]
    delete_response = await authenticated_client.delete(f"/api/itineraries/{itinerary_id}")
    print(f"\n--- ITC_015 - Delete Itinerary ---")
    print(f"Request: DELETE /api/itineraries/{itinerary_id}")
    print(f"Expected Status Code: 204, Actual Status Code: {delete_response.status_code}")
    assert delete_response.status_code == 204


@pytest.mark.asyncio
async def test_itc_016_add_place_to_itinerary(authenticated_client: AsyncClient):
    itinerary_data = {"type": "Manual", "budget": "Comfort", "name": "Trip to Add To", "start_date": "2025-10-10",
                      "end_date": "2025-10-15"}
    create_response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    itinerary_id = create_response.json()["id"]
    item_data = {"place_id": "new_place_123", "place_name": "New Awesome Place", "scheduled_date": "2025-10-11",
                 "scheduled_time": "14:00", "duration_minutes": 90}
    add_item_response = await authenticated_client.post(f"/api/itineraries/{itinerary_id}/items", json=item_data)
    print(f"\n--- ITC_016 - Add Place to Itinerary ---")
    print(f"Request: POST /api/itineraries/{itinerary_id}/items")
    print(f"Expected Status Code: 201, Actual Status Code: {add_item_response.status_code}")
    print(f"Expected place_id: 'new_place_123', Actual place_id: {add_item_response.json().get('place_id')}")
    assert add_item_response.status_code == 201
    assert add_item_response.json()["place_id"] == "new_place_123"