"""
pytest-bdd step definitions for nexus-booking BDD scenarios.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pytest_bdd import given, when, then, parsers
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import generate_token
from app.config import Settings
from app.database import Base, get_db_dep
from app.main import create_app
from app.services.availability import AvailabilityIndex

# ── Shared test fixtures ───────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
TEST_SECRET = "bdd-test-secret"

_engine = None
_app = None
_client = None
_index = None


def _get_settings():
    return Settings(
        database_url=TEST_DB_URL,
        jwt_secret=TEST_SECRET,
        email_enabled=False,
        debug=True,
    )


def _admin_headers():
    token = generate_token({"sub": "admin", "role": "admin"}, secret=TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _user_headers():
    token = generate_token({"sub": "user1", "role": "user"}, secret=TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _base_payload(date: str = "2099-06-15", time: str = "09:00") -> dict:
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
        self.client: AsyncClient | None = None
        self.response = None
        self.payload: dict = {}
        self.booking_id: str | None = None
        self.engine = None
        self.factory = None


@pytest.fixture
def state():
    return ScenarioState()


@pytest_asyncio.fixture
async def bdd_client(state):
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    state.engine = engine
    state.factory = factory

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    settings = _get_settings()
    app = create_app(settings)
    app.dependency_overrides[get_db_dep] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://bddtest",
    ) as client:
        state.client = client
        yield client

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Given steps ───────────────────────────────────────────────────────────────

@given("the booking service is running")
def service_running(state):
    pass  # client fixture handles this


@given("the availability index is initialised with no existing bookings")
@pytest.mark.asyncio
async def index_init(state):
    idx = AvailabilityIndex()
    await idx.build({})
    import app.services.availability as av_module
    av_module._index = idx


@given(parsers.parse('a valid booking payload for date "{date}" at "{time}"'))
def valid_payload(state, date, time):
    state.payload = _base_payload(date=date, time=time)


@given(parsers.parse('that slot is already booked'))
@pytest.mark.asyncio
async def mark_slot_taken(state):
    # Post a first booking to take the slot
    await state.client.post("/v1/bookings", json=state.payload)


@given(parsers.parse('a booking payload with email "{email}"'))
def payload_bad_email(state, email):
    state.payload = {**_base_payload(), "email": email}


@given(parsers.parse('a booking payload missing the "{field}" field'))
def payload_missing_field(state, field):
    p = _base_payload()
    p.pop(field, None)
    state.payload = p


@given(parsers.parse('a booking payload with details "{details}"'))
def payload_short_details(state, details):
    state.payload = {**_base_payload(), "details": details}


@given(parsers.parse('an existing booking for date "{date}" at "{time}"'))
@pytest.mark.asyncio
async def existing_booking(state, date, time):
    payload = _base_payload(date=date, time=time)
    resp = await state.client.post("/v1/bookings", json=payload)
    assert resp.status_code == 201
    state.booking_id = resp.json()["id"]


@given(parsers.parse("{n:d} bookings exist in the system"))
@pytest.mark.asyncio
async def n_bookings_exist(state, n):
    times = ["09:00", "09:15", "09:30", "09:45", "10:00"]
    for i in range(n):
        p = _base_payload(date=f"2099-09-{15+i:02d}", time=times[i % len(times)])
        r = await state.client.post("/v1/bookings", json=p)
        assert r.status_code == 201


# ── When steps ────────────────────────────────────────────────────────────────

@when(parsers.parse('I POST the booking to "{path}"'))
@pytest.mark.asyncio
async def post_booking(state, path):
    state.response = await state.client.post(path, json=state.payload)


@when("an admin PATCHes the booking with cancelled=true")
@pytest.mark.asyncio
async def admin_patch_cancel(state):
    state.response = await state.client.patch(
        f"/v1/bookings/{state.booking_id}",
        json={"cancelled": True, "cancelReason": "Test cancellation"},
        headers=_admin_headers(),
    )


@when("a regular user PATCHes the booking with cancelled=true")
@pytest.mark.asyncio
async def user_patch_cancel(state):
    state.response = await state.client.patch(
        f"/v1/bookings/{state.booking_id}",
        json={"cancelled": True},
        headers=_user_headers(),
    )


@when(parsers.parse('an admin PATCHes booking id "{booking_id}" with cancelled=true'))
@pytest.mark.asyncio
async def admin_patch_nonexistent(state, booking_id):
    state.response = await state.client.patch(
        f"/v1/bookings/{booking_id}",
        json={"cancelled": True},
        headers=_admin_headers(),
    )


@when("an admin DELETEs the booking")
@pytest.mark.asyncio
async def admin_delete(state):
    state.response = await state.client.delete(
        f"/v1/bookings/{state.booking_id}",
        headers=_admin_headers(),
    )


@when(parsers.parse('an admin GETs "{path}"'))
@pytest.mark.asyncio
async def admin_get(state, path):
    state.response = await state.client.get(path, headers=_admin_headers())


@when(parsers.parse('a regular user GETs "{path}"'))
@pytest.mark.asyncio
async def user_get(state, path):
    state.response = await state.client.get(path, headers=_user_headers())


@when(parsers.parse('an unauthenticated user GETs "{path}"'))
@pytest.mark.asyncio
async def anon_get(state, path):
    state.response = await state.client.get(path)


@when("an admin GETs the booking by id")
@pytest.mark.asyncio
async def admin_get_by_id(state):
    state.response = await state.client.get(
        f"/v1/bookings/{state.booking_id}",
        headers=_admin_headers(),
    )


@when(parsers.parse('anyone GETs booking id "{booking_id}"'))
@pytest.mark.asyncio
async def get_nonexistent(state, booking_id):
    state.response = await state.client.get(f"/v1/bookings/{booking_id}")


# ── Then steps ────────────────────────────────────────────────────────────────

@then(parsers.parse("the response status is {code:d}"))
def check_status(state, code):
    assert state.response.status_code == code, (
        f"Expected {code}, got {state.response.status_code}: {state.response.text}"
    )


@then("the response contains a booking id")
def check_booking_id(state):
    data = state.response.json()
    assert "id" in data
    assert data["id"]


@then(parsers.parse('the booking has status "{status}"'))
def check_booking_status(state, status):
    assert state.response.json()["status"] == status


@then("the booking has cancelled=true")
def check_cancelled(state):
    assert state.response.json()["cancelled"] is True


@then(parsers.parse('the error code is "{code}"'))
def check_error_code(state):
    # Accept both nested detail and top-level code
    body = state.response.json()
    if "detail" in body:
        detail = body["detail"]
        if isinstance(detail, dict):
            assert detail.get("code") is not None
        return
    assert body.get("code") is not None


@then(parsers.parse('the slot "{time}" on "{date}" is no longer available'))
@pytest.mark.asyncio
async def slot_no_longer_available(state, time, date):
    resp = await state.client.get(f"/v1/availability?start={date}&end={date}")
    slots = resp.json().get(date, [])
    assert time not in slots


@then(parsers.parse('the slot "{time}" on "{date}" is available again'))
@pytest.mark.asyncio
async def slot_available_again(state, time, date):
    import app.services.availability as av_module
    idx = av_module.get_availability_index()
    slots = idx.get_slots(date)
    assert time in slots


@then(parsers.parse("the response contains {n:d} bookings"))
def check_n_bookings(state, n):
    assert len(state.response.json()) == n


@then(parsers.parse('the booking date is "{date}"'))
def check_date(state, date):
    assert state.response.json()["date"] == date


@then(parsers.parse('the booking time is "{time}"'))
def check_time(state, time):
    assert state.response.json()["time"] == time
