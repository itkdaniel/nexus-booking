"""
Availability endpoint.

GET /v1/availability?start=YYYY-MM-DD&end=YYYY-MM-DD

Returns available time slots for a date range.
The slot index is an in-memory bucketed dict (built O(n) at startup),
so each query is O(d) where d = number of days in the requested range.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from app.models import ErrorResponse
from app.services.availability import BASE_SLOTS, get_availability_index

router = APIRouter(prefix="/v1/availability", tags=["availability"])


@router.get(
    "",
    response_model=Dict[str, List[str]],
    summary="Get available slots for a date range",
    responses={400: {"model": ErrorResponse}},
)
async def get_availability(
    start: str = Query(..., description="Start date YYYY-MM-DD", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., description="End date YYYY-MM-DD", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> Dict[str, List[str]]:
    """
    Return a dict mapping date → [available_times] for the given range.

    Complexity: O(d) where d = days in range.
    Only dates within the pre-built availability window are returned
    (future dates beyond the window return empty).

    Example response:
        {
          "2025-04-15": ["09:00", "09:15", "10:00", ...],
          "2025-04-16": ["13:00", "14:00", ...]
        }
    """
    try:
        s_date = date.fromisoformat(start)
        e_date = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Invalid date format — use YYYY-MM-DD",
                "code": "INVALID_DATE",
                "details": {"start": start, "end": end},
            },
        )

    if s_date > e_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "start must be before end",
                "code": "INVALID_RANGE",
                "details": {},
            },
        )

    max_range = timedelta(days=60)
    if (e_date - s_date) > max_range:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Date range cannot exceed 60 days",
                "code": "RANGE_TOO_LARGE",
                "details": {},
            },
        )

    idx = get_availability_index()
    return idx.get_range(start, end)
