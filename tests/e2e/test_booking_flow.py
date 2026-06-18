"""
End-to-end tests for the full booking lifecycle.

Uses httpx.AsyncClient against the live test app (SQLite in-memory).
Tests complete user journeys from creation to cancellation.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.e2e
@pytest.mark.asyncio
class TestFullBookingLifecycle:
    async def test_create_retrieve_cancel_delete(
        self, client, admin_headers, booking_payload
    ):
        """Complete lifecycle: create → get → cancel → delete."""

        # 1. Create
        r = await client.post("/v1/bookings", json=booking_payload)
        assert r.status_code == 201
        booking_id = r.json()["id"]
        assert r.json()["cancelled"] is False

        # 2. Retrieve
        r = await client.get(f"/v1/bookings/{booking_id}")
        assert r.status_code == 200
        assert r.json()["id"] == booking_id

        # 3. Cancel (admin)
        r = await client.patch(
            f"/v1/bookings/{booking_id}",
            json={"cancelled": True, "cancelReason": "E2E test cancellation"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["cancelled"] is True

        # 4. Slot is freed after cancellation
        date_str = booking_payload["date"]
        time_str = booking_payload["time"]
        r = await client.get(f"/v1/availability?start={date_str}&end={date_str}")
        slots = r.json().get(date_str, [])
        assert time_str in slots

        # 5. Delete (admin)
        r = await client.delete(f"/v1/bookings/{booking_id}", headers=admin_headers)
        assert r.status_code == 204

        # 6. Verify deleted
        r = await client.get(f"/v1/bookings/{booking_id}")
        assert r.status_code == 404

    async def test_double_booking_rejected(self, client, booking_payload):
        """Same slot cannot be booked twice."""
        r1 = await client.post("/v1/bookings", json=booking_payload)
        assert r1.status_code == 201

        r2 = await client.post("/v1/bookings", json=booking_payload)
        assert r2.status_code == 409
        assert r2.json()["detail"]["code"] == "SLOT_UNAVAILABLE"

    async def test_concurrent_bookings_different_slots(self, client):
        """Multiple different slots can be booked concurrently."""
        times = ["09:00", "09:15", "09:30"]
        payloads = [
            {
                "name": f"User {i}",
                "email": f"user{i}@example.com",
                "meetingType": "discovery",
                "details": "Concurrent booking test details for testing.",
                "date": "2099-11-03",  # Tuesday
                "time": t,
            }
            for i, t in enumerate(times)
        ]
        responses = await asyncio.gather(
            *[client.post("/v1/bookings", json=p) for p in payloads]
        )
        codes = [r.status_code for r in responses]
        assert all(c == 201 for c in codes), f"Expected all 201, got {codes}"


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAvailabilityE2E:
    async def test_availability_range_returns_weekdays_only(self, client):
        """Range query only returns weekdays with slots."""
        r = await client.get("/v1/availability?start=2099-01-06&end=2099-01-12")
        assert r.status_code == 200
        data = r.json()
        from datetime import date
        for ds in data:
            d = date.fromisoformat(ds)
            assert d.weekday() < 5, f"{ds} is a weekend!"

    async def test_availability_decreases_after_booking(self, client):
        """Booking a slot removes it from availability."""
        date_str = "2099-12-01"
        time_str = "09:00"

        # Before booking
        r = await client.get(f"/v1/availability?start={date_str}&end={date_str}")
        before = r.json().get(date_str, [])
        assert time_str in before

        # Book
        payload = {
            "name": "E2E Availability",
            "email": "avail@example.com",
            "meetingType": "devops",
            "details": "Testing availability reduction after booking.",
            "date": date_str,
            "time": time_str,
        }
        r = await client.post("/v1/bookings", json=payload)
        assert r.status_code == 201

        # After booking
        r = await client.get(f"/v1/availability?start={date_str}&end={date_str}")
        after = r.json().get(date_str, [])
        assert time_str not in after


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAdminFlowsE2E:
    async def test_admin_list_grows_with_bookings(self, client, admin_headers):
        """Admin list count reflects bookings created."""
        r = await client.get("/v1/bookings", headers=admin_headers)
        initial = len(r.json())

        # Use 3 known weekdays: Mon/Tue/Wed
        weekdays = ["2099-10-05", "2099-10-06", "2099-10-07"]
        payloads = [
            {
                "name": "Admin Flow",
                "email": f"flow{i}@example.com",
                "meetingType": "architecture",
                "details": "Testing admin list growth with multiple bookings.",
                "date": weekdays[i],
                "time": "10:00",
            }
            for i in range(3)
        ]
        for p in payloads:
            r = await client.post("/v1/bookings", json=p)
            assert r.status_code == 201

        r = await client.get("/v1/bookings", headers=admin_headers)
        assert len(r.json()) == initial + 3

    async def test_update_status_without_cancelling(self, client, admin_headers):
        """Admin can update status field without cancelling."""
        payload = {
            "name": "Status Update",
            "email": "status@example.com",
            "meetingType": "ai",
            "details": "Testing status update functionality for the booking.",
            "date": "2099-10-20",
            "time": "14:00",
        }
        r = await client.post("/v1/bookings", json=payload)
        booking_id = r.json()["id"]

        r = await client.patch(
            f"/v1/bookings/{booking_id}",
            json={"status": "completed"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
        assert r.json()["cancelled"] is False
