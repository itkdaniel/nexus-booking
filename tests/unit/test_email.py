"""
Unit tests for the email service.
All tests mock SMTP — no real email sent.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email import (
    EmailPayload, SendResult, _booking_html, dispatch_booking_emails, send_email,
    configure_email,
)
from app.config import Settings


SAMPLE_BOOKING = {
    "id": "abc-123",
    "name": "Alice Smith",
    "email": "alice@example.com",
    "company": "TechCorp",
    "meeting_type": "architecture",
    "details": "Need help with microservices decomposition.",
    "date": "2099-06-15",
    "time": "10:00",
}

_DISABLED_SETTINGS = Settings(
    database_url="sqlite+aiosqlite:///:memory:",
    email_enabled=False,
    smtp_host="",
)

_ENABLED_SETTINGS = Settings(
    database_url="sqlite+aiosqlite:///:memory:",
    email_enabled=True,
    smtp_host="smtp.example.com",
    smtp_port=587,
    smtp_secure=False,
    smtp_user="u",
    smtp_password="p",
    admin_email="admin@nexus.dev",
)


@pytest.mark.unit
class TestBookingHtml:
    def test_user_html_contains_name(self):
        html, text = _booking_html(SAMPLE_BOOKING, is_admin=False)
        assert "Alice Smith" in html
        assert "Alice Smith" in text

    def test_admin_html_contains_booking_id(self):
        html, text = _booking_html(SAMPLE_BOOKING, is_admin=True)
        assert "abc-123" in html
        assert "abc-123" in text

    def test_user_html_not_contains_admin_id(self):
        html, text = _booking_html(SAMPLE_BOOKING, is_admin=False)
        assert "abc-123" not in html
        assert "abc-123" not in text

    def test_html_contains_date_and_time(self):
        html, _ = _booking_html(SAMPLE_BOOKING, is_admin=False)
        assert "2099-06-15" in html
        assert "10:00" in html

    def test_plain_text_fallback(self):
        _, text = _booking_html(SAMPLE_BOOKING, is_admin=False)
        assert "Booking Confirmed" in text

    def test_admin_plain_includes_email(self):
        _, text = _booking_html(SAMPLE_BOOKING, is_admin=True)
        assert "alice@example.com" in text

    def test_user_plain_includes_name(self):
        _, text = _booking_html(SAMPLE_BOOKING, is_admin=False)
        assert "Alice Smith" in text


@pytest.mark.unit
@pytest.mark.asyncio
class TestSendEmail:
    async def test_disabled_email_logs_only(self):
        configure_email(_DISABLED_SETTINGS)
        payload = EmailPayload(to="a@b.com", subject="Test", html="<p>Hi</p>")
        result = await send_email(payload)
        assert result.mode == "log"
        assert result.success is True

    async def test_aiosmtplib_not_installed_falls_back(self):
        configure_email(_ENABLED_SETTINGS)
        payload = EmailPayload(to="a@b.com", subject="T", html="<p>H</p>")
        with patch.dict("sys.modules", {"aiosmtplib": None}):
            result = await send_email(payload)
        assert result.mode == "log"

    async def test_dispatch_runs_both_emails(self):
        """dispatch_booking_emails sends user + admin emails concurrently."""
        configure_email(_ENABLED_SETTINGS)
        sent_to = []

        async def mock_send(payload: EmailPayload) -> SendResult:
            sent_to.append(payload.to)
            return SendResult(success=True, mode="log")

        with patch("app.services.email.send_email", side_effect=mock_send):
            await dispatch_booking_emails(SAMPLE_BOOKING)

        assert "alice@example.com" in sent_to
        assert "admin@nexus.dev" in sent_to
        assert len(sent_to) == 2
