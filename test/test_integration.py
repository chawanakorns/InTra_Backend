import pytest
import pytest_asyncio
import asyncio
import os
from io import BytesIO
from typing import AsyncGenerator, Generator
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import date

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.recommendations import Place

# --- SETUP ---
os.environ["TESTING"] = "True"

# --- App Imports ---
from main import app
from app.database.connection import Base, get_db
from app.database.models import User, Notification, Itinerary, ScheduleItem, Bookmark

# --- Test DB Setup ---
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- CORE FIXTURES ---

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
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    del app.dependency_overrides[get_db]


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session: AsyncSession) -> User:
    user = User(firebase_uid="test_firebase_uid_123", email="authtest@example.com", full_name="Auth Test User")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture(scope="function")
def mock_firebase_auth(mocker):
    """Mocks the firebase_admin.auth module AT THE SOURCE where it is used by the security dependency."""
    # Based on your firebase_auth.py file, this is the correct path.
    return mocker.patch('app.services.firebase_auth.auth')


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(client: AsyncClient, test_user: User, mock_firebase_auth) -> AsyncClient:
    """Provides a client authenticated as an EXISTING user."""
    mock_firebase_auth.verify_id_token.return_value = {'uid': test_user.firebase_uid, 'email': test_user.email}
    client.headers["Authorization"] = "Bearer existing-user-token"
    yield client


@pytest_asyncio.fixture(scope="function")
async def new_user_authenticated_client(client: AsyncClient, mocker) -> AsyncClient:
    """Provides an HTTP client where the Firebase Admin SDK is mocked for a NEW user."""
    mock_auth = mocker.patch('app.services.firebase_auth.auth')
    mock_auth.verify_id_token.return_value = {'uid': 'new_firebase_uid', 'email': 'new.user@test.com'}
    mock_auth.get_user.side_effect = Exception("User not found") # This simulates a new Firebase user
    client.headers["Authorization"] = "Bearer new-user-token"
    yield client


@pytest.mark.asyncio
async def test_itc_001_auth_sync_new_user(client: AsyncClient, mocker):
    """Tests ITC-001: A new Firebase user is synced to the local DB."""
    mock_auth = mocker.patch('app.controllers.auth.auth')
    mock_auth.verify_id_token.return_value = {'uid': 'new_firebase_uid', 'email': 'new.user@test.com'}
    mock_auth.get_user.return_value = MagicMock(
        uid='new_firebase_uid', email='new.user@test.com', display_name='New Test User'
    )

    sync_data = {"fullName": "New Test User", "dob": "2000-01-01", "gender": "Male"}
    response = await client.post("/auth/sync", headers={"Authorization": "Bearer new-user-token"}, json=sync_data)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    assert response.json()["email"] == "new.user@test.com"


@pytest.mark.asyncio
async def test_itc_002_auth_sync_existing_user(client: AsyncClient, test_user: User):
    """Tests InTra-ITC-002 (Duplicate Registration): Syncing an existing Firebase user returns their data."""
    with patch('app.services.firebase_auth.auth.verify_id_token') as mock_verify:
        mock_verify.return_value = {'uid': test_user.firebase_uid}

        sync_data = {"full_name": test_user.full_name, "email": test_user.email}
        response = await client.post("/auth/sync", headers={"Authorization": "Bearer existing_token"}, json=sync_data)

        print(f"\n--- ITC_002 - Auth Sync Existing User ---")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
        assert response.json()["id"] == test_user.id
        assert response.json()["email"] == test_user.email


@pytest.mark.asyncio
async def test_itc_003_get_user_profile(authenticated_client: AsyncClient, test_user: User):
    """Tests InTra-ITC-003 (Login/Get Profile): An authenticated user can retrieve their own profile."""
    response = await authenticated_client.get("/auth/me")

    print(f"\n--- ITC_003 - Get User Profile ---")
    assert response.status_code == 200
    assert response.json()["email"] == test_user.email


@pytest.mark.asyncio
async def test_itc_004_update_user_profile(authenticated_client: AsyncClient):
    """Tests InTra-ITC-004 (Update Profile): An authenticated user can update their profile information."""
    update_data = {"fullName": "Auth Test User Updated", "aboutMe": "I am a traveler."}
    response = await authenticated_client.put("/auth/me", json=update_data)

    print(f"\n--- ITC_004 - Update User Profile ---")
    assert response.status_code == 200
    assert response.json()["full_name"] == "Auth Test User Updated"
    assert response.json()["about_me"] == "I am a traveler."


@pytest.mark.asyncio
async def test_itc_005_save_user_personalization(authenticated_client: AsyncClient):
    personalization_data = {"tourist_type": ["Cultural", "Foodie"], "preferred_activities": ["Museum", "Sightseeing"]}
    response = await authenticated_client.post("/auth/personalization", json=personalization_data)
    print(f"\n--- ITC_005 - Save User Personalization ---")
    assert response.status_code == 200
    assert response.json()["has_completed_personalization"] is True


