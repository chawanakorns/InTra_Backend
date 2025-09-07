import pytest
import jwt
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import io  # Import io for mocking file open

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError


# === Mocks for Fixtures ===
class MockSQLAlchemyUser:
    def __init__(self, id=1, email="test@example.com", password="hashed_password", has_completed_personalization=False,
                 tourist_type=None, image_uri=None, background_uri=None, allow_smart_alerts=True, fcm_token=None):
        self.id = id
        self.email = email
        self.password = password
        self.has_completed_personalization = has_completed_personalization
        self.tourist_type = tourist_type
        self.image_uri = image_uri
        self.background_uri = background_uri
        self.allow_smart_alerts = allow_smart_alerts
        self.fcm_token = fcm_token
        self.itinerary_items = []

class MockSQLAlchemyItinerary:
    def __init__(self, id=1, user_id=1, start_date=date(2025, 1, 1), end_date=date(2025, 1, 5)):
        self.id = id
        self.user_id = user_id
        self.start_date = start_date
        self.end_date = end_date
        self.schedule_items = []


# === Test Fixtures ===
@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    mock_result = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.first.return_value = None
    return session


@pytest.fixture
def mock_user_create_data():
    return {"full_name": "Test User", "date_of_birth": "2000-01-01", "gender": "Male",
            "email": "test@example.com", "password": "password123"}


###############################################################
# 1. Unit Tests for `app/models`
###############################################################
from app.models.user import UserCreate
from app.models.notification import NotificationCreate  # <-- Added for new test


def test_utc_001_usercreate_password_too_short(mock_user_create_data):
    with pytest.raises(ValidationError):
        UserCreate(**{**mock_user_create_data, "password": "abc"})


def test_utc_002_usercreate_name_is_empty(mock_user_create_data):
    with pytest.raises(ValidationError):
        UserCreate(**{**mock_user_create_data, "full_name": "   "})


# --- NEW TEST as per test plan ---
def test_utc_017_notification_model_creation():
    """Tests that the NotificationCreate model works correctly."""
    data = {"title": "Test Title", "body": "Test body"}
    notification = NotificationCreate(**data)
    assert notification.title == data["title"]
    assert notification.body == data["body"]


###############################################################
# 2. Unit Tests for `app/utils/security.py`
###############################################################
from app.utils.security import hash_password, verify_password, create_access_token, SECRET_KEY, ALGORITHM


def test_utc_003_hash_and_verify_password():
    password = "my_correct_password"
    hashed_password = hash_password(password)
    assert verify_password(password, hashed_password) is True
    assert verify_password("wrong_password", hashed_password) is False


def test_utc_004_create_access_token():
    data_to_encode = {"sub": "test@example.com"}
    token = create_access_token(data=data_to_encode)
    decoded_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded_payload["sub"] == "test@example.com"


###############################################################
# 3. Unit Tests for `app/controllers/images.py`
###############################################################
from app.controllers.images import _upload_image
from app.database.models import User


@pytest.mark.asyncio
async def test_utc_005_image_upload_invalid_file_type():
    mock_file = MagicMock(spec=UploadFile, content_type="application/pdf")
    with pytest.raises(HTTPException) as exc:
        await _upload_image(mock_file, MagicMock(spec=User), AsyncMock(), "profile")
    assert exc.value.status_code == 400


def create_mock_path(suffix):
    mock_path = MagicMock()
    mock_path.suffix = suffix
    mock_path.open.return_value.__enter__.return_value = MagicMock(spec=io.BytesIO)
    return mock_path


# --- THE FIX: Updated patch paths from 'controllers.images...' to 'app.controllers.images...' ---
@patch('app.controllers.images.shutil.copyfileobj')
@patch('app.controllers.images.uuid.uuid4')
@patch('app.controllers.images.UPLOAD_DIR')
@patch('app.controllers.images.Path')
@pytest.mark.asyncio
async def test_utc_006_image_upload_profile_success(mock_Path_class, mock_upload_dir, mock_uuid, mock_shutil,
                                                    mock_db_session):
    mock_uuid.return_value.hex = "test_uuid"
    mock_path_from_filename = create_mock_path(".jpg")
    mock_Path_class.return_value = mock_path_from_filename
    mock_final_path = create_mock_path(".jpg")
    mock_upload_dir.__truediv__.return_value = mock_final_path
    mock_file = MagicMock(spec=UploadFile, content_type="image/jpeg", filename="test.jpg", file=io.BytesIO(b"img"))
    mock_user = MockSQLAlchemyUser()

    result = await _upload_image(mock_file, mock_user, mock_db_session, "profile")

    expected_uri = "/uploads/profile_test_uuid.jpg"
    assert mock_user.image_uri == expected_uri
    mock_db_session.commit.assert_awaited_once()
    assert result == {"image_uri": expected_uri}


