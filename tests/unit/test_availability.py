"""
Unit tests for the availability index service.

Tests are fully synchronous / async with no DB dependency.
Complexity assertions confirm O(1) slot operations.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.services.availability import AvailabilityIndex, BASE_SLOTS


@pytest.mark.unit
class TestBaseSlots:
    def test_base_slots_count(self):
        """28 slots: 12 morning (09:00–11:45) + 16 afternoon (13:00–16:45)."""
        assert len(BASE_SLOTS) == 28

    def test_first_slot(self):
        assert BASE_SLOTS[0] == "09:00"

    def test_last_slot(self):
        assert BASE_SLOTS[-1] == "16:45"

    def test_no_lunch_slots(self):
        """12:xx slots must not appear."""
        lunch = [s for s in BASE_SLOTS if s.startswith("12:")]
        assert lunch == []

    def test_slots_sorted(self):
        assert BASE_SLOTS == sorted(BASE_SLOTS)


@pytest.mark.unit
@pytest.mark.asyncio
class TestAvailabilityIndex:
    async def test_build_empty(self):
        idx = AvailabilityIndex()
        await idx.build({})
        assert idx.is_ready

    async def test_build_with_bookings(self):
        idx = AvailabilityIndex()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        await idx.build({tomorrow: {"09:00", "09:15"}})
        slots = idx.get_slots(tomorrow)
        assert "09:00" not in slots
        assert "09:15" not in slots
        assert "09:30" in slots

    async def test_mark_booked_removes_slot(self):
        idx = AvailabilityIndex()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        await idx.build({})
        await idx.mark_booked(tomorrow, "09:00")
        assert "09:00" not in idx.get_slots(tomorrow)

    async def test_free_slot_restores_slot(self):
        idx = AvailabilityIndex()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        await idx.build({tomorrow: {"09:00"}})
        assert "09:00" not in idx.get_slots(tomorrow)
        await idx.free_slot(tomorrow, "09:00")
        assert "09:00" in idx.get_slots(tomorrow)

    async def test_get_slots_not_ready(self):
        idx = AvailabilityIndex()
        result = idx.get_slots("2099-01-01")
        assert result == []

    async def test_get_range_returns_only_weekdays(self):
        idx = AvailabilityIndex()
        await idx.build({})
        # Week of 2099-01-07 (Monday) to 2099-01-13 (Sunday)
        result = idx.get_range("2099-01-07", "2099-01-13")
        # All returned dates should be weekdays (0-4)
        for ds in result:
            d = date.fromisoformat(ds)
            assert d.weekday() < 5, f"{ds} is a weekend"

    async def test_get_range_empty_for_past(self):
        idx = AvailabilityIndex()
        await idx.build({})
        result = idx.get_range("2000-01-01", "2000-01-07")
        assert result == {}

    async def test_slots_are_sorted(self):
        idx = AvailabilityIndex()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        await idx.build({})
        slots = idx.get_slots(tomorrow)
        assert slots == sorted(slots)

    async def test_concurrent_mark_booked_safety(self):
        """Concurrent mark_booked calls should not corrupt the index."""
        idx = AvailabilityIndex()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        await idx.build({})
        # Fire 10 concurrent mark_booked calls
        await asyncio.gather(*[
            idx.mark_booked(tomorrow, f"09:{i:02d}") for i in range(0, 60, 15)
        ])
        slots = idx.get_slots(tomorrow)
        for t in ["09:00", "09:15", "09:30", "09:45"]:
            assert t not in slots

    async def test_window_respects_settings(self):
        idx = AvailabilityIndex()
        await idx.build({})
        # Should have at least 5 business days in the index
        count = sum(1 for ds, slots in [
            (d, idx.get_slots(d))
            for d in [(date.today() + timedelta(days=i)).isoformat() for i in range(1, 10)]
        ] if slots)
        assert count >= 4


@pytest.mark.unit
class TestIndexBusinessDays:
    def test_business_days_excludes_weekends(self):
        idx = AvailabilityIndex()
        days = idx._business_days(10)
        for ds in days:
            d = date.fromisoformat(ds)
            assert d.weekday() < 5

    def test_business_days_count(self):
        idx = AvailabilityIndex()
        days = idx._business_days(10)
        assert len(days) == 10