@pytest.mark.asyncio
async def test_itc_006_get_user_profile(authenticated_client: AsyncClient):
    response = await authenticated_client.get("/auth/me")
    print(f"\n--- ITC_006 - Get User Profile ---")
    assert response.status_code == 200
    assert response.json()["email"] == "authtest@example.com"


@pytest.mark.asyncio
async def test_itc_007_create_bookmark(authenticated_client: AsyncClient):
    bookmark_data = {"place_id": "place123", "place_name": "Test Place", "place_type": "cafe"}
    response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    print(f"\n--- ITC_007 - Create Bookmark ---")
    assert response.status_code == 201
    assert response.json()["place_id"] == "place123"

# --- Integration Test Cases ---

@pytest.mark.asyncio
async def test_itc_008_create_duplicate_bookmark(authenticated_client: AsyncClient):
    """Tests InTra-ITC-008: System prevents duplicate bookmarks."""
    bookmark_data = {"place_id": "place456", "place_name": "Unique Place"}
    response1 = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response1.status_code == 201

    response2 = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert response2.status_code == 409
    assert "already bookmarked" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_itc_009_delete_bookmark(authenticated_client: AsyncClient):
    """Tests InTra-ITC-009: A user can delete their bookmark."""
    bookmark_data = {"place_id": "place789", "place_name": "Place to Delete"}
    create_response = await authenticated_client.post("/api/bookmarks/", json=bookmark_data)
    assert create_response.status_code == 201
    bookmark_id = create_response.json()["id"]

    delete_response = await authenticated_client.delete(f"/api/bookmarks/{bookmark_id}")
    assert delete_response.status_code == 204


# @pytest.mark.asyncio
# async def test_itc_010_create_manual_itinerary(authenticated_client: AsyncClient):
#     """Tests ITC-010."""
#     itinerary_data = {
#         "budget": "Comfort", "name": "My Paris Trip",
#         "start_date": "2025-08-15", "end_date": "2025-08-20"
#     }
#     response = await authenticated_client.post("/api/itineraries/", json=itinerary_data)
#     assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"


@pytest.mark.asyncio
async def test_itc_011_get_user_itineraries(authenticated_client: AsyncClient):
    """Tests InTra-ITC-011: A user can retrieve all their created itineraries."""
    itinerary_data = {"budget": "Comfort", "name": "Trip to Get", "start_date": "2025-09-01",
                      "end_date": "2025-09-05"}
    await authenticated_client.post("/api/itineraries/", json=itinerary_data)

    response = await authenticated_client.get("/api/itineraries/")
    assert response.status_code == 200
    assert len(response.json()) > 0
    assert response.json()[0]["name"] == "Trip to Get"


@pytest.mark.asyncio
async def test_itc_013_upload_profile_image(authenticated_client: AsyncClient):
    image_data = BytesIO(b"this_is_a_fake_image_content")
    files = {"file": ("test_profile.jpg", image_data, "image/jpeg")}
    response = await authenticated_client.post("/api/images/profile/upload", files=files)
    print(f"\n--- ITC_013 - Upload Profile Image ---")
    assert response.status_code == 200
    assert "image_uri" in response.json()


# @pytest.mark.asyncio
# async def test_itc_014_generate_ai_itinerary(authenticated_client: AsyncClient, mocker):
#     """Tests ITC-014: A user can generate an AI-powered itinerary."""
#     mock_ai_response = [
#         {"place_id": "p1", "place_name": "AI Museum", "scheduled_date": "2025-11-01",
#          "scheduled_time": "10:00", "duration_minutes": 120, "place_type": "museum"}
#     ]
#     mocker.patch('app.services.generation_service.auto_generate_schedule', new_callable=AsyncMock,
#                  return_value=mock_ai_response)
#     mocker.patch('app.controllers.itinerary.get_personalized_places', new_callable=AsyncMock,
#                  return_value=[Place(id="p1", name="AI Museum", rating=4.5, placeId="p1")])
#
#     gen_data = {
#         "name": "AI Adventure", "start_date": "2025-11-01", "end_date": "2025-11-03",
#         "latitude": 48.8566, "longitude": 2.3522
#     }
#     response = await authenticated_client.post("/api/itineraries/generate", json=gen_data)
#
#     assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
#     assert response.json()["name"] == "AI Adventure"


