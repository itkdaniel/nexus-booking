"""
Availability index service.

The slot index is a date-bucketed dict built in O(n) at startup
and invalidated on each write. Queries are O(1) per date lookup.

Design:
  - All business days in the next `window_days` get a fixed slot list
  - Slots already booked for a date are removed from the bucket on write
  - Index rebuilds on startup from DB (O(n) where n = existing bookings)

Slot times: every 15 minutes from 09:00–11:45 and 13:00–16:45
(avoiding 12:00–12:45 lunch block)
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Set

from app.config import get_settings

# ── Base slot grid (generated once) ──────────────────────────────────────────

def _build_base_slots() -> List[str]:
    """All possible slot times: morning 09:00–11:45, afternoon 13:00–16:45."""
    slots: List[str] = []
    for hour in range(9, 12):         # 09:00 – 11:45
        for minute in (0, 15, 30, 45):
            slots.append(f"{hour:02d}:{minute:02d}")
    for hour in range(13, 17):        # 13:00 – 16:45
        for minute in (0, 15, 30, 45):
            slots.append(f"{hour:02d}:{minute:02d}")
    return slots


BASE_SLOTS: List[str] = _build_base_slots()   # 32 slots per day


# ── Availability index ────────────────────────────────────────────────────────

class AvailabilityIndex:
    """
    Thread-safe (asyncio-safe) in-memory availability index.

    Complexity:
      build():       O(n) where n = existing bookings
      get_slots():   O(1) dict lookup
      mark_booked(): O(1) set remove
      free():        O(1) set add
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # date_str -> set of available slot strings
        self._index: Dict[str, Set[str]] = {}
        self._built = False

    def _business_days(self, window_days: int) -> List[str]:
        """Return ISO date strings for all weekdays in the next window_days."""
        result: List[str] = []
        today = date.today()
        for i in range(1, window_days + 60):   # overshoot to fill window
            d = today + timedelta(days=i)
            if d.weekday() < 5:                # 0=Mon … 4=Fri
                result.append(d.isoformat())
            if len(result) >= window_days:
                break
        return result

    async def build(self, booked: Dict[str, Set[str]], window_days: int | None = None) -> None:
        """
        Populate the index from the full set of already-booked (date, time) pairs.

        :param booked: {date_str: {time_str, ...}} of existing bookings
        :param window_days: override setting (useful for tests — avoids cached Settings)
        """
        if window_days is None:
            window_days = get_settings().availability_window_days
        days = self._business_days(window_days)

        new_index: Dict[str, Set[str]] = {}
        for day in days:
            taken = booked.get(day, set())
            new_index[day] = set(BASE_SLOTS) - taken

        async with self._lock:
            self._index = new_index
            self._built = True

    async def mark_booked(self, date_str: str, time_str: str) -> None:
        """Remove a slot from availability (O(1))."""
        async with self._lock:
            if date_str in self._index:
                self._index[date_str].discard(time_str)

    async def free_slot(self, date_str: str, time_str: str) -> None:
        """Return a cancelled slot to availability (O(1))."""
        async with self._lock:
            if date_str in self._index:
                self._index[date_str].add(time_str)

    def get_slots(self, date_str: str) -> List[str]:
        """Return sorted available slots for a date. O(1) lookup."""
        if not self._built:
            return []
        return sorted(self._index.get(date_str, set()))

    def get_range(self, start: str, end: str) -> Dict[str, List[str]]:
        """
        Return available slots for all dates in [start, end].
        O(d) where d = number of days in range.
        """
        result: Dict[str, List[str]] = {}
        try:
            s = date.fromisoformat(start)
            e = date.fromisoformat(end)
        except ValueError:
            return result

        current = s
        while current <= e:
            ds = current.isoformat()
            slots = self.get_slots(ds)
            if slots:
                result[ds] = slots
            current += timedelta(days=1)
        return result

    @property
    def is_ready(self) -> bool:
        return self._built


# Module-level singleton index
_index: AvailabilityIndex | None = None


def get_availability_index() -> AvailabilityIndex:
    global _index
    if _index is None:
        _index = AvailabilityIndex()
    return _index
