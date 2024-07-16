from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import List
from datetime import datetime, timedelta
import requests

DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

class SOSAlert(Base):
    __tablename__ = "sos_alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    emergency_button_pressed = Column(Boolean)
    emergency_contacts = Column(JSON)
    gps_location = Column(String)
    vital_info = Column(JSON)

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    reminder_type = Column(String)
    reminder_text = Column(String)
    reminder_time = Column(String)

class VitalInfo(BaseModel):
    spo2: float = Field(..., example=95.5)
    blood_pressure: str = Field(..., example="120/80")
    pulse: int = Field(..., example=75)

    @validator("blood_pressure")
    def validate_blood_pressure(cls, v):
        systolic, diastolic = v.split("/")
        if not systolic.isdigit() or not diastolic.isdigit():
            raise ValueError("Blood pressure should be in the format 'systolic/diastolic'")
        if int(systolic) <= 0 or int(diastolic) <= 0:
            raise ValueError("Blood pressure values should be positive integers")
        return v

class SOSRequest(BaseModel):
    user_id: int = Field(..., example=1)
    emergency_button_pressed: bool = Field(..., example=True)
    emergency_contacts: List[str] = Field(..., example=["John:1234567890", "Jane:9876543210"])
    gps_location: str = Field(..., example="40.712776, -74.005974")
    vital_info: VitalInfo

    @validator("gps_location")
    def validate_gps_location(cls, v):
        try:
            lat, lon = map(float, v.split(","))
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                raise ValueError("Invalid GPS coordinates")
        except Exception as e:
            raise ValueError("Invalid GPS coordinates format")
        return v

    @validator("emergency_contacts")
    def validate_emergency_contacts(cls, v):
        for contact in v:
            parts = contact.split(":")
            if len(parts) != 2 or not parts[1].isdigit():
                raise ValueError("Emergency contact format should be 'Name:Phone'")
        return v

    @validator("user_id")
    def validate_user_id(cls, v):
        if v <= 0:
            raise ValueError("User ID must be a positive integer")
        return v

class ReminderRequest(BaseModel):
    user_id: int = Field(..., example=1)
    reminder_type: str = Field(..., example="Medication")
    reminder_text: str = Field(..., example="Take your blood pressure medication")
    reminder_time: datetime = Field(..., example="2024-06-10T09:00:00")

    @validator("user_id")
    def validate_user_id(cls, v):
        if v <= 0:
            raise ValueError("User ID must be a positive integer")
        return v

    @validator("reminder_type")
    def validate_reminder_type(cls, v):
        allowed_types = {"Medication", "Daily Tasks", "Doctor Appointments"}
        if v not in allowed_types:
            raise ValueError("Invalid reminder type")
        return v

    @validator("reminder_text")
    def validate_reminder_text(cls, v):
        max_words = 50
        if len(v.split()) > max_words:
            raise ValueError(f"Reminder text must be within {max_words} words")
        return v

    @validator("reminder_time")
    def validate_reminder_time(cls, v):
        now = datetime.now()
        if v <= now:
            raise ValueError("Reminder time must be in the future")
        if v <= now + timedelta(minutes=1):
            raise ValueError("Reminder time must be at least 1 minute in the future")
        return v

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def send_sos_alert(sos_alert: SOSAlert):
    message = f"SOS Alert! User ID: {sos_alert.user_id}\n"
    message += f"Location: {sos_alert.gps_location}\n"
    message += "Vital Information:\n"
    message += f"  - SpO2: {sos_alert.vital_info['spo2']}\n"
    message += f"  - Blood Pressure: {sos_alert.vital_info['blood_pressure']}\n"
    message += f"  - Pulse: {sos_alert.vital_info['pulse']}\n"
    for contact in sos_alert.emergency_contacts:
        try:
            response = requests.post(
                "https://api.twilio.com/2010-04-01/Accounts/your_account_sid/Messages.json",
                auth=("your_account_sid", "your_auth_token"),
                data={
                    "From": "your_twilio_phone_number",
                    "To": contact.split(":")[1],
                    "Body": message
                }
            )
            response.raise_for_status()
            print(f"Message sent to {contact}")
        except Exception as e:
            print(f"Failed to send message to {contact}: {e}")

@app.post("/sos/")
async def create_sos_alert(sos: SOSRequest, db: Session = Depends(get_db)):
    sos_alert = SOSAlert(
        user_id=sos.user_id,
        emergency_button_pressed=sos.emergency_button_pressed,
        emergency_contacts=sos.emergency_contacts,
        gps_location=sos.gps_location,
        vital_info=sos.vital_info.dict()
    )
    db.add(sos_alert)
    db.commit()
    db.refresh(sos_alert)
    send_sos_alert(sos_alert)
    return {"message": "SOS alert created", "sos_alert": sos_alert}

@app.post("/reminders/")
async def create_reminder(reminder: ReminderRequest, db: Session = Depends(get_db)):
    reminder = Reminder(
        user_id=reminder.user_id,
        reminder_type=reminder.reminder_type,
        reminder_text=reminder.reminder_text,
        reminder_time=reminder.reminder_time.isoformat()
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return {"message": "Reminder created", "reminder": reminder}

@app.get("/")
async def read_root():
    return {"message": "Person Engagement App API is running"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello, {name}"}

@app.get("/sos/", response_model=List[SOSRequest])
async def read_sos_alerts(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    sos_alerts = db.query(SOSAlert).offset(skip).limit(limit).all()
    return sos_alerts

@app.get("/reminders/", response_model=List[ReminderRequest])
async def read_reminders(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    reminders = db.query(Reminder).offset(skip).limit(limit).all()
    return reminders
