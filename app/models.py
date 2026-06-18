"""
Database models (SQLAlchemy ORM) and Pydantic v2 request/response schemas.

Booking fields mirror the TypeScript schema in shared/schema.ts for
compatibility with the main portfolio gateway.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ── SQLAlchemy ORM Model ──────────────────────────────────────────────────────

class BookingModel(Base):
    """bookings table — one row per scheduled consultation."""
    __tablename__ = "bookings"
    __table_args__ = (
        # Prevent double-booking the same slot at the DB level.
        # Partial uniqueness: only active (non-cancelled) bookings block a slot.
        # SQLite doesn't support partial indexes via DDL so we use a plain
        # unique constraint on (date, time) and rely on cancellation freeing slots
        # at the application layer (mark_booked / free_slot on the index).
        UniqueConstraint("date", "time", name="uq_booking_slot"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meeting_type: Mapped[str] = mapped_column(Text, nullable=False, default="discovery")
    details: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str] = mapped_column(Text, nullable=False)   # "YYYY-MM-DD"
    time: Mapped[str] = mapped_column(Text, nullable=False)   # "HH:MM"
    status: Mapped[str] = mapped_column(Text, nullable=False, default="confirmed")
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

MEETING_TYPES = {
    "discovery", "architecture", "microservices",
    "automation", "devops", "ai",
}

TIME_PATTERN = r"^\d{1,2}:\d{2}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class BookingCreate(BaseModel):
    """Request body for POST /v1/bookings."""
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    company: Optional[str] = Field(None, max_length=120)
    meeting_type: str = Field("discovery", alias="meetingType")
    details: str = Field(..., min_length=10, max_length=2000)
    date: str = Field(..., pattern=DATE_PATTERN)
    time: str = Field(..., pattern=TIME_PATTERN)

    model_config = {"populate_by_name": True}

    @field_validator("meeting_type")
    @classmethod
    def validate_meeting_type(cls, v: str) -> str:
        if v not in MEETING_TYPES:
            raise ValueError(f"meeting_type must be one of {sorted(MEETING_TYPES)}")
        return v


class BookingUpdate(BaseModel):
    """Request body for PATCH /v1/bookings/{id}."""
    status: Optional[str] = None
    cancel_reason: Optional[str] = Field(None, max_length=500, alias="cancelReason")
    cancelled: Optional[bool] = None

    model_config = {"populate_by_name": True}


class BookingResponse(BaseModel):
    """Response schema for a booking — camelCase for frontend compat."""
    id: str
    name: str
    email: str
    company: Optional[str] = None
    meeting_type: str = Field(serialization_alias="meetingType")
    details: str
    date: str
    time: str
    status: str
    cancelled: bool
    cancel_reason: Optional[str] = Field(None, serialization_alias="cancelReason")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def from_orm(cls, obj: BookingModel) -> "BookingResponse":
        return cls(
            id=obj.id,
            name=obj.name,
            email=obj.email,
            company=obj.company,
            meeting_type=obj.meeting_type,
            details=obj.details,
            date=obj.date,
            time=obj.time,
            status=obj.status,
            cancelled=obj.cancelled,
            cancel_reason=obj.cancel_reason,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class ErrorResponse(BaseModel):
    """Standard error envelope used by all endpoints."""
    error: str
    code: str
    details: dict = Field(default_factory=dict)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime: float


class InfoResponse(BaseModel):
    name: str
    version: str
    port: int
    endpoints: list[dict]
    description: str
