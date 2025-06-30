import pytest
import jwt
from unittest.mock import AsyncMock, patch, MagicMock, call
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import io  # Import io for mocking file open
import os  # Import os for mocking UPLOAD_DIR (useful if UPLOAD_DIR were a Path object initially)
from pathlib import Path  # Import real Path for type hinting in mocks if needed, not for patching directly

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError


# === Mocks for Fixtures ===
class MockSQLAlchemyUser:
    def __init__(self, id=1, email="test@example.com", password="hashed_password", has_completed_personalization=False,
                 tourist_type=None, image_uri=None, background_uri=None):
        self.id = id
        self.email = email
        self.password = password
        self.has_completed_personalization = has_completed_personalization
        self.tourist_type = tourist_type
        self.image_uri = image_uri
        self.background_uri = background_uri


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
# 1. Unit Tests for `models`
###############################################################
from models.user import UserCreate


def test_utc_001_usercreate_password_too_short(mock_user_create_data):
    with pytest.raises(ValidationError):
        UserCreate(**{**mock_user_create_data, "password": "abc"})


def test_utc_002_usercreate_name_is_empty(mock_user_create_data):
    with pytest.raises(ValidationError):
        UserCreate(**{**mock_user_create_data, "full_name": "   "})


###############################################################
# 2. Unit Tests for `utils/security.py`
###############################################################
from utils.security import hash_password, verify_password, create_access_token, SECRET_KEY, ALGORITHM


def test_utc_003_hash_and_verify_password():
    password = "my_correct_password"
    hashed_password = hash_password(password)

    # Test correct password
    actual_result_correct = verify_password(password, hashed_password)
    expected_result_correct = True
    print(f"\n--- UTC_003 - Correct Password ---")
    print(f"Expected: {expected_result_correct}, Actual: {actual_result_correct}")
    assert actual_result_correct is expected_result_correct

    # Test wrong password
    actual_result_wrong = verify_password("wrong_password", hashed_password)
    expected_result_wrong = False
    print(f"\n--- UTC_003 - Wrong Password ---")
    print(f"Expected: {expected_result_wrong}, Actual: {actual_result_wrong}")
    assert actual_result_wrong is expected_result_wrong


def test_utc_004_create_access_token():
    data_to_encode = {"sub": "test@example.com"}
    token = create_access_token(data=data_to_encode)
    decoded_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

    expected_sub = "test@example.com"
    actual_sub = decoded_payload["sub"]
    print(f"\n--- UTC_004 ---")
    print(f"Expected 'sub': {expected_sub}, Actual 'sub': {actual_sub}")
    assert actual_sub == expected_sub


###############################################################
# 3. Unit Tests for `routes/images.py`
###############################################################
from routes.images import _upload_image, UPLOAD_DIR
from database.db import User  # Needed for type hinting in test


