"""
Async email service using aiosmtplib.

Falls back to structured console logging when SMTP is disabled
or not configured — so the app never blocks on email in dev/test.

Parallelism: email is always dispatched as a fire-and-forget
asyncio task so it never blocks the booking creation response.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings

logger = logging.getLogger("nexus-booking.email")


@dataclass
class EmailPayload:
    to: str
    subject: str
    html: str
    text: Optional[str] = None


@dataclass
class SendResult:
    success: bool
    mode: str           # "smtp" | "log" | "disabled"
    message_id: Optional[str] = None
    error: Optional[str] = None


async def send_email(payload: EmailPayload) -> SendResult:
    """
    Send an email via aiosmtplib or log to console.
    Never raises — returns SendResult with success=False on error.
    """
    s = get_settings()

    if not s.email_enabled or not s.smtp_host:
        logger.info(
            "EMAIL (console-only) to=%s subject=%s", payload.to, payload.subject
        )
        return SendResult(success=True, mode="log")

    try:
        import aiosmtplib  # optional dep
        smtp = aiosmtplib.SMTP(
            hostname=s.smtp_host,
            port=s.smtp_port,
            use_tls=s.smtp_secure,
        )
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{s.from_name} <{s.from_email}>"
        msg["To"] = payload.to
        msg["Subject"] = payload.subject
        if payload.text:
            msg.attach(MIMEText(payload.text, "plain"))
        msg.attach(MIMEText(payload.html, "html"))

        async with smtp:
            await smtp.login(s.smtp_user, s.smtp_password)
            result = await smtp.send_message(msg)
            message_id = str(result)
            logger.info("Email sent to %s (id=%s)", payload.to, message_id)
            return SendResult(success=True, mode="smtp", message_id=message_id)
    except ImportError:
        logger.warning("aiosmtplib not installed — falling back to console log")
        logger.info("EMAIL to=%s subject=%s", payload.to, payload.subject)
        return SendResult(success=True, mode="log")
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return SendResult(success=False, mode="smtp", error=str(exc))


def _booking_html(booking_data: dict, is_admin: bool = False) -> tuple[str, str]:
    """Generate HTML + plain-text email body for a booking."""
    name = booking_data.get("name", "")
    email = booking_data.get("email", "")
    date = booking_data.get("date", "")
    time = booking_data.get("time", "")
    meeting_type = booking_data.get("meeting_type", "")
    details = booking_data.get("details", "")
    company = booking_data.get("company", "")
    booking_id = booking_data.get("id", "")

    rows = [
        ("📅", "Date", date),
        ("🕐", "Time", time),
        ("📋", "Session Type", meeting_type),
        ("📝", "Details", details),
    ]
    if company:
        rows.append(("🏢", "Company", company))
    if is_admin:
        rows.insert(0, ("👤", "Name", name))
        rows.insert(1, ("📧", "Email", email))
        rows.append(("🆔", "Booking ID", booking_id))

    rows_html = "".join(
        f"""<tr><td style="padding:4px 0 4px 0;vertical-align:top;font-size:16px;width:28px">{icon}</td>
        <td style="padding:4px 0"><span style="font-size:11px;color:#71717a;text-transform:uppercase;letter-spacing:.05em;display:block">{label}</span>
        <span style="font-size:14px;color:#d4d4d8">{value}</span></td></tr>"""
        for icon, label, value in rows
    )

    if is_admin:
        title = "🔔 New Booking Request"
        subtitle = "A new consultation has been scheduled"
        greeting = ""
    else:
        title = "✓ Booking Confirmed"
        subtitle = "Your consultation session has been scheduled"
        greeting = f"<p style='margin:0 0 8px;font-size:16px;color:#d4d4d8'>Hi <strong style='color:#f4f4f5'>{name}</strong>,</p><p style='margin:0;color:#a1a1aa;line-height:1.6'>Thank you for scheduling. Here are your session details:</p>"

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#09090b;font-family:Inter,Arial,sans-serif;color:#e4e4e7">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#09090b">
<tr><td align="center" style="padding:40px 20px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#18181b;border-radius:12px;border:1px solid rgba(255,255,255,.08)">
<tr><td style="background:linear-gradient(135deg,#1e3a5f,#1a1a2e);padding:36px 40px 28px;text-align:center">
<h1 style="margin:0;font-size:22px;font-weight:700;color:#f4f4f5">{title}</h1>
<p style="margin:8px 0 0;color:#a1a1aa;font-size:14px">{subtitle}</p>
</td></tr>
{f'<tr><td style="padding:28px 40px 0">{greeting}</td></tr>' if greeting else ''}
<tr><td style="padding:24px 40px">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#27272a;border-radius:8px;border:1px solid rgba(255,255,255,.06)">
<tr><td style="padding:20px 24px"><table width="100%" cellpadding="0" cellspacing="0">{rows_html}</table></td></tr>
</table></td></tr>
<tr><td style="background:#09090b;padding:20px 40px;border-top:1px solid rgba(255,255,255,.05)">
<p style="margin:0;color:#52525b;font-size:11px;text-align:center">NexusConsult Booking Service</p>
</td></tr>
</table></td></tr></table></body></html>"""

    if is_admin:
        plain = (
            f"New Booking\n\nName: {name}\nEmail: {email}\n"
            f"Date: {date}\nTime: {time}\nType: {meeting_type}\nDetails: {details}"
            + (f"\nCompany: {company}" if company else "")
            + f"\nID: {booking_id}"
        )
    else:
        plain = (
            f"Hi {name},\nBooking Confirmed\n\n"
            f"Date: {date}\nTime: {time}\nType: {meeting_type}\nDetails: {details}"
            + (f"\nCompany: {company}" if company else "")
        )
    return html, plain


async def dispatch_booking_emails(booking_data: dict) -> None:
    """
    Fire-and-forget: send user confirmation + admin notification in parallel.
    Uses asyncio.gather() for concurrent dispatch — O(1) blocking time.
    """
    s = get_settings()

    html_user, text_user = _booking_html(booking_data, is_admin=False)
    html_admin, text_admin = _booking_html(booking_data, is_admin=True)

    tasks = []
    tasks.append(send_email(EmailPayload(
        to=booking_data["email"],
        subject=f"✓ Booking Confirmed — {booking_data['date']} at {booking_data['time']}",
        html=html_user,
        text=text_user,
    )))
    tasks.append(send_email(EmailPayload(
        to=s.admin_email,
        subject=f"[nexus-booking] New Booking: {booking_data['name']} on {booking_data['date']}",
        html=html_admin,
        text=text_admin,
    )))

    # Run both concurrently
    await asyncio.gather(*tasks, return_exceptions=True)
