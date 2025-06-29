import pytest
import pytest_asyncio
import asyncio
import os
from io import BytesIO
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# --- SETUP: Set a testing flag before importing app components ---
os.environ["TESTING"] = "True"

# --- App Imports ---
from main import app
from database.db import Base, get_db
from models.recommendations import Place
from models.user import UserResponse

# --- Database Setup for Testing ---
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)


# --- Pytest Fixtures ---

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
async def authenticated_client(client: AsyncClient, db_session: AsyncSession) -> AsyncClient:
    user_data = {
        "full_name": "Auth Test User", "date_of_birth": "2000-01-01", "gender": "Male",
        "email": "authtest@example.com", "password": "a_secure_password"
    }
    await client.post("/auth/register", json=user_data)
    login_data = {"username": "authtest@example.com", "password": "a_secure_password"}
    login_response = await client.post("/auth/login", data=login_data)
    token = login_response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# --- Mock Data ---

MOCK_ATTRACTIONS_DATA = [
    {
        "id": "place1", "name": "Eiffel Tower", "rating": 4.5, "image": "http://example.com/image.png",
        "address": "123 Test St, Paris", "types": ["tourist_attraction"], "placeId": "place1"
    },
    {
        "id": "place2", "name": "Louvre Museum", "rating": 4.7, "image": "http://example.com/image.png",
        "address": "456 Art St, Paris", "types": ["museum", "tourist_attraction"], "placeId": "place2"
    }
]

MOCK_RESTAURANTS_DATA = [
    {
        "id": "place3", "name": "Le Jules Verne", "rating": 4.8, "image": "http://example.com/image.png",
        "address": "789 Food St, Paris", "types": ["restaurant"], "placeId": "place3"
    },
]

MOCK_AI_SCHEDULE = [
    {
        "place_id": "place2", "place_name": "Louvre Museum",
        "scheduled_date": "2025-07-10", "scheduled_time": "10:00",
        "duration_minutes": 180
    },
    {
        "place_id": "place3", "place_name": "Le Jules Verne",
        "scheduled_date": "2025-07-10", "scheduled_time": "13:30",
        "duration_minutes": 90
    }
]


# =================================================================================
# --- TEST CASES ---
# =================================================================================

