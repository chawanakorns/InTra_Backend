from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Column, Integer, String, Date, Text, Boolean, JSON, ForeignKey, Float, UniqueConstraint
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

if not DB_PASSWORD:
    raise ValueError("DB_PASSWORD environment variable is required")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

print(f"Database URL: postgresql+asyncpg://{DB_USER}:****@{DB_HOST}:{DB_PORT}/{DB_NAME}")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(50), nullable=True)
    email = Column(Text, unique=True, nullable=False, index=True)
    about_me = Column(Text, nullable=True)
    image_uri = Column(Text, nullable=True)
    background_uri = Column(Text, nullable=True)
    has_completed_personalization = Column(Boolean, default=False)
    tourist_type = Column(JSON, nullable=True)
    preferred_activities = Column(JSON, nullable=True)
    preferred_cuisines = Column(JSON, nullable=True)
    preferred_dining = Column(JSON, nullable=True)
    preferred_times = Column(JSON, nullable=True)

    itineraries = relationship("Itinerary", back_populates="user", cascade="all, delete-orphan")
    bookmarks = relationship("Bookmark", back_populates="user", cascade="all, delete-orphan")

class Itinerary(Base):
    __tablename__ = "itineraries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), nullable=False)
    budget = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    user = relationship("User", back_populates="itineraries")
    schedule_items = relationship("ScheduleItem", back_populates="itinerary", cascade="all, delete-orphan")

class ScheduleItem(Base):
    __tablename__ = "schedule_items"

    id = Column(Integer, primary_key=True, index=True)
    itinerary_id = Column(Integer, ForeignKey("itineraries.id"), nullable=False)
    place_id = Column(String(255), nullable=False)
    place_name = Column(String(255), nullable=False)
    place_type = Column(String(255), nullable=True)
    place_address = Column(String(255), nullable=True)
    place_rating = Column(Float, nullable=True)
    place_image = Column(Text, nullable=True)
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(String(50), nullable=False)
    duration_minutes = Column(Integer, default=60)

    itinerary = relationship("Itinerary", back_populates="schedule_items")

class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    place_id = Column(String(255), nullable=False)
    place_name = Column(String(255), nullable=False)
    place_type = Column(String(255), nullable=True)
    place_address = Column(String(255), nullable=True)
    place_rating = Column(Float, nullable=True)
    place_image = Column(Text, nullable=True)

    user = relationship("User", back_populates="bookmarks")
    __table_args__ = (UniqueConstraint('user_id', 'place_id', name='_user_place_uc'),)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

@asynccontextmanager
async def get_db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)