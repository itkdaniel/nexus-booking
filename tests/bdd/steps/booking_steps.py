"""
pytest-bdd step definitions for nexus-booking BDD scenarios.

pytest-bdd does not support async step functions natively, so all HTTP calls
use starlette.testclient.TestClient (synchronous ASGI wrapper) instead of
httpx.AsyncClient.
"""
from __future__ import annotations

import asyncio
import pytest
from starlette.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from pytest_bdd import given, when, then, parsers

import app.services.availability as av_module
from app.auth import generate_token
from app.config import Settings
from app.database import Base, get_db_dep
from app.main import create_app
from app.services.availability import AvailabilityIndex

# ── Constants ──────────────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
TEST_SECRET = "bdd-test-secret"


def _get_settings() -> Settings:
    return Settings(
        database_url=TEST_DB_URL,
        jwt_secret=TEST_SECRET,
        email_enabled=False,
        debug=True,
        availability_window_days=50000,
    )


def _admin_headers() -> dict:
    token = generate_token({"sub": "admin", "role": "admin"}, secret=TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict:
    token = generate_token({"sub": "user1", "role": "user"}, secret=TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _base_payload(date: str = "2099-06-17", time: str = "09:00") -> dict:
    # 2099-06-17 = Wednesday
    return {
        "name": "BDD Tester",
        "email": "bdd@example.com",
        "meetingType": "discovery",
        "details": "BDD step definition test booking details here.",
        "date": date,
        "time": time,
    }


# ── State container ────────────────────────────────────────────────────────────

class ScenarioState:
    def __init__(self):
        self.client: TestClient | None = None
        self.response = None
        self.payload: dict = {}
        self.booking_id: str | None = None


@pytest.fixture
def state() -> ScenarioState:
    return ScenarioState()


@pytest.fixture
def bdd_client(state: ScenarioState):
    """
    Synchronous TestClient (ASGI) with isolated in-memory DB and availability index.
    Builds the engine/tables/index synchronously before yielding.
    """
    settings = _get_settings()

    # Reset any lingering index from a previous test
    av_module._index = None

    # Build engine + tables in a fresh event loop
    engine = create_async_engine(TEST_DB_URL, echo=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        idx = AvailabilityIndex()
        await idx.build({}, window_days=settings.availability_window_days)
        av_module._index = idx

    asyncio.run(_setup())

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Patch auth module to recognise the test secret
    import unittest.mock as mock
    import app.auth as auth_module
    auth_module.get_settings = mock.MagicMock(return_value=settings)

    app_instance = create_app(settings)
    app_instance.dependency_overrides[get_db_dep] = override_db

    # Disable the lifespan so TestClient doesn't try to connect to PostgreSQL.
    # Tables and index are already created above; the lifespan is not needed for tests.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app_instance.router.lifespan_context = noop_lifespan

    with TestClient(app_instance, raise_server_exceptions=False) as client:
        state.client = client
        yield client

    async def _teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_teardown())
    av_module._index = None

    # Restore auth
    if hasattr(auth_module, "_real_get_settings"):
        auth_module.get_settings = auth_module._real_get_settings


# ── Given steps ───────────────────────────────────────────────────────────────

@given("the booking service is running")
def service_running(state: ScenarioState, bdd_client):
    pass  # bdd_client fixture ensures the app is ready


@given("the availability index is initialised with no existing bookings")
def index_init(state: ScenarioState):
    pass  # bdd_client fixture builds a fresh index


@given(parsers.parse('a valid booking payload for date "{date}" at "{time}"'))
def valid_payload(state: ScenarioState, date: str, time: str):
    state.payload = _base_payload(date=date, time=time)


@given("that slot is already booked")
def mark_slot_taken(state: ScenarioState):
    r = state.client.post("/v1/bookings", json=state.payload)
    assert r.status_code == 201, f"Pre-booking failed ({r.status_code}): {r.text}"


@given(parsers.parse('a booking payload with email "{email}"'))
def payload_bad_email(state: ScenarioState, email: str):
    state.payload = {**_base_payload(), "email": email}


@given(parsers.parse('a booking payload missing the "{field}" field'))
def payload_missing_field(state: ScenarioState, field: str):
    p = _base_payload()
    p.pop(field, None)
    state.payload = p


@given(parsers.parse('a booking payload with details "{details}"'))
def payload_short_details(state: ScenarioState, details: str):
    state.payload = {**_base_payload(), "details": details}


@given(parsers.parse('an existing booking for date "{date}" at "{time}"'))
def existing_booking(state: ScenarioState, date: str, time: str):
    payload = _base_payload(date=date, time=time)
    resp = state.client.post("/v1/bookings", json=payload)
    assert resp.status_code == 201, f"Pre-booking failed ({resp.status_code}): {resp.text}"
    state.booking_id = resp.json()["id"]


@given(parsers.parse("{n:d} bookings exist in the system"))
def n_bookings_exist(state: ScenarioState, n: int):
    # All known Mon–Fri weekdays in 2099
    dates = [
        "2099-09-15",  # Tuesday
        "2099-09-16",  # Wednesday
        "2099-09-17",  # Thursday
        "2099-09-18",  # Friday
        "2099-09-22",  # Monday
    ]
    times = ["09:00", "09:15", "09:30", "09:45", "10:00"]
    for i in range(n):
        p = _base_payload(date=dates[i % len(dates)], time=times[i % len(times)])
        p["email"] = f"admin{i}@example.com"
        r = state.client.post("/v1/bookings", json=p)
        assert r.status_code == 201, f"Booking {i} failed ({r.status_code}): {r.text}"


# ── When steps ────────────────────────────────────────────────────────────────

@when(parsers.parse('I POST the booking to "{path}"'))
def post_booking(state: ScenarioState, path: str):
    state.response = state.client.post(path, json=state.payload)


@when("an admin PATCHes the booking with cancelled=true")
def admin_patch_cancel(state: ScenarioState):
    state.response = state.client.patch(
        f"/v1/bookings/{state.booking_id}",
        json={"cancelled": True, "cancelReason": "Test cancellation"},
        headers=_admin_headers(),
    )


@when("a regular user PATCHes the booking with cancelled=true")
def user_patch_cancel(state: ScenarioState):
    state.response = state.client.patch(
        f"/v1/bookings/{state.booking_id}",
        json={"cancelled": True},
        headers=_user_headers(),
    )


@when(parsers.parse('an admin PATCHes booking id "{booking_id}" with cancelled=true'))
def admin_patch_nonexistent(state: ScenarioState, booking_id: str):
    state.response = state.client.patch(
        f"/v1/bookings/{booking_id}",
        json={"cancelled": True},
        headers=_admin_headers(),
    )


@when("an admin DELETEs the booking")
def admin_delete(state: ScenarioState):
    state.response = state.client.delete(
        f"/v1/bookings/{state.booking_id}",
        headers=_admin_headers(),
    )


@when(parsers.parse('an admin GETs "{path}"'))
def admin_get(state: ScenarioState, path: str):
    state.response = state.client.get(path, headers=_admin_headers())


@when(parsers.parse('a regular user GETs "{path}"'))
def user_get(state: ScenarioState, path: str):
    state.response = state.client.get(path, headers=_user_headers())


@when(parsers.parse('an unauthenticated user GETs "{path}"'))
def anon_get(state: ScenarioState, path: str):
    state.response = state.client.get(path)


@when("an admin GETs the booking by id")
def admin_get_by_id(state: ScenarioState):
    state.response = state.client.get(
        f"/v1/bookings/{state.booking_id}",
        headers=_admin_headers(),
    )


@when(parsers.parse('anyone GETs booking id "{booking_id}"'))
def get_nonexistent(state: ScenarioState, booking_id: str):
    state.response = state.client.get(f"/v1/bookings/{booking_id}")


# ── Then steps ────────────────────────────────────────────────────────────────

@then(parsers.parse("the response status is {code:d}"))
def check_status(state: ScenarioState, code: int):
    assert state.response is not None, "No response — 'when' step did not fire"
    assert state.response.status_code == code, (
        f"Expected {code}, got {state.response.status_code}: {state.response.text}"
    )


@then("the response contains a booking id")
def check_booking_id(state: ScenarioState):
    data = state.response.json()
    assert "id" in data and data["id"]


@then(parsers.parse('the booking has status "{status}"'))
def check_booking_status(state: ScenarioState, status: str):
    assert state.response.json()["status"] == status


@then("the booking has cancelled=true")
def check_cancelled(state: ScenarioState):
    assert state.response.json()["cancelled"] is True


@then(parsers.parse('the error code is "{code}"'))
def check_error_code(state: ScenarioState, code: str):
    body = state.response.json()
    actual = body.get("code") or body.get("detail", {}).get("code")
    assert actual == code, f"Expected code={code!r}, got body={body}"


@then(parsers.parse('the slot "{time}" on "{date}" is no longer available'))
def slot_no_longer_available(state: ScenarioState, time: str, date: str):
    resp = state.client.get(f"/v1/availability?start={date}&end={date}")
    slots = resp.json().get(date, [])
    assert time not in slots, f"Expected {time} to be taken, but slots={slots}"


@then(parsers.parse('the slot "{time}" on "{date}" is available again'))
def slot_available_again(state: ScenarioState, time: str, date: str):
    idx = av_module.get_availability_index()
    slots = idx.get_slots(date)
    assert time in slots, f"Expected {time} to be free, but slots={slots}"


@then(parsers.parse("the response contains {n:d} bookings"))
def check_n_bookings(state: ScenarioState, n: int):
    data = state.response.json()
    assert len(data) == n, f"Expected {n} bookings, got {len(data)}: {data}"


@then(parsers.parse('the booking date is "{date}"'))
def check_date(state: ScenarioState, date: str):
    assert state.response.json()["date"] == date


@then(parsers.parse('the booking time is "{time}"'))
def check_time(state: ScenarioState, time: str):
    assert state.response.json()["time"] == time