@pytest.mark.asyncio
async def test_utc_005_image_upload_invalid_file_type():
    """Tests that the upload helper rejects non-image files."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "application/pdf"
    mock_file.file = io.BytesIO(b"fake pdf content")

    with pytest.raises(HTTPException) as exc:
        await _upload_image(mock_file, MagicMock(spec=User), AsyncMock(), "profile")
    assert exc.value.status_code == 400
    assert "Invalid file type" in exc.value.detail


# Helper to create a mock Path instance with specified suffix and open behavior
def create_mock_path_instance_for_file(suffix):
    mock_path = MagicMock()
    mock_path.suffix = suffix
    mock_path.open.return_value.__enter__.return_value = MagicMock(spec=io.BytesIO)
    return mock_path


@patch('routes.images.shutil.copyfileobj')
@patch('routes.images.uuid.uuid4')
@patch('routes.images.UPLOAD_DIR')  # PATCH THE GLOBAL VARIABLE INSTANCE
@patch('routes.images.Path')  # PATCH THE PATH CLASS ITSELF
@pytest.mark.asyncio
async def test_utc_006_image_upload_profile_success(mock_Path_class, mock_upload_dir_global_var, mock_uuid,
                                                    mock_shutil, mock_db_session):
    """Tests the successful upload flow for a profile image."""
    mock_uuid.return_value.hex = "test_uuid"

    # 1. Configure the mock for Path(file.filename) call
    mock_path_from_filename = create_mock_path_instance_for_file(".jpg")
    mock_Path_class.return_value = mock_path_from_filename  # Path() will return this for `Path(file.filename)`

    # 2. Configure the mock for the global UPLOAD_DIR variable
    # This is the object that `UPLOAD_DIR / filename` is called on
    mock_final_file_path_after_div = create_mock_path_instance_for_file(".jpg")
    mock_upload_dir_global_var.__truediv__.return_value = mock_final_file_path_after_div

    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "image/jpeg"
    mock_file.filename = "test.jpg"
    mock_file.file = io.BytesIO(b"fake image content")  # Essential for copyfileobj

    mock_user = MockSQLAlchemyUser()
    mock_user.image_uri = None

    result = await _upload_image(mock_file, mock_user, mock_db_session, "profile")

    expected_uri = "/uploads/profile_test_uuid.jpg"
    actual_uri = mock_user.image_uri
    print(f"\n--- UTC_006 ---")
    print(f"Expected user image_uri: {expected_uri}, Actual user image_uri: {actual_uri}")
    print(f"Expected result dict: {{'image_uri': '{expected_uri}'}}, Actual result dict: {result}")

    # Assertions
    # Path class should be called once, with file.filename
    mock_Path_class.assert_called_once_with(mock_file.filename)

    # UPLOAD_DIR global variable's __truediv__ should be called once
    mock_upload_dir_global_var.__truediv__.assert_called_once_with(f"profile_test_uuid{mock_path_from_filename.suffix}")

    # The final Path object (result of division) should have its .open method called
    mock_final_file_path_after_div.open.assert_called_once_with("wb")

    mock_shutil.assert_called_once_with(mock_file.file,
                                        mock_final_file_path_after_div.open.return_value.__enter__.return_value)

    assert actual_uri == expected_uri
    mock_db_session.add.assert_called_with(mock_user)
    mock_db_session.commit.assert_awaited_once()
    assert result == {"image_uri": expected_uri}


@patch('routes.images.shutil.copyfileobj')
@patch('routes.images.uuid.uuid4')
@patch('routes.images.UPLOAD_DIR')  # PATCH THE GLOBAL VARIABLE INSTANCE
@patch('routes.images.Path')  # PATCH THE PATH CLASS ITSELF
@pytest.mark.asyncio
async def test_utc_007_image_upload_background_success(mock_Path_class, mock_upload_dir_global_var, mock_uuid,
                                                       mock_shutil, mock_db_session):
    """Tests the successful upload flow for a background image."""
    mock_uuid.return_value.hex = "bg_uuid"

    mock_path_from_filename = create_mock_path_instance_for_file(".png")
    mock_Path_class.return_value = mock_path_from_filename

    mock_final_file_path_after_div = create_mock_path_instance_for_file(".png")
    mock_upload_dir_global_var.__truediv__.return_value = mock_final_file_path_after_div

    mock_file = MagicMock(spec=UploadFile, content_type="image/png", filename="background.png")
    mock_file.file = io.BytesIO(b"fake background content")

    mock_user = MockSQLAlchemyUser()
    mock_user.background_uri = None

    result = await _upload_image(mock_file, mock_user, mock_db_session, "background")

    mock_Path_class.assert_called_once_with(mock_file.filename)

    mock_upload_dir_global_var.__truediv__.assert_called_once_with(f"bg_bg_uuid{mock_path_from_filename.suffix}")
    mock_final_file_path_after_div.open.assert_called_once_with("wb")
    mock_shutil.assert_called_once_with(mock_file.file,
                                        mock_final_file_path_after_div.open.return_value.__enter__.return_value)

    assert mock_user.background_uri == "/uploads/bg_bg_uuid.png"
    mock_db_session.add.assert_called_with(mock_user)
    mock_db_session.commit.assert_awaited_once()
    assert result == {"background_uri": "/uploads/bg_bg_uuid.png"}


@patch('routes.images.shutil.copyfileobj')
@patch('routes.images.uuid.uuid4')
@patch('routes.images.UPLOAD_DIR')  # PATCH THE GLOBAL VARIABLE INSTANCE
@patch('routes.images.Path')  # PATCH THE PATH CLASS ITSELF
@pytest.mark.asyncio
async def test_utc_008_image_upload_db_error(mock_Path_class, mock_upload_dir_global_var, mock_uuid, mock_shutil,
                                             mock_db_session):
    """Tests that a database error during commit is handled correctly."""
    mock_db_session.commit.side_effect = Exception("DB error")
    mock_file = MagicMock(spec=UploadFile, content_type="image/jpeg", filename="fail.jpg")
    mock_file.file = io.BytesIO(b"content")

    mock_path_from_filename = create_mock_path_instance_for_file(".jpg")
    mock_Path_class.return_value = mock_path_from_filename

    mock_final_file_path_after_div = create_mock_path_instance_for_file(".jpg")
    mock_upload_dir_global_var.__truediv__.return_value = mock_final_file_path_after_div

    with pytest.raises(HTTPException) as exc:
        await _upload_image(mock_file, MockSQLAlchemyUser(), mock_db_session, "profile")

    assert exc.value.status_code == 500
    assert "Image upload failed." in exc.value.detail
    mock_db_session.rollback.assert_awaited_once()


###############################################################
# 4. Unit Tests for `routes/itinerary.py`
###############################################################
from routes.itinerary import convert_to_pydantic, add_schedule_item_to_itinerary, ScheduleItemCreate
from models.itinerary import Itinerary as ItineraryResponse


def test_utc_009_itinerary_convert_to_pydantic():
    mock_db_item = SimpleNamespace(place_id="p1", place_name="Place 1", scheduled_date=date(2025, 1, 2),
                                   scheduled_time="10:00", duration_minutes=60, place_type=None, place_address=None,
                                   place_rating=None, place_image=None)
    mock_db_itinerary = SimpleNamespace(id=1, type="Manual", budget="Comfort", name="Trip", start_date=date(2025, 1, 1),
                                        end_date=date(2025, 1, 3), user_id=1, schedule_items=[mock_db_item])

    response = convert_to_pydantic(mock_db_itinerary)
    assert isinstance(response, ItineraryResponse)
    assert response.schedule_items[0].scheduled_date == "2025-01-02"


@patch('routes.itinerary.select')
@pytest.mark.asyncio
async def test_utc_010_itinerary_add_item_date_out_of_range(mock_select, mock_db_session):
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
# 5. Unit Tests for `routes/recommendations.py`
###############################################################
from routes.recommendations import calculate_relevance, build_place_types_query, process_results


def test_utc_011_reco_calculate_relevance():
    prefs = {"tourist_type": ["Cultural"], "preferred_activities": ["Museum"]}

    # Test case 1
    actual_relevance1 = calculate_relevance(["museum", "art_gallery"], prefs)
    expected_relevance1 = 1.0
    print(f"\n--- UTC_011 - Relevance Test Case 1 ---")
    print(f"Preferences: {prefs}, Place Types: ['museum', 'art_gallery']")
    print(f"Expected Relevance: {expected_relevance1}, Actual Relevance: {actual_relevance1}")
    assert actual_relevance1 == expected_relevance1

    # Test case 2
    actual_relevance2 = calculate_relevance(["park", "zoo"], prefs)
    expected_relevance2 = 0.0
    print(f"\n--- UTC_011 - Relevance Test Case 2 ---")
    print(f"Preferences: {prefs}, Place Types: ['park', 'zoo']")
    print(f"Expected Relevance: {expected_relevance2}, Actual Relevance: {actual_relevance2}")
    assert actual_relevance2 == expected_relevance2


def test_utc_012_reco_build_place_types_query():
    prefs = {"tourist_type": ["Adventurous"], "preferred_activities": ["Shopping"]}
    query = build_place_types_query(prefs, "tourist_attraction")
    expected_types = {"amusement_park", "park", "hiking", "zoo", "shopping_mall", "clothing_store", "jewelry_store"}
    assert set(query.split('|')) == expected_types


def test_utc_013_reco_process_results_filters_by_category():
    raw_results = [
        {"name": "Louvre Museum", "place_id": "1", "types": ["museum"]},
        {"name": "Le Bistrot", "place_id": "2", "types": ["restaurant", "food"]},
    ]
    processed = process_results(raw_results, "tourist_attraction", {})
    assert len(processed) == 1
    assert processed[0]['name'] == "Louvre Museum"


###############################################################
# 6. Unit Tests for `services/generation_service.py`
###############################################################
from services.generation_service import generate_itinerary_prompt, auto_generate_schedule
from models.user import UserResponse as PydanticUserResponse
from models.itinerary import ItineraryCreate as PydanticItineraryCreate
from models.recommendations import Place as PydanticPlace


def test_utc_014_generation_prompt_creation():
    it_details = PydanticItineraryCreate(name="My Trip", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                                         budget="Low")
    user_prefs = PydanticUserResponse(id=1, full_name="Test", email="t@t.com", has_completed_personalization=True,
                                      tourist_type=["Cultural"], date_of_birth=date(2000, 1, 1), gender="Male",
                                      about_me=None, image_uri=None, background_uri=None, preferred_activities=None,
                                      preferred_cuisines=None, preferred_dining=None, preferred_times=None)
    attractions = [PydanticPlace(id="p1", name="Museum", rating=4.5, placeId="p1", types=["museum"])]

    prompt = generate_itinerary_prompt(it_details, user_prefs, attractions, [])
    assert "Trip Name: My Trip" in prompt


@pytest.mark.asyncio
async def test_utc_015_auto_generate_schedule_parses_json():
    mock_gemini_model = AsyncMock()
    expected_response_text = '```json\n[{"place_id": "p1", "place_name": "Test Place", "scheduled_date": "2025-01-01", "scheduled_time": "09:00", "duration_minutes": 120}]\n```'
    mock_gemini_model.generate_content_async.return_value = MagicMock(text=expected_response_text)

    with patch('services.generation_service.genai.GenerativeModel', return_value=mock_gemini_model):
        with patch('services.generation_service.configure_gemini'):
            result = await auto_generate_schedule(MagicMock(), MagicMock(), [], [])

    expected_result = [
        {"place_id": "p1", "place_name": "Test Place", "scheduled_date": "2025-01-01", "scheduled_time": "09:00",
         "duration_minutes": 120}]
    print(f"\n--- UTC_015 ---")
    print(f"Expected Parsed Result: {expected_result}")
    print(f"Actual Parsed Result: {result}")
    assert result == expected_result


@pytest.mark.asyncio
async def test_utc_016_auto_generate_schedule_handles_bad_json():
    mock_gemini_model = AsyncMock()
    mock_gemini_model.generate_content_async.return_value = MagicMock(text='This is not JSON.')

    with patch('services.generation_service.genai.GenerativeModel', return_value=mock_gemini_model):
        with patch('services.generation_service.configure_gemini'):
            result = await auto_generate_schedule(MagicMock(), MagicMock(), [], [])

    expected_result = []
    print(f"\n--- UTC_016 ---")
    print(f"Expected Result (for bad JSON): {expected_result}")
    print(f"Actual Result (for bad JSON): {result}")
    assert result == expected_result