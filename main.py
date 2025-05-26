
from fastapi import FastAPI
from routes.auth import router as auth_router
from database.db import init_db
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="InTra Authentication API")

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])

@app.get("/")
async def root():
    return {"message": "InTra Authentication API"}

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    print(f"Connecting to database: {os.getenv('DB_NAME', 'Intra_DB')} at {os.getenv('DB_HOST', 'localhost')}")
    await init_db()