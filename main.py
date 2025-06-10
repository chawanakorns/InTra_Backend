from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth import router as auth_router
from routes.recommendations import router as recommendations_router
from database.db import init_db
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="InTra API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(recommendations_router, prefix="/api", tags=["recommendations"])

@app.get("/")
async def root():
    return {"message": "InTra API"}


@app.on_event("startup")
async def startup_event():
    print(f"Connecting to database: {os.getenv('DB_NAME', 'Intra_DB')} at {os.getenv('DB_HOST', 'localhost')}")
    await init_db()
