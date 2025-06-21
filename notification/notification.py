from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ItineraryCreate(BaseModel):
    id: str
    type: str
    budget: str
    name: str
    startDate: str
    endDate: str
    schedule: list

def init_db():
    try:
        conn = sqlite3.connect("itineraries.db")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS itineraries
                     (id TEXT PRIMARY KEY, type TEXT, budget TEXT, name TEXT, startDate TEXT, endDate TEXT, schedule TEXT)''')
        conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise
    finally:
        conn.close()

init_db()

@app.post("/api/itineraries")
async def create_itinerary(itinerary: ItineraryCreate):
    logger.info(f"Received request to create itinerary: {itinerary}")
    conn = sqlite3.connect("itineraries.db")
    c = conn.cursor()
    schedule_str = json.dumps(itinerary.schedule)  # Convert list to JSON string

    try:
        c.execute(
            "INSERT INTO itineraries (id, type, budget, name, startDate, endDate, schedule) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (itinerary.id, itinerary.type, itinerary.budget, itinerary.name, itinerary.startDate, itinerary.endDate, schedule_str)
        )
        conn.commit()
        created_itinerary = {
            "id": itinerary.id,
            "type": itinerary.type,
            "budget": itinerary.budget,
            "name": itinerary.name,
            "startDate": itinerary.startDate,
            "endDate": itinerary.endDate,
            "schedule": itinerary.schedule
        }
        logger.info(f"Successfully created itinerary: {created_itinerary}")
        conn.close()
        return created_itinerary
    except sqlite3.IntegrityError as e:
        conn.close()
        logger.error(f"IntegrityError: {str(e)}")
        raise HTTPException(status_code=400, detail="Itinerary with this ID already exists")
    except Exception as e:
        conn.close()
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/itineraries")
async def get_itineraries():
    try:
        conn = sqlite3.connect("itineraries.db")
        c = conn.cursor()
        c.execute("SELECT * FROM itineraries")
        rows = c.fetchall()
        itineraries = [
            {
                "id": row[0],
                "type": row[1],
                "budget": row[2],
                "name": row[3],
                "startDate": row[4],
                "endDate": row[5],
                "schedule": json.loads(row[6]) if row[6] else []
            }
            for row in rows
        ]
        conn.close()
        logger.info(f"Retrieved {len(itineraries)} itineraries")
        return itineraries
    except Exception as e:
        logger.error(f"Error retrieving itineraries: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/notifications")
async def send_notification(title: str, message: str):
    logger.info(f"Notification sent: {title} - {message}")
    return {"status": "success", "title": title, "message": message}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)