@pytest.mark.asyncio
async def test_itc_015_delete_itinerary(authenticated_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Tests ITC-015: A user can delete an entire itinerary."""
    itinerary = Itinerary(
        user_id=test_user.id, name="Trip to be Deleted", type="Manual", budget="Economy",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 5)
    )
    db_session.add(itinerary)
    await db_session.commit()
    await db_session.refresh(itinerary)

    delete_response = await authenticated_client.delete(f"/api/itineraries/{itinerary.id}")
    assert delete_response.status_code == 204


@pytest.mark.asyncio
async def test_itc_016_add_item_to_itinerary(authenticated_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Tests ITC-016: A user can add a new item to an itinerary."""
    itinerary = Itinerary(
        user_id=test_user.id, name="Trip to Add To", type="Manual", budget="Luxury",
        start_date=date(2025, 10, 10), end_date=date(2025, 10, 15)
    )
    db_session.add(itinerary)
    await db_session.commit()
    await db_session.refresh(itinerary)

    item_data = {
        "place_id": "new_place_123", "place_name": "New Awesome Place",
        "scheduled_date": "2025-10-11", "scheduled_time": "14:00",
        "duration_minutes": 120, "place_type": "restaurant"
    }
    add_item_response = await authenticated_client.post(f"/api/itineraries/{itinerary.id}/items", json=item_data)
    assert add_item_response.status_code == 201, f"Expected 201, got {add_item_response.status_code}. Response: {add_item_response.text}"
    assert add_item_response.json()["place_id"] == "new_place_123"


# --- NEW TEST CASES START HERE ---

@pytest.mark.asyncio
async def test_itc_017_edit_itinerary_item(authenticated_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Tests ITC-017: A user can edit the date and time of a schedule item."""
    # 1. Setup: Create an itinerary and an item to edit
    itinerary = Itinerary(
        user_id=test_user.id, name="Trip to Edit Item In", type="Manual", budget="Economy",
        start_date=date(2025, 11, 1), end_date=date(2025, 11, 5)
    )
    db_session.add(itinerary)
    await db_session.flush()

    item_to_edit = ScheduleItem(
        itinerary_id=itinerary.id,
        place_id="place_to_edit",
        place_name="Original Place",
        scheduled_date=date(2025, 11, 2),
        scheduled_time="10:00",
        duration_minutes=60
    )
    db_session.add(item_to_edit)
    await db_session.commit()
    await db_session.refresh(item_to_edit)

    # 2. Action: Send PUT request with update data
    update_data = {
        "scheduled_date": "2025-11-03",
        "scheduled_time": "15:30",
        "duration_minutes": 90
    }
    response = await authenticated_client.put(f"/api/itineraries/items/{item_to_edit.id}", json=update_data)

    # 3. Assertions
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    response_json = response.json()
    assert response_json["scheduled_date"] == "2025-11-03"
    assert response_json["scheduled_time"] == "15:30"
    assert response_json["duration_minutes"] == 90


@pytest.mark.asyncio
async def test_itc_018_delete_itinerary_item(authenticated_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Tests ITC-018: A user can delete a single item from an itinerary."""
    # 1. Setup: Create itinerary and an item to delete
    itinerary = Itinerary(
        user_id=test_user.id, name="Trip to Delete Item From", type="Manual", budget="Luxury",
        start_date=date(2025, 12, 1), end_date=date(2025, 12, 5)
    )
    db_session.add(itinerary)
    await db_session.flush()

    item_to_delete = ScheduleItem(
        itinerary_id=itinerary.id,
        place_id="place_to_delete",
        place_name="Ephemeral Place",
        scheduled_date=date(2025, 12, 3),
        scheduled_time="09:00",
        duration_minutes=45
    )
    db_session.add(item_to_delete)
    await db_session.commit()
    await db_session.refresh(item_to_delete)
    item_id = item_to_delete.id

    # 2. Action: Send DELETE request
    delete_response = await authenticated_client.delete(f"/api/itineraries/items/{item_id}")

    # 3. Assertions
    assert delete_response.status_code == 204

    # 4. Verification: Check if the item is gone from the database
    deleted_item = await db_session.get(ScheduleItem, item_id)
    assert deleted_item is None

# --- NEW TEST CASES END HERE ---


@pytest.mark.asyncio
async def test_itc_019_get_notifications(authenticated_client: AsyncClient, db_session: AsyncSession, test_user: User):
    """Tests InTra-ITC-019: Get a list of user's notifications."""
    db_session.add(Notification(user_id=test_user.id, title="Test Notif", body="This is a test."))
    await db_session.commit()

    response = await authenticated_client.get("/api/notifications/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]['title'] == "Test Notif"


@pytest.mark.asyncio
async def test_itc_020_mark_notification_as_read(authenticated_client: AsyncClient, db_session: AsyncSession,
                                                 test_user: User):
    """Tests InTra-ITC-020: Mark a single notification as read."""
    notif = Notification(user_id=test_user.id, title="Unread", body="Mark me as read.", is_read=False)
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    response = await authenticated_client.put(f"/api/notifications/{notif.id}/read")
    assert response.status_code == 200
    assert response.json()['is_read'] is True


@pytest.mark.asyncio
async def test_itc_021_clear_all_notifications(authenticated_client: AsyncClient, db_session: AsyncSession,
                                               test_user: User):
    """Tests InTra-ITC-021: Delete all notifications for a user."""
    db_session.add_all([
        Notification(user_id=test_user.id, title="Notif 1", body="Body 1"),
        Notification(user_id=test_user.id, title="Notif 2", body="Body 2")
    ])
    await db_session.commit()

    get_resp_before = await authenticated_client.get("/api/notifications/")
    assert len(get_resp_before.json()) == 2

    delete_response = await authenticated_client.delete("/api/notifications/")
    assert delete_response.status_code == 204

    get_resp_after = await authenticated_client.get("/api/notifications/")
    assert len(get_resp_after.json()) == 0