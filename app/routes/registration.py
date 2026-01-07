from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
import uuid

import cloudinary
import cloudinary.uploader

from app.database.db import get_db
from app.models.participant import Participant
from app.models.registration import Registration
from app.models.event import Event
from app.models.team_member import TeamMember
from app.utils.whatsapp_utils import send_whatsapp_confirmation

router = APIRouter(prefix="/register", tags=["Registration"])

# ==========================
# CLOUDINARY CONFIG (FREE, NO .env)
# ==========================

cloudinary.config(
    cloud_name="dljsz4msc",
    api_key="812755949136866",
    api_secret="1ovTVgsgeq4NYcAUOlsPoa2sk28",
    secure=True
)

# ==========================
# CONFIG
# ==========================
TEAM_SIZE_MAP = {
    "Cricket": 15,
    "Volleyball": 9,
    "Kabaddi": 12,
    "Relay 4x100 m": 4,
    "Relay 4x400 m": 4,
    "Debate" : 3
}

ALLOWED_TYPES = {"image/jpeg", "image/png", "application/pdf"}

# ==========================
# HELPERS (STEP 2 FIX)
# ==========================
def save_aadhaar(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid Aadhaar file type")

    try:
        result = cloudinary.uploader.upload(
            file.file,
            folder="aadhaar",
            resource_type="auto"  # supports image + pdf
        )
        return result["secure_url"]   # 🔥 STORE URL IN DB

    except Exception as e:
        print("❌ CLOUDINARY UPLOAD ERROR:", e)
        raise HTTPException(status_code=500, detail="Aadhaar upload failed")


# ==========================
# REGISTER EVENT
# ==========================
@router.post("/")
def register_event(
    event_id: int = Form(...),
    name: str = Form(...),
    roll_number: str = Form(...),
    department: str = Form(...),
    year: str = Form(...),
    gender: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    mode: str = Form(...),  # solo | pair | team

    aadhaar: UploadFile = File(...),

    team_name: str = Form(None),

    member_names: List[str] = Form([]),
    member_rolls: List[str] = Form([]),
    member_aadhaars: List[UploadFile] = File([]),

    db: Session = Depends(get_db)
):

    # ==========================
    # 1️⃣ EVENT
    # ==========================
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # ==========================
    # 2️⃣ PARTICIPANT
    # ==========================
    participant = db.query(Participant).filter(
        (Participant.roll_number == roll_number) |
        (Participant.email == email)
    ).first()

    if participant:
        if participant.roll_number != roll_number:
            raise HTTPException(
                status_code=400,
                detail="Email already registered with a different roll number"
            )

        if not participant.aadhaar_file:
            participant.aadhaar_file = save_aadhaar(aadhaar)
            db.commit()

    else:
        aadhaar_url = save_aadhaar(aadhaar)

        participant = Participant(
            name=name.strip(),
            roll_number=roll_number.strip(),
            department=department,
            year=year,
            gender=gender,
            email=email.strip(),
            phone=phone.strip(),
            aadhaar_file=aadhaar_url
        )

        db.add(participant)
        try:
            db.commit()
            db.refresh(participant)
        except IntegrityError as e:
            db.rollback()
            print("❌ PARTICIPANT INSERT ERROR:", e.orig)
            raise HTTPException(
                status_code=400,
                detail="Participant already exists"
            )

    # ==========================
    # 3️⃣ VALIDATION
    # ==========================
    if mode == "team":
        if not team_name:
            raise HTTPException(400, "Team name required")

        required = TEAM_SIZE_MAP.get(event.name)
        if required and len(member_names) != required:
            raise HTTPException(
                400, f"{event.name} requires exactly {required} players"
            )

    if mode == "pair" and len(member_names) != 2:
        raise HTTPException(400, "Pair requires exactly 2 players")

    if mode == "solo" and member_names:
        raise HTTPException(400, "Solo registration cannot have team members")

    if len(member_names) != len(member_rolls) or len(member_names) != len(member_aadhaars):
        raise HTTPException(400, "Each member must upload Aadhaar")

    # ==========================
    # 4️⃣ REGISTRATION
    # ==========================
    registration = Registration(
        participant_id=participant.id,
        event_id=event.id,
        team_name=team_name,
        mode=mode
    )

    db.add(registration)

    try:
        db.commit()
        db.refresh(registration)
    except IntegrityError as e:
        db.rollback()
        print("❌ REGISTRATION INSERT ERROR:", e.orig)
        raise HTTPException(
            status_code=400,
            detail="Registration failed. Duplicate entry or invalid data."
        )

    # ==========================
    # 5️⃣ TEAM / PAIR MEMBERS
    # ==========================
    for i in range(len(member_names)):
        aadhaar_url = save_aadhaar(member_aadhaars[i])

        db.add(TeamMember(
            registration_id=registration.id,
            member_name=member_names[i].strip(),
            member_roll=member_rolls[i].strip(),
            aadhaar_file=aadhaar_url
        ))

    db.commit()

    # ==========================
    # 6️⃣ WHATSAPP
    # ==========================
    try:
        send_whatsapp_confirmation(
            phone=participant.phone,
            name=participant.name,
            event=event.name,
            category=event.category,
            team=team_name
        )
    except Exception:
        pass

    # ==========================
    # 7️⃣ RESPONSE
    # ==========================
    return {
        "message": "Registration successful",
        "event": event.name,
        "mode": mode,
        "team": team_name,
        "players": len(member_names) if member_names else 1
    }
