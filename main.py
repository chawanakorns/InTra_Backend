# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth import router as auth_router
from routes.recommendations import router as recommendations_router
from routes.itinerary import router as itinerary_router
from routes.bookmarks import router as bookmark_router
from routes.image import router as image_router
from database.db import init_db
from dotenv import load_dotenv
import os

# --- 🛑 1. Import StaticFiles and Path ---
from fastapi.staticfiles import StaticFiles
from pathlib import Path


load_dotenv()

app = FastAPI(title="InTra API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 🛑 2. Mount the 'uploads' directory ---
# This makes any file in your 'uploads' folder accessible via a URL.
# For example: http://your-api-url.com/uploads/image.jpg
# This line should come AFTER `app = FastAPI()` and BEFORE you include your routers.
Path("uploads").mkdir(exist_ok=True) # Ensures the folder exists
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


# Your routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])
app.include_router(itinerary_router, prefix="/api/itineraries", tags=["itineraries"])
app.include_router(bookmark_router, prefix="/api/bookmarks", tags=["bookmarks"])

# Your image router's prefix is /api, and the endpoint is /images, so the full path is correct: /api/images
app.include_router(image_router, prefix="/api", tags=["images"])


@app.get("/")
async def root():
    return {"message": "InTra API"}

@app.on_event("startup")
async def startup_event():
    print(f"Connecting to database: {os.getenv('DB_NAME', 'Intra_DB')} at {os.getenv('DB_HOST', 'localhost')}")
    await init_db()