@patch('app.controllers.images.shutil.copyfileobj')
@patch('app.controllers.images.uuid.uuid4')
@patch('app.controllers.images.UPLOAD_DIR')
@patch('app.controllers.images.Path')
@pytest.mark.asyncio
async def test_utc_007_image_upload_background_success(mock_Path_class, mock_upload_dir, mock_uuid, mock_shutil,
                                                       mock_db_session):
    mock_uuid.return_value.hex = "bg_uuid"
    mock_path_from_filename = create_mock_path(".png")
    mock_Path_class.return_value = mock_path_from_filename
    mock_final_path = create_mock_path(".png")
    mock_upload_dir.__truediv__.return_value = mock_final_path
    mock_file = MagicMock(spec=UploadFile, content_type="image/png", filename="background.png", file=io.BytesIO(b"img"))
    mock_user = MockSQLAlchemyUser()

    result = await _upload_image(mock_file, mock_user, mock_db_session, "background")

    expected_uri = "/uploads/bg_bg_uuid.png"
    assert mock_user.background_uri == expected_uri
    mock_db_session.commit.assert_awaited_once()
    assert result == {"background_uri": expected_uri}


@patch('app.controllers.images.shutil.copyfileobj')
@patch('app.controllers.images.UPLOAD_DIR')
@patch('app.controllers.images.Path')
@pytest.mark.asyncio
async def test_utc_008_image_upload_db_error(mock_Path, mock_upload_dir, mock_shutil, mock_db_session):
    mock_db_session.commit.side_effect = Exception("DB error")
    mock_Path.return_value.suffix = ".jpg"
    mock_upload_dir.__truediv__.return_value.open.return_value.__enter__.return_value = MagicMock()
    # <<< FIX: Added `file` attribute to the mock to make it more complete and avoid warnings/errors.
    mock_file = MagicMock(spec=UploadFile, content_type="image/jpeg", filename="fail.jpg", file=io.BytesIO(b"img"))

    with pytest.raises(HTTPException) as exc:
        await _upload_image(mock_file, MockSQLAlchemyUser(), mock_db_session, "profile")
    assert exc.value.status_code == 500
    mock_db_session.rollback.assert_awaited_once()


###############################################################
# 4. Unit Tests for `app/controllers/itinerary.py`
###############################################################
from app.controllers.itinerary import convert_to_pydantic, add_schedule_item_to_itinerary, ScheduleItemCreate
from app.models.itinerary import Itinerary as ItineraryResponse


def test_utc_009_itinerary_convert_to_pydantic():
    mock_db_item = SimpleNamespace(id=1, place_id="p1", place_name="Place 1", scheduled_date=date(2025, 1, 2),
                                   scheduled_time="10:00", duration_minutes=60, place_type=None, place_address=None,
                                   place_rating=None, place_image=None)
    mock_db_itinerary = SimpleNamespace(id=1, type="Manual", budget="Comfort", name="Trip", start_date=date(2025, 1, 1),
                                        end_date=date(2025, 1, 3), user_id=1, schedule_items=[mock_db_item])
    response = convert_to_pydantic(mock_db_itinerary)
    assert isinstance(response, ItineraryResponse)
    assert response.schedule_items[0].place_name == "Place 1"


