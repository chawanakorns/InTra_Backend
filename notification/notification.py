from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from firebase_admin import messaging, credentials, initialize_app
import logging

# Setup
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# CORS for mobile app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firebase Admin
cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(cred)

# Model
class NotificationRequest(BaseModel):
    fcm_token: str
    title: str
    body: str
    data: dict | None = None

# Endpoint
@app.post("/api/send-notification")
async def send_notification(payload: NotificationRequest):
    try:
        message = messaging.Message(
            token=payload.fcm_token,
            notification=messaging.Notification(
                title=payload.title,
                body=payload.body
            ),
            data=payload.data or {}
        )
        response = messaging.send(message)
        logging.info(f"Notification sent: {response}")
        return {"status": "success", "message_id": response}
    except Exception as e:
        logging.error(f"Error sending notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
