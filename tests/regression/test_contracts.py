"""
Regression / API contract tests.

These tests assert that the API response *shape* never changes
without an intentional version bump. They act as a breaking-change
detector for the portfolio gateway integration.
"""
from __future__ import annotations

import pytest


@pytest.mark.regression
@pytest.mark.asyncio
class TestHealthContract:
    async def test_health_has_required_fields(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "service" in body
        assert "version" in body
        assert "uptime_seconds" in body

    async def test_health_status_is_ok(self, client):
        resp = await client.get("/health")
        assert resp.json()["status"] == "ok"

    async def test_health_service_name(self, client):
        resp = await client.get("/health")
        assert resp.json()["service"] == "nexus-booking"


@pytest.mark.regression
@pytest.mark.asyncio
class TestInfoContract:
    async def test_info_has_required_fields(self, client):
        resp = await client.get("/info")
        assert resp.status_code == 200
        body = resp.json()
        required = {"name", "version", "port", "endpoints", "description"}
        assert required.issubset(body.keys())

    async def test_info_endpoints_is_list(self, client):
        resp = await client.get("/info")
        assert isinstance(resp.json()["endpoints"], list)

    async def test_info_endpoints_have_method_and_path(self, client):
        resp = await client.get("/info")
        for ep in resp.json()["endpoints"]:
            assert "method" in ep
            assert "path" in ep
            assert "auth" in ep


@pytest.mark.regression
@pytest.mark.asyncio
class TestOpenApiContract:
    async def test_openapi_json_accessible(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "openapi" in body
        assert "info" in body
        assert "paths" in body

    async def test_booking_paths_present(self, client):
        resp = await client.get("/openapi.json")
        paths = resp.json()["paths"]
        assert "/v1/bookings" in paths
        assert "/v1/availability" in paths


@pytest.mark.regression
@pytest.mark.asyncio
class TestBookingResponseContract:
    async def test_booking_response_shape(self, client, booking_payload):
        resp = await client.post("/v1/bookings", json=booking_payload)
        assert resp.status_code == 201
        body = resp.json()
        required_fields = {
            "id", "name", "email", "meetingType", "details",
            "date", "time", "status", "cancelled", "createdAt", "updatedAt"
        }
        assert required_fields.issubset(body.keys())

    async def test_booking_id_is_uuid(self, client, booking_payload):
        import re
        resp = await client.post("/v1/bookings", json=booking_payload)
        assert resp.status_code == 201
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert uuid_pattern.match(resp.json()["id"])

    async def test_booking_default_status(self, client, booking_payload):
        resp = await client.post("/v1/bookings", json=booking_payload)
        assert resp.json()["status"] == "confirmed"

    async def test_booking_default_cancelled(self, client, booking_payload):
        resp = await client.post("/v1/bookings", json=booking_payload)
        assert resp.json()["cancelled"] is False


@pytest.mark.regression
@pytest.mark.asyncio
class TestErrorEnvelopeContract:
    async def test_404_uses_standard_envelope(self, client, admin_headers):
        resp = await client.get("/v1/bookings/non-existent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        detail = body["detail"]
        assert "error" in detail
        assert "code" in detail

    async def test_401_on_missing_auth(self, client):
        resp = await client.get("/v1/bookings")
        assert resp.status_code == 401

    async def test_405_for_wrong_method(self, client):
        resp = await client.delete("/v1/bookings")
        assert resp.status_code == 405


@pytest.mark.regression
@pytest.mark.asyncio
class TestAvailabilityContract:
    async def test_availability_returns_dict(self, client):
        resp = await client.get("/v1/availability?start=2099-01-06&end=2099-01-10")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    async def test_availability_values_are_lists(self, client):
        resp = await client.get("/v1/availability?start=2099-01-06&end=2099-01-10")
        for slots in resp.json().values():
            assert isinstance(slots, list)

    async def test_availability_bad_range_returns_400(self, client):
        resp = await client.get("/v1/availability?start=2099-01-10&end=2099-01-06")
        assert resp.status_code == 400
