# file: main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
import os

# Import all your routers
from routes.auth import router as auth_router
from routes.images import router as images_router
# ... add other routers here

from database.db import init_db

load_dotenv()

app = FastAPI(title="InTra API")

# Allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create the 'uploads' directory if it doesn't exist
Path("uploads").mkdir(exist_ok=True)

# ✅ CRITICAL LINE: This tells FastAPI to serve files from the "uploads" directory
# when a request comes in for a path starting with "/uploads".
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include all your API routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(images_router, prefix="/api/images", tags=["images"])
# ... add other routers here

@app.get("/")
async def root():
    return {"message": "InTra API is running"}

@app.on_event("startup")
async def startup_event():
    await init_db()