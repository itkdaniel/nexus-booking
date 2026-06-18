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

    Parallelism: asyncio.gather() is used to concurrently:
      1) Flush the booking to the DB
      2) Prepare the email payload (CPU-bound, runs concurrently with flush)
    Email dispatch is then handed off as a background task so the HTTP response
    is returned as soon as the DB write succeeds.

    Complexity: O(1) slot check + O(1) DB insert + O(1) slot invalidation.
    """
    idx = get_availability_index()

    # Check slot availability (O(1) index lookup)
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

    # Build email payload coroutine (pure function, treated as coroutine for gather)
    async def _prepare_email_data():
        return {
            "id": booking.id,
            "name": booking.name,
            "email": booking.email,
            "company": booking.company,
            "meeting_type": booking.meeting_type,
            "details": booking.details,
            "date": booking.date,
            "time": booking.time,
        }

    # Concurrently flush to DB and prepare email payload
    _, booking_data = await asyncio.gather(
        db.flush(),
        _prepare_email_data(),
    )
    await db.refresh(booking)

    # O(1) slot invalidation in the in-memory index
    await idx.mark_booked(payload.date, payload.time)

    # Fire-and-forget email (non-blocking — response returns immediately)
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
    """Update a booking's status or cancel it.

    Index invariants:
    - False → True (cancel):    free the slot so it can be rebooked.
    - True  → False (uncancel): re-mark the slot as booked.
    - No change:                leave the index untouched.
    """
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

    idx = get_availability_index()
    now_cancelled = booking.cancelled

    if now_cancelled and not was_cancelled:
        # Newly cancelled → free the slot so it can be rebooked
        await idx.free_slot(booking.date, booking.time)
        logger.info("Booking cancelled id=%s slot freed", booking_id)
    elif not now_cancelled and was_cancelled:
        # Uncancelled → re-mark the slot as booked to prevent double-booking
        await idx.mark_booked(booking.date, booking.time)
        logger.info("Booking uncancelled id=%s slot re-reserved", booking_id)

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
    """Hard delete a booking.

    Index invariant: only frees the slot if the booking was active (not cancelled).
    Deleting an already-cancelled booking must NOT touch the index — the slot may
    already be occupied by a new rebooked active booking.
    """
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

    date_str, time_str, was_cancelled = booking.date, booking.time, booking.cancelled
    await db.delete(booking)
    await db.flush()

    # Only free the slot if the booking was active. If it was already cancelled,
    # the slot may have been rebooked — leave the index untouched.
    if not was_cancelled:
        idx = get_availability_index()
        await idx.free_slot(date_str, time_str)
        logger.info("Active booking deleted id=%s slot freed", booking_id)
    else:
        logger.info("Cancelled booking deleted id=%s (slot already free)", booking_id)
