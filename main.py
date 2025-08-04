# file: main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
import os

from routes.auth import router as auth_router
from routes.images import router as images_router
from routes.itinerary import router as itinerary_router
from routes.recommendations import router as recommendations_router
from routes.bookmarks import router as bookmarks_router
# --- NEW: Import the notification router ---
from routes.notification import router as notification_router
from database.db import init_db

load_dotenv()

app = FastAPI(title="InTra API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path("uploads").mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(images_router, prefix="/api/images", tags=["images"])
app.include_router(itinerary_router, prefix="/api/itineraries", tags=["itineraries"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])
app.include_router(bookmarks_router, prefix="/api/bookmarks", tags=["bookmarks"])
# --- NEW: Include the notification router ---
app.include_router(notification_router, prefix="/api/notifications", tags=["notifications"])


@app.get("/")
async def root():
    return {"message": "InTra API is running"}

@app.on_event("startup")
async def startup_event():
    await init_db()