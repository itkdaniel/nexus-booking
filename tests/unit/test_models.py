"""
Unit tests for Pydantic request/response model validation.
No DB required — pure model logic.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import BookingCreate, BookingUpdate, ErrorResponse


@pytest.mark.unit
class TestBookingCreate:
    def test_valid_payload(self, booking_payload):
        model = BookingCreate(**booking_payload)
        assert model.name == "Jane Doe"
        assert model.email == "jane@example.com"
        assert model.meeting_type == "discovery"

    def test_name_too_short(self, booking_payload):
        booking_payload["name"] = "J"
        with pytest.raises(ValidationError) as exc:
            BookingCreate(**booking_payload)
        assert "name" in str(exc.value).lower()

    def test_invalid_email(self, booking_payload):
        booking_payload["email"] = "not-an-email"
        with pytest.raises(ValidationError):
            BookingCreate(**booking_payload)

    def test_invalid_meeting_type(self, booking_payload):
        booking_payload["meetingType"] = "coffee-chat"
        with pytest.raises(ValidationError) as exc:
            BookingCreate(**booking_payload)
        assert "meeting_type" in str(exc.value).lower()

    def test_details_too_short(self, booking_payload):
        booking_payload["details"] = "short"
        with pytest.raises(ValidationError):
            BookingCreate(**booking_payload)

    def test_invalid_date_format(self, booking_payload):
        booking_payload["date"] = "06/15/2099"
        with pytest.raises(ValidationError):
            BookingCreate(**booking_payload)

    def test_invalid_time_format(self, booking_payload):
        booking_payload["time"] = "9am"
        with pytest.raises(ValidationError):
            BookingCreate(**booking_payload)

    def test_company_is_optional(self, booking_payload):
        booking_payload.pop("company", None)
        model = BookingCreate(**booking_payload)
        assert model.company is None

    def test_all_valid_meeting_types(self, booking_payload):
        for mt in ["discovery", "architecture", "microservices", "automation", "devops", "ai"]:
            booking_payload["meetingType"] = mt
            model = BookingCreate(**booking_payload)
            assert model.meeting_type == mt

    def test_alias_populate_by_name(self, booking_payload):
        """meetingType alias maps to meeting_type field."""
        model = BookingCreate(**booking_payload)
        assert model.meeting_type == booking_payload["meetingType"]


@pytest.mark.unit
class TestBookingUpdate:
    def test_all_optional(self):
        model = BookingUpdate()
        assert model.status is None
        assert model.cancelled is None
        assert model.cancel_reason is None

    def test_can_set_cancelled(self):
        model = BookingUpdate(cancelled=True, cancelReason="Scheduling conflict")
        assert model.cancelled is True
        assert model.cancel_reason == "Scheduling conflict"

    def test_cancel_reason_length_limit(self):
        with pytest.raises(ValidationError):
            BookingUpdate(cancelReason="x" * 501)


@pytest.mark.unit
class TestErrorResponse:
    def test_has_request_id(self):
        err = ErrorResponse(error="Not found", code="NOT_FOUND")
        assert err.request_id
        assert len(err.request_id) == 36  # UUID format

    def test_request_ids_are_unique(self):
        a = ErrorResponse(error="e", code="C")
        b = ErrorResponse(error="e", code="C")
        assert a.request_id != b.request_id

    def test_details_defaults_to_empty_dict(self):
        err = ErrorResponse(error="e", code="C")
        assert err.details == {}
