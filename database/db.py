from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Column, Integer, String, Date, Text, Boolean, JSON, ForeignKey, Float
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# Get database configuration from environment variables
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

# Validate required environment variables
if not DB_PASSWORD:
    raise ValueError("DB_PASSWORD environment variable is required")

# Database URL
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

print(f"Database URL: postgresql+asyncpg://{DB_USER}:****@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# Base class for models
class Base(DeclarativeBase):
    pass


# User model
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)
    email = Column(Text, unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    has_completed_personalization = Column(Boolean, default=False)
    tourist_type = Column(JSON, nullable=True)
    preferred_activities = Column(JSON, nullable=True)
    preferred_cuisines = Column(JSON, nullable=True)
    preferred_dining = Column(JSON, nullable=True)
    preferred_times = Column(JSON, nullable=True)

    itineraries = relationship("Itinerary", back_populates="user")


# Itinerary model
class Itinerary(Base):
    __tablename__ = "itineraries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), nullable=False)
    budget = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # schedule = Column(JSON, nullable=True) # Remove schedule column

    user = relationship("User", back_populates="itineraries")
    schedule_items = relationship("ScheduleItem", back_populates="itinerary") # this

# ScheduleItem model
class ScheduleItem(Base):
    __tablename__ = "schedule_items"

    id = Column(Integer, primary_key=True, index=True)
    itinerary_id = Column(Integer, ForeignKey("itineraries.id"), nullable=False)
    place_id = Column(String(255), nullable=False)
    place_name = Column(String(255), nullable=False)
    place_type = Column(String(255), nullable=True)
    place_address = Column(String(255), nullable=True)
    place_rating = Column(Float, nullable=True)
    place_image = Column(Text, nullable=True)  # Change to Text or increase String length
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(String(50), nullable=False)
    duration_minutes = Column(Integer, default=60)
    # You might also include other relevant fields from the Place data

    itinerary = relationship("Itinerary", back_populates="schedule_items")

# Dependency to get database session
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Context manager for database sessions
@asynccontextmanager
async def get_db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Initialize database tables
async def init_db():
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)