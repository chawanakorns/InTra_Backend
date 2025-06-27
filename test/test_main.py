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

# --- SETUP: Set a testing flag before importing app components ---
os.environ["TESTING"] = "True"

# --- App Imports ---
from main import app
from database.db import Base, get_db
from models.recommendations import Place

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


# =================================================================================
# --- Pytest Fixtures ---
# =================================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Creates an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Creates a new, isolated database session for each test function."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession, mocker) -> AsyncGenerator[AsyncClient, None]:
    """
    Creates a test client for the app, overriding all database dependencies
    to ensure full isolation.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    mock_db_manager = AsyncMock()
    mock_db_manager.__aenter__.return_value = db_session
    mocker.patch(
        'services.auth.get_db_session',
        return_value=mock_db_manager
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    del app.dependency_overrides[get_db]


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(client: AsyncClient) -> AsyncClient:
    """Creates a client that is pre-authenticated for testing protected endpoints."""
    user_data = {
        "full_name": "Test User",
        "date_of_birth": "2000-01-01",
        "gender": "Male",
        "email": "test@example.com",
        "password": "a_secure_password"
    }
    register_response = await client.post("/auth/register", json=user_data)
    assert register_response.status_code == 200, f"Registration failed: {register_response.text}"

    login_data = {
        "username": "test@example.com",
        "password": "a_secure_password"
    }
    login_response = await client.post("/auth/login", data=login_data)
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"

    token = login_response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# --- Mock Data ---
def get_mock_place(place_id: str, name: str, types: list) -> Place:
    """Helper to create a Place model instance."""
    return Place(
        id=place_id, name=name, rating=4.5, image="http://example.com/image.png",
        address="123 Test St, Paris", types=types, placeId=place_id
    )


MOCK_ATTRACTIONS = [
    get_mock_place("place1", "Eiffel Tower", ["tourist_attraction"]).dict(),
    get_mock_place("place2", "Louvre Museum", ["museum", "tourist_attraction"]).dict()
]
MOCK_RESTAURANTS = [
    get_mock_place("place3", "Le Test Cafe", ["restaurant", "cafe"]).dict()
]


# =================================================================================
# --- TEST CASES ---
# =================================================================================

# --- Test Authentication (routes/auth.py) ---

@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient):
    """Test successful user registration (Mirrors STC-01.1)."""
    response = await client.post(
        "/auth/register", json={
            "full_name": "New User", "date_of_birth": "1995-05-10", "gender": "Female",
            "email": "new.user@test.com", "password": "good_password123"
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_user_duplicate_email(authenticated_client: AsyncClient):
    """Test registration with an already existing email (Mirrors STC-01.2)."""
    response = await authenticated_client.post(
        "/auth/register", json={
            "full_name": "Another User", "date_of_birth": "1999-01-01", "gender": "Other",
            "email": "test@example.com", "password": "another_password"
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_login_success(authenticated_client: AsyncClient):
    """Test successful login (Mirrors STC-002)."""
    response = await authenticated_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, authenticated_client: AsyncClient):
    """Test login with incorrect password (Mirrors STC-02.3)."""
    login_data = {"username": "test@example.com", "password": "wrong_password"}
    response = await client.post("/auth/login", data=login_data)
    assert response.status_code == 401
    assert "Invalid credentials" in response.json().get("detail")


@pytest.mark.asyncio
async def test_save_personalization(authenticated_client: AsyncClient):
    """Test saving user preferences (Mirrors STC-004)."""
    personalization_data = {
        "tourist_type": ["Cultural", "Foodie"],
        "preferred_activities": ["Museum", "Sightseeing"]
    }
    response = await authenticated_client.post("/auth/personalization", json=personalization_data)
    assert response.status_code == 200
    data = response.json()
    assert data["has_completed_personalization"] is True
    assert data["tourist_type"] == ["Cultural", "Foodie"]


# --- Test Recommendations (routes/recommendations.py) ---

@pytest.mark.asyncio
async def test_get_attraction_recommendations(authenticated_client: AsyncClient, mocker):
    """Test attraction recommendations with mocked external API."""
    mocker.patch(
        "routes.recommendations.get_personalized_places",
        return_value=[Place(**p) for p in MOCK_ATTRACTIONS]
    )
    response = await authenticated_client.get("/api/recommendations/attractions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Eiffel Tower"


# --- Test Bookmarks (routes/bookmarks.py) ---

@pytest.mark.asyncio
async def test_create_and_get_bookmarks(authenticated_client: AsyncClient):
    """Test creating a new bookmark (Mirrors UTC-006)."""
    bookmark_data = {
        "place_id": "place123", "place_name": "Test Place", "place_type": "cafe",
        "place_address": "123 Bookmark Lane", "place_rating": 4.8, "place_image": "http://example.com/image.png"
    }
    response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response.status_code == 201
    created_bookmark = response.json()
    assert created_bookmark["place_id"] == "place123"

    response = await authenticated_client.get("/api/bookmarks/")
    assert response.status_code == 200
    bookmarks = response.json()
    assert len(bookmarks) == 1
    assert bookmarks[0]["place_id"] == "place123"


@pytest.mark.asyncio
async def test_create_duplicate_bookmark(authenticated_client: AsyncClient):
    """Test preventing duplicate bookmarks (Mirrors UTC-007)."""
    bookmark_data = {"place_id": "place456", "place_name": "Unique Place"}
    await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    response2 = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response2.status_code == 409
    assert "already bookmarked" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_delete_bookmark(authenticated_client: AsyncClient):
    """Test deleting a bookmark."""
    bookmark_data = {"place_id": "place789", "place_name": "Place to Delete"}
    create_response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    bookmark_id = create_response.json()["id"]

    delete_response = await authenticated_client.delete(f"/api/bookmarks/{bookmark_id}")
    assert delete_response.status_code == 204

    get_response = await authenticated_client.get("/api/bookmarks/")
    assert len(get_response.json()) == 0


# --- Test Itinerary (routes/itinerary.py) ---

@pytest.mark.asyncio
async def test_create_and_get_itinerary(authenticated_client: AsyncClient):
    """Test creating and retrieving a manually created itinerary."""
    itinerary_data = {
        "type": "Manual", "budget": "Comfort", "name": "My Paris Trip",
        "start_date": "2025-08-15", "end_date": "2025-08-20"
    }
    create_response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
    assert create_response.status_code == 200

    get_response = await authenticated_client.get("/api/itineraries/")
    assert get_response.status_code == 200
    itineraries = get_response.json()
    assert len(itineraries) == 1
    assert itineraries[0]["name"] == "My Paris Trip"

# --- Test Image Uploads (routes/images.py) ---

@pytest.mark.asyncio
async def test_upload_profile_image(authenticated_client: AsyncClient):
    """Test uploading a profile image."""
    image_data = BytesIO(b"this_is_a_fake_image_content")
    files = {"file": ("test_profile.jpg", image_data, "image/jpeg")}

    response = await authenticated_client.post("/api/images/profile/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert "image_uri" in data
    assert data["image_uri"].startswith("/uploads/profile_")

    me_response = await authenticated_client.get("/auth/me")
    assert me_response.json()["image_uri"] == data["image_uri"]