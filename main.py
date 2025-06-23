from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
import os

# Routers
from routes.auth import router as auth_router
from routes.recommendations import router as recommendations_router
from routes.itinerary import router as itinerary_router
from routes.bookmarks import router as bookmark_router
from routes.images import router as images_router  # ✅ NEW

from database.db import init_db

load_dotenv()

app = FastAPI(title="InTra API")

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create uploads directory if not exists
Path("uploads").mkdir(exist_ok=True)

# Mount uploads for static file serving
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])
app.include_router(itinerary_router, prefix="/api/itineraries", tags=["itineraries"])
app.include_router(bookmark_router, prefix="/api/bookmarks", tags=["bookmarks"])
app.include_router(images_router, prefix="/api/images", tags=["images"])  # ✅ NEW

# Root
@app.get("/")
async def root():
    return {"message": "InTra API"}

# Database startup
@app.on_event("startup")
async def startup_event():
    print(f"Connecting to database: {os.getenv('DB_NAME', 'Intra_DB')} at {os.getenv('DB_HOST', 'localhost')}")
    await init_db()
