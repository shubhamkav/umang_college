from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
import os
import uuid

from app.database.db import get_db
from app.models.participant import Participant
from app.models.registration import Registration
from app.models.event import Event
from app.models.team_member import TeamMember
from app.utils.whatsapp_utils import send_whatsapp_confirmation

router = APIRouter(prefix="/register", tags=["Registration"])

# ==========================
# CONFIG
# ==========================
UPLOAD_DIR = "uploads/aadhaar"
os.makedirs(UPLOAD_DIR, exist_ok=True)

TEAM_SIZE_MAP = {
    "Cricket": 15,
    "Volleyball": 9,
    "Kabaddi": 12,
    "Relay 4x100 m": 4,
    "Relay 4x400 m": 4
}

ALLOWED_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB


# ==========================
# HELPERS
# ==========================
def save_aadhaar(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Invalid Aadhaar file type")

    file.file.seek(0)
    contents = file.file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(400, "Aadhaar file must be under 2MB")

    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(contents)

    return path


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
        raise HTTPException(404, "Event not found")

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
                400,
                "Email already registered with a different roll number"
            )

        if not participant.aadhaar_file:
            participant.aadhaar_file = save_aadhaar(aadhaar)
            db.commit()
    else:
        aadhaar_path = save_aadhaar(aadhaar)

        participant = Participant(
            name=name.strip(),
            roll_number=roll_number.strip(),
            department=department,
            year=year,
            gender=gender,
            email=email.strip(),
            phone=phone.strip(),
            aadhaar_file=aadhaar_path
        )

        db.add(participant)
        db.commit()
        db.refresh(participant)

    # ==========================
    # 3️⃣ MODE VALIDATION
    # ==========================
    if mode == "team":
        if not team_name:
            raise HTTPException(400, "Team name required")

        required = TEAM_SIZE_MAP.get(event.name)
        if required and len(member_names) != required:
            raise HTTPException(
                400,
                f"{event.name} requires exactly {required} players"
            )

    if mode == "pair" and len(member_names) != 1:
        raise HTTPException(400, "Pair requires exactly 2 players")

    if mode == "solo" and member_names:
        raise HTTPException(400, "Solo registration cannot have team members")

    if len(member_names) != len(member_rolls) or len(member_names) != len(member_aadhaars):
        raise HTTPException(400, "Each member must upload Aadhaar")

    # ==========================
    # 4️⃣ DUPLICATE CHECK (FIX)
    # ==========================
    existing = db.query(Registration).filter(
        Registration.participant_id == participant.id,
        Registration.event_id == event.id,
        Registration.mode == mode
    ).first()

    if existing:
        raise HTTPException(
            409,
            f"You are already registered for {event.name} as {mode}"
        )

    # ==========================
    # 5️⃣ REGISTRATION
    # ==========================
    registration = Registration(
        participant_id=participant.id,
        event_id=event.id,
        team_name=team_name,
        mode=mode
    )

    db.add(registration)
    db.commit()
    db.refresh(registration)

    # ==========================
    # 6️⃣ TEAM MEMBERS
    # ==========================
    for i in range(len(member_names)):
        aadhaar_path = save_aadhaar(member_aadhaars[i])

        db.add(TeamMember(
            registration_id=registration.id,
            member_name=member_names[i].strip(),
            member_roll=member_rolls[i].strip(),
            aadhaar_file=aadhaar_path
        ))

    db.commit()

    # ==========================
    # 7️⃣ WHATSAPP
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
    # 8️⃣ RESPONSE
    # ==========================
    return {
        "message": "Registration successful",
        "event": event.name,
        "mode": mode,
        "team": team_name,
        "players": len(member_names) + 1 if mode != "solo" else 1
    }
