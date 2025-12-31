from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.database.db import Base


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True, index=True)

    participant_id = Column(
        Integer,
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False
    )

    event_id = Column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False
    )

    team_name = Column(String(100), nullable=True)

    # ✅ FIX: use STRING instead of PostgreSQL ENUM
    # Allowed values: solo | pair | team (validated in route)
    mode = Column(String(10), nullable=False)

    registered_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "event_id",
            "mode",
            name="uq_participant_event_mode"
        ),
    )