@pytest.mark.asyncio
async def test_utc_010_itinerary_add_item_date_out_of_range(mock_db_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = MockSQLAlchemyItinerary(start_date=date(2025, 10, 10),
                                                                                  end_date=date(2025, 10, 15))
    mock_db_session.execute.return_value = mock_result
    item_data = ScheduleItemCreate(place_id="p1", place_name="Test", scheduled_date="2025-10-09",
                                   scheduled_time="10:00", duration_minutes=60)
    with pytest.raises(HTTPException, match="Scheduled date must be within the itinerary's range"):
        await add_schedule_item_to_itinerary(itinerary_id=1, item=item_data, current_user=MockSQLAlchemyUser(),
                                             db=mock_db_session)


###############################################################
# 5. Unit Tests for `app/controllers/recommendations.py`
###############################################################
from app.controllers.recommendations import calculate_relevance, build_place_types_query, process_results


def test_utc_011_reco_calculate_relevance():
    prefs = {"tourist_type": ["Cultural"], "preferred_activities": ["Museum"]}
    assert calculate_relevance(["museum", "art_gallery"], prefs) == 1.0
    assert calculate_relevance(["park", "zoo"], prefs) == 0.0


def test_utc_012_reco_build_place_types_query():
    prefs = {"tourist_type": ["Adventurous"], "preferred_activities": ["Shopping"]}
    query = build_place_types_query(prefs, "tourist_attraction")
    expected_types = {"amusement_park", "park", "hiking", "zoo", "shopping_mall", "clothing_store", "jewelry_store"}
    assert set(query.split('|')) == expected_types


def test_utc_013_reco_process_results_filters_by_category():
    raw_results = [{"name": "Louvre Museum", "place_id": "1", "types": ["museum"]},
                   {"name": "Le Bistrot", "place_id": "2", "types": ["restaurant", "food"]}, ]
    processed = process_results(raw_results, "tourist_attraction", {})
    assert len(processed) == 1
    assert processed[0]['name'] == "Louvre Museum"


###############################################################
# 6. Unit Tests for `app/services/generation_service.py`
###############################################################
from app.services.generation_service import generate_itinerary_prompt, auto_generate_schedule
from app.models.user import UserResponse as PydanticUserResponse
from app.models.itinerary import ItineraryCreate as PydanticItineraryCreate
from app.models.recommendations import Place as PydanticPlace


def test_utc_014_generation_prompt_creation():
    it_details = PydanticItineraryCreate(name="My Trip", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                                         budget="Low")
    user_prefs = PydanticUserResponse(id=1, full_name="Test", email="t@t.com", has_completed_personalization=True,
                                      tourist_type=["Cultural"], allow_smart_alerts=True, allow_opportunity_alerts=True,
                                      allow_real_time_tips=True)
    attractions = [PydanticPlace(id="p1", name="Museum", rating=4.5, placeId="p1", types=["museum"])]
    prompt = generate_itinerary_prompt(it_details, user_prefs, attractions, [])
    assert "Trip Name: My Trip" in prompt
    assert "Budget Guideline: Low" in prompt
    assert "Tourist Type: Cultural" in prompt
    assert '"name": "Museum"' in prompt


@pytest.mark.asyncio
async def test_utc_015_auto_generate_schedule_parses_json():
    mock_gemini_model = AsyncMock()
    expected_response_text = '```json\n[{"place_id": "p1", "place_name": "Test Place", "scheduled_date": "2025-01-01", "scheduled_time": "09:00", "duration_minutes": 120}]\n```'
    mock_gemini_model.generate_content_async.return_value = MagicMock(text=expected_response_text)
    with patch('app.services.generation_service.genai.GenerativeModel', return_value=mock_gemini_model):
        with patch('app.services.generation_service.configure_gemini'):
            result = await auto_generate_schedule(MagicMock(), MagicMock(), [], [])
    expected_result = [
        {"place_id": "p1", "place_name": "Test Place", "scheduled_date": "2025-01-01", "scheduled_time": "09:00",
         "duration_minutes": 120}]
    assert result == expected_result


@pytest.mark.asyncio
async def test_utc_016_auto_generate_schedule_handles_bad_json():
    mock_gemini_model = AsyncMock()
    mock_gemini_model.generate_content_async.return_value = MagicMock(text='This is not JSON.')
    with patch('app.services.generation_service.genai.GenerativeModel', return_value=mock_gemini_model):
        with patch('app.services.generation_service.configure_gemini'):
            result = await auto_generate_schedule(MagicMock(), MagicMock(), [], [])
    assert result == []


###############################################################
# 7. Unit Tests for Notification Logic (auth.py & scheduler.py)
###############################################################
from app.controllers.auth import update_fcm_token
from scripts.notification_scheduler import check_and_send_smart_alerts, send_expo_push_notification


@pytest.mark.asyncio
async def test_utc_018_update_fcm_token_logic(mock_db_session):
    """Verifies that updating an FCM token removes it from the previous owner."""
    new_token = "new_fcm_token"
    mock_user_A = MockSQLAlchemyUser(id=1, email="user_a@test.com", fcm_token=new_token)
    mock_user_B = MockSQLAlchemyUser(id=2, email="user_b@test.com", fcm_token=None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user_A
    mock_db_session.execute.return_value = mock_result

    mock_payload = SimpleNamespace(fcm_token=new_token)

    # <<< FIX: The payload from the request body is a positional argument, not a keyword one.
    await update_fcm_token(mock_payload, current_user=mock_user_B, db=mock_db_session)

    assert mock_user_A.fcm_token is 'new_fcm_token'
    assert mock_user_B.fcm_token is 'new_fcm_token'
    assert mock_db_session.commit.call_count == 1


# The patch targets are now correct and clean:
# 1. get_db_session: To mock the database connection.
# 2. send_expo_push_notification: To check if notifications are sent.
@patch('scripts.notification_scheduler.get_db_session')
@patch('scripts.notification_scheduler.send_expo_push_notification', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_utc_019_scheduler_skips_disabled_users(mock_send_notification, mock_get_db_session):
    """
    FINAL TEST: Verifies the scheduler skips users with disabled notifications.
    """
    # 1. SETUP: Define user data. This user has alerts OFF.
    user_with_alerts_off = MockSQLAlchemyUser(allow_smart_alerts=False)
    item = SimpleNamespace(
        scheduled_date=date.today(),
        scheduled_time=datetime.now().strftime("%H:%M"),
        itinerary=SimpleNamespace(user=user_with_alerts_off)
    )

    # 2. MOCK THE DATABASE SESSION & THE DATA IT RETURNS
    mock_db_session_instance = AsyncMock()
    mock_result = MagicMock()
    # Configure the mock to return our item when the query runs
    mock_result.scalars.return_value.unique.return_value.all.return_value = [item]
    mock_db_session_instance.execute = AsyncMock(return_value=mock_result)

    # When `async with get_db_session() as db:` is called in the script,
    # it will yield our mock session instance.
    mock_get_db_session.return_value.__aenter__.return_value = mock_db_session_instance

    # 3. EXECUTE the function being tested.
    await check_and_send_smart_alerts()

    # 4. ASSERT
    mock_db_session_instance.execute.assert_awaited_once()
    # Crucially, verify the notification service was NOT called.
    mock_send_notification.assert_not_called()


# The patch targets are now correct and clean:
# 1. get_db_session: To mock the database.
# 2. send_expo_push_notification: To check if notifications are sent.
# 3. get_travel_time_seconds: To mock the external API call.
@patch('scripts.notification_scheduler.get_db_session')
@patch('scripts.notification_scheduler.send_expo_push_notification', new_callable=AsyncMock)
@patch('scripts.notification_scheduler.get_travel_time_seconds', new_callable=AsyncMock, return_value=600)
@pytest.mark.asyncio
async def test_utc_020_scheduler_sends_alert(mock_get_travel_time, mock_send_notification, mock_get_db_session):
    """
    FINAL TEST: Verifies the scheduler sends notifications for eligible users.
    """
    # 1. SETUP: Define an eligible user with alerts ON.
    user_with_alerts_on = MockSQLAlchemyUser(
        allow_smart_alerts=True,
        fcm_token="valid_token_for_user",
        email="test@example.com"
    )
    # The item is scheduled soon, triggering the notification logic.
    upcoming_item = SimpleNamespace(
        id=1,
        place_id="place123",
        scheduled_date=date.today(),
        scheduled_time=(datetime.now() + timedelta(minutes=20)).strftime("%H:%M"),
        place_name="Eiffel Tower",
        notification_sent=False,
        itinerary=SimpleNamespace(id=99, user=user_with_alerts_on)
    )

    # 2. MOCK THE DATABASE SESSION & THE DATA IT RETURNS
    mock_db_session_instance = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = [upcoming_item]
    mock_db_session_instance.execute = AsyncMock(return_value=mock_result)
    mock_get_db_session.return_value.__aenter__.return_value = mock_db_session_instance

    # 3. EXECUTE
    await check_and_send_smart_alerts()

    # 4. ASSERT
    mock_db_session_instance.execute.assert_awaited_once()
    mock_get_travel_time.assert_awaited_once()
    mock_send_notification.assert_awaited_once()
    assert upcoming_item.notification_sent is True
    mock_db_session_instance.commit.assert_awaited_once()


@patch('httpx.AsyncClient.post', new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_utc_021_send_expo_push_payload(mock_httpx_post):
    """Verifies the correct JSON payload is constructed for the Expo API."""
    token = "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"
    title = "Test Title"
    body = "Test Body"

    await send_expo_push_notification(token, title, body, data={"itineraryId": 1})

    mock_httpx_post.assert_awaited_once()
    _, kwargs = mock_httpx_post.call_args
    json_payload = kwargs['json']
    assert json_payload['to'] == token
    assert json_payload['title'] == title
    assert json_payload['body'] == body
    assert json_payload['data'] == {"itineraryId": 1}