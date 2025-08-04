# file: main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv

# Updated imports to reflect new structure
from app.controllers import auth, images, itinerary, recommendations, bookmarks, notification
from app.database.connection import init_db

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

# Include routers from the controllers directory
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(images.router, prefix="/api/images", tags=["Images"])
app.include_router(itinerary.router, prefix="/api/itineraries", tags=["Itineraries"])
app.include_router(recommendations.router, prefix="/api", tags=["Recommendations"])
app.include_router(bookmarks.router, prefix="/api/bookmarks", tags=["Bookmarks"])
app.include_router(notification.router, prefix="/api/notifications", tags=["Notifications"])

@app.get("/")
async def root():
    return {"message": "InTra API is running"}

@app.on_event("startup")
async def startup_event():
    await init_db()