# ... (all previous tests from test_utc_001 to test_utc_013 remain the same) ...
@pytest.mark.asyncio
async def test_utc_001_register_user_success(client: AsyncClient):
    """(UTC-001) Test successful user registration."""
    print("\n--- Testing UTC-001: Register User Success ---")
    response = await client.post(
        "/auth/register", json={
            "full_name": "New User", "date_of_birth": "1995-05-10", "gender": "Female",
            "email": "new.user@test.com", "password": "good_password123"
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_utc_002_register_user_duplicate_email(authenticated_client: AsyncClient):
    """(UTC-002) Test registration with an already existing email."""
    print("\n--- Testing UTC-002: Register User Duplicate Email ---")
    response = await authenticated_client.post(
        "/auth/register", json={
            "full_name": "Another User", "date_of_birth": "1999-01-01", "gender": "Other",
            "email": "authtest@example.com", "password": "another_password"
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_utc_003_login_success(client: AsyncClient):
    """(UTC-003) Test successful user login returns a token."""
    print("\n--- Testing UTC-003: Login User Success ---")
    await client.post("/auth/register", json={
        "full_name": "Login User", "date_of_birth": "2000-01-01", "gender": "Male",
        "email": "login@test.com", "password": "a_secure_password"
    })
    login_data = {"username": "login@test.com", "password": "a_secure_password"}
    response = await client.post("/auth/login", data=login_data)
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_utc_004_login_wrong_password(client: AsyncClient, authenticated_client: AsyncClient):
    """(UTC-004) Test login with incorrect password."""
    print("\n--- Testing UTC-004: Login User Wrong Password ---")
    login_data = {"username": "authtest@example.com", "password": "wrong_password"}
    response = await client.post("/auth/login", data=login_data)
    assert response.status_code == 401
    assert "Invalid credentials" in response.json().get("detail")


@pytest.mark.asyncio
async def test_utc_005_save_personalization(authenticated_client: AsyncClient):
    """(UTC-005) Test saving user preferences."""
    print("\n--- Testing UTC-005: Save User Personalization ---")
    personalization_data = {"tourist_type": ["Cultural", "Foodie"], "preferred_activities": ["Museum", "Sightseeing"]}
    response = await authenticated_client.post("/auth/personalization", json=personalization_data)
    assert response.status_code == 200
    assert response.json()["has_completed_personalization"] is True


@pytest.mark.asyncio
async def test_utc_006_get_user_profile(authenticated_client: AsyncClient):
    """(UTC-006) Test retrieving the current user's profile."""
    print("\n--- Testing UTC-006: Get User Profile ---")
    response = await authenticated_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "authtest@example.com"


@pytest.mark.asyncio
async def test_utc_007_create_bookmark(authenticated_client: AsyncClient):
    """(UTC-007) Test creating a new bookmark."""
    print("\n--- Testing UTC-007: Create Bookmark ---")
    bookmark_data = {"place_id": "place123", "place_name": "Test Place", "place_type": "cafe"}
    response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response.status_code == 201
    assert response.json()["place_id"] == "place123"


@pytest.mark.asyncio
async def test_utc_008_create_duplicate_bookmark(authenticated_client: AsyncClient):
    """(UTC-008) Test preventing duplicate bookmarks."""
    print("\n--- Testing UTC-008: Create Duplicate Bookmark ---")
    bookmark_data = {"place_id": "place456", "place_name": "Unique Place"}
    await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    response2 = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response2.status_code == 409
    assert "already bookmarked" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_utc_009_delete_bookmark(authenticated_client: AsyncClient):
    """(UTC-009) Test deleting a bookmark."""
    print("\n--- Testing UTC-009: Delete Bookmark ---")
    bookmark_data = {"place_id": "place789", "place_name": "Place to Delete"}
    create_response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    bookmark_id = create_response.json()["id"]
    delete_response = await authenticated_client.delete(f"/api/bookmarks/{bookmark_id}")
    assert delete_response.status_code == 204


@pytest.mark.asyncio
async def test_utc_010_create_manual_itinerary(authenticated_client: AsyncClient):
    """(UTC-010) Test creating a new manual itinerary."""
    print("\n--- Testing UTC-010: Create Manual Itinerary ---")
    itinerary_data = {"type": "Manual", "budget": "Comfort", "name": "My Paris Trip", "start_date": "2025-08-15",
                      "end_date": "2025-08-20"}
    response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    actual_body = response.json()
    assert response.status_code == 200
    assert actual_body["name"] == "My Paris Trip"
    assert "id" in actual_body


@pytest.mark.asyncio
async def test_utc_011_get_user_itineraries(authenticated_client: AsyncClient):
    """(UTC-011) Test retrieving a user's itineraries."""
    print("\n--- Testing UTC-011: Get User Itineraries ---")
    itinerary_data = {"type": "Manual", "budget": "Comfort", "name": "Trip to Get", "start_date": "2025-09-01",
                      "end_date": "2025-09-05"}
    await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    response = await authenticated_client.get("/api/itineraries/")
    actual_body = response.json()
    assert response.status_code == 200
    assert len(actual_body) > 0
    assert actual_body[0]["name"] == "Trip to Get"


@pytest.mark.asyncio
async def test_utc_012_get_attraction_recommendations(authenticated_client: AsyncClient, mocker):
    """(UTC-012) Test attraction recommendations with mocked external API."""
    print("\n--- Testing UTC-012: Get Attraction Recommendations ---")
    mocker.patch(
        "routes.recommendations.get_personalized_places",
        return_value=[Place(**p) for p in MOCK_ATTRACTIONS_DATA]
    )
    response = await authenticated_client.get("/api/recommendations/attractions")
    actual_body = response.json()
    assert response.status_code == 200
    assert len(actual_body) == 2
    assert actual_body[0]['name'] == 'Eiffel Tower'


@pytest.mark.asyncio
async def test_utc_013_upload_profile_image(authenticated_client: AsyncClient):
    """(UTC-013) Test uploading a profile image."""
    print("\n--- Testing UTC-013: Upload Profile Image ---")
    image_data = BytesIO(b"this_is_a_fake_image_content")
    files = {"file": ("test_profile.jpg", image_data, "image/jpeg")}
    response = await authenticated_client.post("/api/images/profile/upload", files=files)
    assert response.status_code == 200
    assert "image_uri" in response.json()


@pytest.mark.asyncio
@patch('routes.itinerary.auto_generate_schedule', new_callable=AsyncMock)
@patch('routes.itinerary.get_personalized_places', new_callable=AsyncMock)
async def test_utc_014_generate_ai_itinerary(mock_get_places, mock_auto_generate, authenticated_client: AsyncClient):
    """(UTC-014) Test AI Itinerary Generation with mocked services."""
    print("\n--- Testing UTC-014: Generate AI Itinerary ---")

    # --- FINAL FIX ---
    # Provide a sequence of awaitable return values. The AsyncMock will correctly
    # yield these in order for the concurrent 'await' calls in the route.
    # This avoids the complex greenlet/event loop issue.
    mock_get_places.side_effect = [
        [Place(**p) for p in MOCK_ATTRACTIONS_DATA],
        [Place(**p) for p in MOCK_RESTAURANTS_DATA]
    ]

    # The mock for the AI service remains the same. It is called only once.
    mock_auto_generate.return_value = MOCK_AI_SCHEDULE

    # Prepare request data
    generation_data = {
        "type": "AI", "budget": "Premium", "name": "My AI Trip",
        "start_date": "2025-07-10", "end_date": "2025-07-12"
    }

    # Make the request
    response = await authenticated_client.post("/api/itineraries/generate", json=generation_data)
    actual_body = response.json()

    # Assertions
    print(f"Expected Result: Status Code 200 with a populated itinerary containing 2 schedule items.")
    print(f"Actual Result:   Status Code {response.status_code}, Body: {actual_body}")

    # Add a check for the error detail if the status code is not 200
    if response.status_code != 200:
        print(f"Error Detail: {response.text}")

    assert response.status_code == 200
    assert actual_body["name"] == "My AI Trip"
    assert len(actual_body["schedule_items"]) == 2
    assert actual_body["schedule_items"][0]["place_name"] == "Louvre Museum"


@pytest.mark.asyncio
async def test_utc_015_delete_itinerary(authenticated_client: AsyncClient):
    """(UTC-015) Test deleting an entire itinerary."""
    print("\n--- Testing UTC-015: Delete Itinerary ---")
    itinerary_data = {
        "type": "Manual", "budget": "Budget", "name": "Trip to be Deleted",
        "start_date": "2026-01-01", "end_date": "2026-01-05"
    }
    create_response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    assert create_response.status_code == 200
    itinerary_id = create_response.json()["id"]
    delete_response = await authenticated_client.delete(f"/api/itineraries/{itinerary_id}")
    assert delete_response.status_code == 204
    get_response = await authenticated_client.get("/api/itineraries/")
    assert all(itinerary['id'] != itinerary_id for itinerary in get_response.json())


@pytest.mark.asyncio
async def test_utc_016_add_item_to_itinerary(authenticated_client: AsyncClient):
    """(UTC-016) Test adding a schedule item to an existing itinerary."""
    print("\n--- Testing UTC-016: Add Item to Itinerary ---")
    # 1. Create a parent itinerary
    itinerary_data = {
        "type": "Manual", "budget": "Comfort", "name": "Trip to Add To",
        "start_date": "2025-10-10", "end_date": "2025-10-15"
    }
    create_response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    assert create_response.status_code == 200
    itinerary_id = create_response.json()["id"]

    # 2. Add an item to it
    item_data = {
        "place_id": "new_place_123", "place_name": "New Awesome Place",
        "scheduled_date": "2025-10-11", "scheduled_time": "14:00",
        "duration_minutes": 90
    }
    add_item_response = await authenticated_client.post(f"/api/itineraries/{itinerary_id}/items", json=item_data)
    actual_body = add_item_response.json()

    print(f"Expected Result: Status Code 201 with created schedule item data.")
    print(f"Actual Result:   Status Code {add_item_response.status_code}, Body: {actual_body}")
    assert add_item_response.status_code == 201
    assert actual_body["place_id"] == "new_place_123"
    assert actual_body["place_name"] == "New Awesome Place"

    # 3. Verify the item was added correctly
    get_response = await authenticated_client.get("/api/itineraries/")
    itineraries_list = get_response.json()
    target_itinerary = next((it for it in itineraries_list if it["id"] == itinerary_id), None)
    assert target_itinerary is not None
    assert len(target_itinerary["schedule_items"]) == 1
    assert target_itinerary["schedule_items"][0]["place_id"] == "new_place_123"