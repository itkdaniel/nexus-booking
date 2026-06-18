"""
Booking CRUD endpoints.

GET  /v1/bookings          — list all (admin only)
POST /v1/bookings          — create booking (public)
GET  /v1/bookings/{id}     — single booking
PATCH /v1/bookings/{id}    — update status/cancel (admin)
DELETE /v1/bookings/{id}   — hard delete (admin)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, get_optional_user
from app.database import get_db_dep
from app.models import (
    BookingCreate, BookingModel, BookingResponse, BookingUpdate, ErrorResponse
)
from app.services.availability import get_availability_index
from app.services.email import dispatch_booking_emails

logger = logging.getLogger("nexus-booking.bookings")
router = APIRouter(prefix="/v1/bookings", tags=["bookings"])


@router.get(
    "",
    response_model=List[BookingResponse],
    summary="List all bookings (admin only)",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def list_bookings(
    db: AsyncSession = Depends(get_db_dep),
    _admin: dict = Depends(require_admin),
) -> List[BookingResponse]:
    """Return all bookings ordered by creation date (newest first)."""
    result = await db.execute(
        select(BookingModel).order_by(BookingModel.created_at.desc())
    )
    rows = result.scalars().all()
    return [BookingResponse.from_orm(r) for r in rows]


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new booking (public)",
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def create_booking(
    payload: BookingCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_dep),
) -> BookingResponse:
    """
    Create a booking and fire email notifications in the background.

    Concurrency: DB insert + email dispatch run concurrently via
    BackgroundTasks (email) so the response is returned as soon as
    the DB write completes.

    Complexity: O(1) DB insert + O(1) slot invalidation.
    """
    idx = get_availability_index()

    # Check slot availability
    available = idx.get_slots(payload.date)
    if payload.time not in available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Time slot not available",
                "code": "SLOT_UNAVAILABLE",
                "details": {"date": payload.date, "time": payload.time},
                "request_id": str(uuid.uuid4()),
            },
        )

    # Create the booking record
    booking = BookingModel(
        id=str(uuid.uuid4()),
        name=payload.name,
        email=payload.email,
        company=payload.company,
        meeting_type=payload.meeting_type,
        details=payload.details,
        date=payload.date,
        time=payload.time,
        status="confirmed",
        cancelled=False,
    )
    db.add(booking)
    try:
        await db.flush()
        await db.refresh(booking)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Time slot not available",
                "code": "SLOT_UNAVAILABLE",
                "details": {"date": payload.date, "time": payload.time},
                "request_id": str(uuid.uuid4()),
            },
        )

    # O(1) slot invalidation
    await idx.mark_booked(payload.date, payload.time)

    # Prepare email data before committing (in case commit alters state)
    booking_data = {
        "id": booking.id,
        "name": booking.name,
        "email": booking.email,
        "company": booking.company,
        "meeting_type": booking.meeting_type,
        "details": booking.details,
        "date": booking.date,
        "time": booking.time,
    }

    # Fire-and-forget email (does not block response)
    background_tasks.add_task(dispatch_booking_emails, booking_data)

    logger.info("Booking created id=%s date=%s time=%s", booking.id, booking.date, booking.time)
    return BookingResponse.from_orm(booking)


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Get a single booking by ID",
    responses={404: {"model": ErrorResponse}},
)
async def get_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db_dep),
) -> BookingResponse:
    """Fetch a single booking by UUID."""
    result = await db.execute(
        select(BookingModel).where(BookingModel.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Booking not found",
                "code": "NOT_FOUND",
                "details": {"id": booking_id},
                "request_id": str(uuid.uuid4()),
            },
        )
    return BookingResponse.from_orm(booking)


@router.patch(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Update booking status (admin only)",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_booking(
    booking_id: str,
    payload: BookingUpdate,
    db: AsyncSession = Depends(get_db_dep),
    _admin: dict = Depends(require_admin),
) -> BookingResponse:
    """Update a booking's status or cancel it. Frees the slot on cancellation."""
    result = await db.execute(
        select(BookingModel).where(BookingModel.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Booking not found",
                "code": "NOT_FOUND",
                "details": {"id": booking_id},
                "request_id": str(uuid.uuid4()),
            },
        )

    was_cancelled = booking.cancelled

    if payload.status is not None:
        booking.status = payload.status
    if payload.cancelled is not None:
        booking.cancelled = payload.cancelled
    if payload.cancel_reason is not None:
        booking.cancel_reason = payload.cancel_reason

    await db.flush()
    await db.refresh(booking)

    # If newly cancelled, free the slot O(1)
    if booking.cancelled and not was_cancelled:
        idx = get_availability_index()
        await idx.free_slot(booking.date, booking.time)
        logger.info("Booking cancelled id=%s slot freed", booking_id)

    return BookingResponse.from_orm(booking)


@router.delete(
    "/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a booking (admin only)",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def delete_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db_dep),
    _admin: dict = Depends(require_admin),
) -> None:
    """Hard delete a booking. Frees the associated time slot."""
    result = await db.execute(
        select(BookingModel).where(BookingModel.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Booking not found",
                "code": "NOT_FOUND",
                "details": {"id": booking_id},
                "request_id": str(uuid.uuid4()),
            },
        )

    date_str, time_str = booking.date, booking.time
    await db.delete(booking)
    await db.flush()

    # Free the slot O(1)
    idx = get_availability_index()
    await idx.free_slot(date_str, time_str)
    logger.info("Booking deleted id=%s", booking_id)
