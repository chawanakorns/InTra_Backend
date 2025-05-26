
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from models.user import UserCreate, UserResponse, Token
from services.auth import register_user, authenticate_user, get_current_user

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Dependency function for getting current user from token
async def get_current_user_dependency(token: str = Depends(oauth2_scheme)):
    return await get_current_user(token)

@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate):
    return await register_user(user)

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    return await authenticate_user(form_data.username, form_data.password)

@router.post("/logout")
async def logout(current_user: UserResponse = Depends(get_current_user_dependency)):
    return {"message": "Logged out successfully"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user_dependency)):
    return current_user